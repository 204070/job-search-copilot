"""The single SQLite connection helper for this workspace's jobs database.

All database access goes through `connect()`, using the standard library
`sqlite3` module: no ORM, no query builder. Row factory, foreign-key
enforcement and WAL mode are set once, per connection, here.

`connect()` with no argument opens `JOBS_DB_PATH` (env var, default
`db/jobs.db` next to this package). Passing an explicit path opens that path
instead — how tests point at a throwaway database. `":memory:"` is supported.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

#: Default database file: db/jobs.db inside this package.
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "jobs.db"


def default_db_path() -> Path:
    """The database path: $JOBS_DB_PATH if set, else db/jobs.db."""
    override = os.environ.get("JOBS_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection to `db_path`, or to `default_db_path()` when `None`.

    Every returned connection gets:

    - `row_factory = sqlite3.Row`, so rows read by column name;
    - `PRAGMA foreign_keys = ON` (off by default in SQLite);
    - WAL journal mode, so reads and writes do not block each other.

    A missing parent directory is created first so the first connection to a
    fresh checkout does not fail.
    """
    target: Path | str = default_db_path() if db_path is None else db_path
    if target != ":memory:":
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(target))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection
