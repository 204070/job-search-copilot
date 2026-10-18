-- =============================================================================
-- 0001_baseline.sql — the complete system in one migration (2026-10-17).
--
-- Formerly migrations 0001-0011, squashed once the schema settled. SCHEMA
-- ONLY below — no INSERTs: curated boards and scoring terms live in
-- db/seeds/*.jsonc and scanner/keywords.jsonc (see `python3 -m db.seed`), so clones start from their
-- own defaults. History is tracked by filename in schema_migrations.

-- Sources: every origin a job can come from. `boards.id` is the source of
-- truth for `jobs.board_id` (surfaced read-only as `jobs.source` via the
-- jobs_with_source view).
CREATE TABLE boards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    -- Where the board lives: a job board site, a company careers page, an RSS
    -- feed, a referral, an agency, etc.
    kind TEXT NOT NULL DEFAULT 'job_board'
        CHECK (kind IN ('job_board', 'careers_page', 'rss', 'referral',
                        'agency', 'other')),
    url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    last_checked_at TEXT,
    -- rss / jobspy / api / html = scannable; manual / disabled = never
    -- scanned. Everything strategy-specific lives in scan_config (JSON).
    scan_strategy TEXT NOT NULL DEFAULT 'manual'
        CHECK (scan_strategy IN ('rss', 'jobspy', 'api', 'html', 'manual',
                                 'disabled')),
    scan_config TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(scan_config))
);

-- Postings: the union of everything discovered (scans, X bookmarks, manual
-- adds). Dedupe keys are the partial unique indexes below.
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    board_id INTEGER REFERENCES boards(id) ON DELETE SET NULL,
    -- Nullable and not UNIQUE: a bookmarked lead may precede its URL, and dedup
    -- is a separate concern from storage.
    url TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    -- Null means "not scored yet"; 0-100 when set.
    match_score INTEGER
        CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100),
    -- Posting text as captured, for later scoring/drafting.
    raw_text TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    -- The job's own lifecycle, independent of any application.
    status TEXT NOT NULL DEFAULT 'bookmarked'
        CHECK (
            status IN ('bookmarked', 'ready_to_apply', 'applied', 'archived')
        ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    workplace_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (workplace_type IN ('remote', 'hybrid', 'onsite', 'unknown')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    source_ref TEXT,
    last_seen_at TEXT,
    posted_at TEXT,
    -- When the user's X-bookmark feed first mentioned this job: intent, set
    -- even when the URL is already known from another board.
    bookmarked_at TEXT,
    CHECK (salary_min IS NULL OR salary_max IS NULL
           OR salary_min <= salary_max)
);

-- Applications: one per submission; the pipeline (applied -> ... -> offer)
-- advances independently of jobs.status.
CREATE TABLE applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    -- The application's own status; jobs.status only tracks bookmarking.
    status TEXT NOT NULL DEFAULT 'ready_to_apply'
        CHECK (
            status IN ('ready_to_apply', 'applied', 'screening',
                       'interviewing', 'offer', 'rejected', 'withdrawn',
                       'archived')
        ),
    -- ISO-8601 UTC date the application was submitted (null until applied).
    applied_at TEXT,
    method TEXT
        CHECK (method IS NULL OR method IN ('online_form', 'email',
                                            'referral', 'linkedin',
                                            'recruiter', 'other')),
    -- Which resume/cover-letter variant was sent, for iterating on materials.
    resume_variant TEXT,
    cover_letter_variant TEXT,
    referrer TEXT,
    -- Free-form notes: salary band discussed, contacts, etc.
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

-- Append-only timeline per application.
CREATE TABLE application_events (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL
        REFERENCES applications(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('status_change', 'applied', 'follow_up',
                              'interview', 'offer', 'rejection',
                              'withdrawal', 'note')),
    from_status TEXT,
    to_status TEXT,
    -- When the event actually happened (ISO-8601 UTC).
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- For scheduled future events (follow-up due, interview time); null otherwise.
    scheduled_for TEXT,
    summary TEXT NOT NULL,
    details TEXT,
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

CREATE INDEX idx_jobs_board_id ON jobs(board_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_applications_job_id
    ON applications(job_id);
CREATE INDEX idx_applications_status
    ON applications(status);
CREATE INDEX idx_application_events_application
    ON application_events(application_id, occurred_at);

-- Dedupe keys, both partial so NULLs never collide: boards often link the
-- same ATS page, and board-scoped ids only matter when provided.
CREATE UNIQUE INDEX ux_jobs_board_source_ref ON jobs (board_id, source_ref)
    WHERE source_ref IS NOT NULL;
CREATE UNIQUE INDEX ux_jobs_url ON jobs ((lower(url)))
    WHERE url IS NOT NULL;

-- Read-only "where did this job come from?" lookup (board name + kind).
CREATE VIEW jobs_with_source AS
SELECT j.*, b.name AS source, b.kind AS source_kind
FROM jobs j LEFT JOIN boards b ON b.id = j.board_id;

