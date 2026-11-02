-- Per-employer score weights for the "Next roles" shortlist.
--
-- The shortlist already derives a seven-day cooldown from applications. This
-- table is the longer memory: an employer whose requirements or history make a
-- rejection likely, or one we have already written to several times, can be
-- pushed down the page by a named number, with the reason recorded beside it.
--
-- It is data rather than code, so the decision changes without editing the
-- digest, and it lives in the database rather than in a committed file because
-- it names employers. `company_key` is the employer name lowercased, trimmed
-- and whitespace-collapsed, so "M-KOPA" and "m-kopa" are one row.
--
-- A weight is added to the posting's match score before the shortlist is
-- ordered. Negative demotes; the raw score stays in the table so the decision
-- is visible rather than silently baked in.
CREATE TABLE employer_weights (
    company_key TEXT PRIMARY KEY,
    weight INTEGER NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
