-- =============================================================================
-- 0005_user_todos.sql — a home for the actions that have no row behind them
-- (2026-10-18).
--
-- The digest is a view over `db/jobs.db`, and everything it asks for is derived
-- from a row: a chase is due because an `application_events` row says so, a
-- form is unsent because the application row says `ready_to_apply`, a lead left
-- the pool because the job row is archived. That works until the thing waiting
-- on a human is not attached to anything. "Create the 8+ years resume variant"
-- is a real next action with no job, no application and no question behind it.
-- Without somewhere to put it, it lives in a chat scrollback, which is exactly
-- the memory loss the digest exists to prevent.
--
-- So the digest gains a small store of its own. It is not a general note pile:
-- `text` is an action, phrased as something to do, and closing it is the only
-- state change. The file still holds nothing — an open todo renders in section
-- 2 with the command that closes it, and disappears when that command runs.
--
--   owner     who is expected to act. 'user' is work only they can do (a
--             resume variant, a decision, a credential). 'agent' is work the
--             agent can do on its own and should not need to be asked twice.
--   context   optional free text: where the item came from and why it is
--             wanted, for the moment months later when the one-line action is
--             not self-explanatory.
--   closed_at NULL while open. There is no 'done' flag, for the same reason
--             nothing else here keeps one: a timestamp answers both "is it
--             closed" and "when", and cannot be out of step with itself.
--
-- SCHEMA ONLY.
-- =============================================================================

CREATE TABLE todos (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'user' CHECK (owner IN ('user', 'agent')),
    context TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    closed_at TEXT,
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
);

-- The digest only ever asks for the open ones.
CREATE INDEX idx_todos_open ON todos(closed_at);

-- Oldest first: an item that has been waiting longest is the one to read first.
CREATE VIEW open_todos AS
SELECT * FROM todos WHERE closed_at IS NULL ORDER BY created_at, id;
