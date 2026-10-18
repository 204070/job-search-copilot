-- =============================================================================
-- 0002_question_bank.sql — the application & interview question bank (2026-10-18).
--
-- Two-layer memory for the questions application forms ask, so "is this
-- frequently asked?" is a COUNT, not a judgement call:
--
--   questions           canonical, deduped: ONE row per DISTINCT question.
--                       Deliberately has no date and no company — just the
--                       reusable answer, the reasoning behind it, and where
--                       the answer comes from.
--   question_instances  append-only ledger: one row per time a form ACTUALLY
--                       asked it. This is the layer that keeps the provenance
--                       the canonical row omits (date, company, the option
--                       list that particular form showed).
--
-- `questions_with_frequency` is the read view (count + last asked per question)
-- and `questions_fts` is the stdlib FTS5 index that lets
-- `python3 -m db.tools.questions lookup "<field label>"` match a new form's
-- wording against everything answered before. A lookup MISS is the signal that
-- a question is novel; a hit count >= 2 is the signal that it belongs in the
-- FAQ. Neither is a guess.
--
-- SCHEMA ONLY — and deliberately so: this bank holds private answers (salary
-- expectations, work authorization), so its content belongs in the gitignored
-- database, never in a migration or `db/seeds/*.jsonc`.

-- One row per distinct question, deduped by `question_key`.
CREATE TABLE questions (
    id INTEGER PRIMARY KEY,
    -- Stable slug the agent assigns once (e.g. `compensation_expectation`).
    -- Frequency groups on this; it never changes when a form rewords things.
    question_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'application'
        CHECK (kind IN ('application', 'technical')),
    -- Normalised wording, no date/company/option list.
    canonical_text TEXT NOT NULL,
    -- The reusable answer. NULL when `answer_source` names a better home
    -- (a fact belongs in profile.jsonc, not duplicated here).
    answer TEXT,
    -- WHY this answer: the reasoning that makes it defensible and keeps a
    -- future agent from answering the same question inconsistently.
    reasoning TEXT,
    -- Where the answer really lives: 'profile:$.path' | 'answer_bank' | NULL.
    -- Facts point at profile.jsonc so there is a single source of truth.
    answer_source TEXT,
    -- Alternative wordings this form used, JSON array of strings. This is the
    -- paraphrase bridge that makes FTS matching work.
    aliases TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases)),
    -- When this question surfaced a fact that ought to move into profile.jsonc,
    -- the JSON path it should land at. A pending promotion is
    -- `promotes_to IS NOT NULL` with an answer_source that is not 'profile:%'.
    promotes_to TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'retired')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

-- Append-only ledger: one row per time a form asked the question.
CREATE TABLE question_instances (
    id INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    -- Which submission it came from; SET NULL so the learning outlives the
    -- application row.
    application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    -- The form's exact wording THIS time (the canonical text is the deduped one).
    field_label TEXT NOT NULL,
    field_type TEXT
        CHECK (field_type IS NULL OR field_type IN
               ('text', 'combobox', 'textarea', 'checkbox', 'other')),
    required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    -- The options that form actually showed, JSON array; [] for free text.
    options_seen TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(options_seen)),
    -- What was written into that field (may differ from the canonical answer).
    answer_given TEXT,
    -- When the form asked it, ISO-8601 UTC.
    asked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

CREATE INDEX idx_questions_kind_status ON questions(kind, status);
CREATE INDEX idx_question_instances_question
    ON question_instances(question_id, asked_at);
CREATE INDEX idx_question_instances_application
    ON question_instances(application_id);
CREATE INDEX idx_question_instances_job
    ON question_instances(job_id);

-- Frequency + recency in one read, mirroring the jobs_with_source convention.
CREATE VIEW questions_with_frequency AS
SELECT
    q.*,
    (SELECT COUNT(*) FROM question_instances i WHERE i.question_id = q.id)
        AS times_asked,
    (SELECT MAX(i.asked_at) FROM question_instances i WHERE i.question_id = q.id)
        AS last_asked_at
FROM questions q;

-- Full-text index over the canonical wording, answer and alias list, so a new
-- form's field label can be matched against prior questions. External-content
-- table: `questions` is the storage, the triggers below keep this in sync.
CREATE VIRTUAL TABLE questions_fts USING fts5(
    canonical_text,
    answer,
    aliases,
    content = 'questions',
    content_rowid = 'id',
    tokenize = "unicode61 remove_diacritics 2"
);

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
