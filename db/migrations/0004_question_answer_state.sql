-- =============================================================================
-- 0004_question_answer_state.sql — a stored review flag becomes a derived state
-- (2026-10-18).
--
-- `questions.status` held 'draft' | 'approved' | 'retired', and the middle one
-- recorded that a human had read the answer and judged it safe to reuse. It
-- did not survive contact with how the bank is actually used. The real bank
-- read `approved` on all 18 rows the day one command was run over it, and only
-- 10 of those rows had ever been on a submitted application at all: the flag
-- recorded that a terminal command had been typed, not that anyone had read
-- anything. Nor could it: the review that matters already happened at
-- handover, before submission, so approving afterwards asked for the same
-- judgement twice and then recorded only the second one.
--
-- What is left is a state nothing has to remember, derived from the instance
-- ledger on read:
--
--   unsent   no form that reached an employer has ever carried this question
--   sent     the bank's current text is exactly what some employer received
--   revised  it went out, and the stored text has changed since, so what is
--            stored is NOT what anyone received — the one state worth putting
--            in front of a human
--   retired  a deliberate decision never to reuse this again
--
-- "Reached an employer" is `applications.applied_at`, not the application's
-- current status: an application withdrawn after it went out still carried the
-- text, and a state that un-sends it would be a lie. `last_sent_text` is kept
-- beside the state so a `revised` row can show its own diff.
--
-- RETIREMENT IS THE ONE MANUAL ACTION, so it is the only thing stored:
-- `retired_at` is NULL for a row in use and a timestamp for one set aside.
--
-- Also fixes two rows where `answer` held a NOTE ABOUT AN EVENT instead of a
-- reusable answer (what a US-state dropdown did when it had no option for the
-- applicant's own city, and what channel list a form offered). The notes move to
-- `metadata.original_answer`, which the FAQ already renders as "Earlier
-- answer", and `answer` goes back to meaning the reusable text. Without that,
-- the sent/revised comparison is comparing a note with an answer.
--
-- SCHEMA + TWO ROW FIXES. No content beyond those two rows is touched; every
-- other answer, alias and instance is copied verbatim.
-- =============================================================================

-- Rebuilding `questions` means dropping the old table, and it is the parent of
-- `question_instances`, whose foreign key is ON DELETE CASCADE: with foreign
-- keys enforced, the drop would silently take the whole instance ledger with
-- it. The pragma must be set outside the transaction, and the transaction
-- keeps the swap atomic.
PRAGMA foreign_keys = OFF;
BEGIN;

-- Drop the read view first: it references `questions`, and the rename below
-- recompiles every view, which fails with the table momentarily gone. It is
-- recreated at the end with the derived state.
DROP VIEW questions_with_frequency;

CREATE TABLE questions_new (
    id INTEGER PRIMARY KEY,
    question_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'application'
        CHECK (kind IN ('application', 'technical')),
    canonical_text TEXT NOT NULL,
    answer TEXT,
    reasoning TEXT,
    answer_source TEXT,
    aliases TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases)),
    promotes_to TEXT,
    -- NULL while the answer is in use; set when it is deliberately retired.
    retired_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

INSERT INTO questions_new
    (id, question_key, kind, canonical_text, answer, reasoning, answer_source,
     aliases, promotes_to, retired_at, created_at, updated_at, metadata)
SELECT
    id, question_key, kind, canonical_text, answer, reasoning, answer_source,
    aliases, promotes_to,
    CASE WHEN status = 'retired' THEN updated_at END,
    created_at, updated_at, metadata
FROM questions;

DROP TABLE questions;
ALTER TABLE questions_new RENAME TO questions;

CREATE INDEX idx_questions_kind_retired ON questions(kind, retired_at);

-- The FTS triggers went with the dropped table; recreate them against the new
-- one and rebuild the index so it holds the copied rows.
CREATE TRIGGER questions_fts_insert AFTER INSERT ON questions BEGIN
    INSERT INTO questions_fts (rowid, canonical_text, answer, aliases)
    VALUES (new.id, new.canonical_text, coalesce(new.answer, ''), new.aliases);
END;

CREATE TRIGGER questions_fts_delete AFTER DELETE ON questions BEGIN
    INSERT INTO questions_fts (questions_fts, rowid, canonical_text, answer, aliases)
    VALUES ('delete', old.id, old.canonical_text, coalesce(old.answer, ''), old.aliases);
END;

CREATE TRIGGER questions_fts_update AFTER UPDATE ON questions BEGIN
    INSERT INTO questions_fts (questions_fts, rowid, canonical_text, answer, aliases)
    VALUES ('delete', old.id, old.canonical_text, coalesce(old.answer, ''), old.aliases);
    INSERT INTO questions_fts (rowid, canonical_text, answer, aliases)
    VALUES (new.id, new.canonical_text, coalesce(new.answer, ''), new.aliases);
END;

INSERT INTO questions_fts (questions_fts) VALUES ('rebuild');

-- The read view gains the derived state. `sent` when ANY employer received
-- exactly this text: a later rewrite of the bank must not unsend the answer an
-- employer already holds. A row whose answer lives elsewhere (a profile fact)
-- has no literal text to compare, so an application that carried it counts as
-- sent rather than revised forever.
CREATE VIEW questions_with_frequency AS
SELECT
    q.*,
    (SELECT COUNT(*) FROM question_instances i WHERE i.question_id = q.id)
        AS times_asked,
    (SELECT MAX(i.asked_at) FROM question_instances i WHERE i.question_id = q.id)
        AS last_asked_at,
    CASE
        WHEN q.retired_at IS NOT NULL THEN 'retired'
        WHEN NOT EXISTS (
            SELECT 1 FROM question_instances i
            JOIN applications a ON a.id = i.application_id
            WHERE i.question_id = q.id AND a.applied_at IS NOT NULL
        ) THEN 'unsent'
        WHEN q.answer IS NULL THEN 'sent'
        WHEN EXISTS (
            SELECT 1 FROM question_instances i
            JOIN applications a ON a.id = i.application_id
            WHERE i.question_id = q.id AND a.applied_at IS NOT NULL
              AND trim(i.answer_given) = trim(q.answer)
        ) THEN 'sent'
        ELSE 'revised'
    END AS state,
    (SELECT i.answer_given FROM question_instances i
     JOIN applications a ON a.id = i.application_id
     WHERE i.question_id = q.id AND a.applied_at IS NOT NULL
     ORDER BY i.asked_at DESC, i.id DESC LIMIT 1) AS last_sent_text
FROM questions q;

-- --- the two note-not-answer rows -------------------------------------------

-- A form asked for a US state and the list had no option for the applicant's
-- own city. What was typed is an event, not an answer; the reusable answer is
-- what to put in that field next time, and the fact behind it lives in
-- profile.jsonc (`location.city`).
UPDATE questions
   SET answer = 'N/A (not a US state)',
       metadata = json_set(
           metadata, '$.original_answer',
           'Attempted the city name / "Remote" / "N/A"; the dropdown listed US states only.'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 WHERE question_key = 'current_state';

-- The reusable answer is the honest catch-all; the guidance about when to name
-- the board instead belongs in `reasoning`, which is what it was. Which board
-- surfaced a given posting is recorded on that question's instance.
UPDATE questions
   SET answer = 'Other online job boards',
       reasoning = 'Name the channel that actually surfaced the posting. When an'
                   || ' aggregator did, take the form''s catch-all rather than'
                   || ' implying a claim you cannot back; when the field is free'
                   || ' text, name the board. The radio-list form offered'
                   || ' "Other online job boards (found via Real Work From Anywhere)"'
                   || ' and the free-text one took "Real Work From Anywhere (job board)".',
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 WHERE question_key = 'where_did_you_hear_about_this_vacancy';

COMMIT;
PRAGMA foreign_keys = ON;
