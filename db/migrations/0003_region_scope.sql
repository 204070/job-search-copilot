-- =============================================================================
-- 0003_region_scope.sql — where a posting says it will hire (2026-10-18).
--
-- The scan pulls from boards that are overwhelmingly US-facing (Indeed,
-- LinkedIn) plus region-gated marketplaces. Nothing in the schema said where a
-- posting was actually *open*, so 77 US-only postings and 112 unstated ones
-- looked identical on the board and the pipeline filled with work that could
-- never be taken.
--
-- This adds the triage tag, derived from the posting's own text by
-- `scanner/eligibility.py` and written by `scanner/tools/classify.py`:
--
--   worldwide     the posting says it hires anywhere
--   us_only       it demands US residence or US work authorisation
--   region_gated  it names specific countries or regions (a list to check)
--   unknown       it states no restriction — the common case, and NOT a bar
--
-- `region_evidence` is the phrase that produced the tag, so a wrong guess is
-- visible on the row instead of hiding a good lead.
--
-- The tag describes the STATED RESTRICTION, never the company's home country:
-- a US company with no location restriction stays `unknown`. And it never
-- excludes anything — a US company hiring worldwide is a first-class lead, so
-- the tag groups the board, it does not filter it.
--
-- Default 'unknown' is deliberate: an unread posting is unknown, not ineligible.
--
-- SCHEMA ONLY. The values are derived on demand and rewritten by re-running
-- the classify tool, so nothing here needs backfilling in SQL.

ALTER TABLE jobs ADD COLUMN region_scope TEXT NOT NULL DEFAULT 'unknown'
    CHECK (region_scope IN ('worldwide', 'us_only', 'region_gated', 'unknown'));

ALTER TABLE jobs ADD COLUMN region_evidence TEXT;

CREATE INDEX idx_jobs_region_scope ON jobs(region_scope);
