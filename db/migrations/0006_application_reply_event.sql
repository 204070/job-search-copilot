-- =============================================================================
-- 0006_application_reply_event.sql — a reply is contact; a note is our own
-- bookkeeping (2026-10-18).
--
-- The day-7 chase clock was suppressed by any of interview / offer / rejection /
-- note / follow_up. Two of those are not the other side at all: a `note` is our
-- own annotation ("recon done", "form filled in one pass") and a `follow_up` is
-- our own chase. The defect showed on the day an application went out: the
-- digest read "no action (a reply is on record)" on an application nobody had
-- answered, which is precisely the case the clock exists for, and the better the
-- application was documented the more reliably it happened.
--
-- The signal means "the employer made contact". Contact that moves no status (a
-- recruiter asking a question, an acknowledgement, a rejection of one role but
-- interest in another) needs a type of its own, so `reply` joins the list, and
-- `review reply` is the command that writes one. `db/tools/review.py` holds the
-- authoritative list in SIGNAL_EVENT_TYPES.
--
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt. SCHEMA ONLY:
-- no rows are written here, and the copy below carries the existing events over
-- unchanged.
-- =============================================================================

CREATE TABLE application_events_new (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL
        REFERENCES applications(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('status_change', 'applied', 'follow_up',
                              'interview', 'offer', 'rejection',
                              'withdrawal', 'note', 'reply')),
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

INSERT INTO application_events_new (id, application_id, event_type, from_status,
                                    to_status, occurred_at, scheduled_for,
                                    summary, details, metadata)
SELECT id, application_id, event_type, from_status, to_status, occurred_at,
       scheduled_for, summary, details, metadata
  FROM application_events;

DROP TABLE application_events;

ALTER TABLE application_events_new RENAME TO application_events;

CREATE INDEX idx_application_events_application
    ON application_events(application_id, occurred_at);
