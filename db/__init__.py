"""SQLite jobs database: connection helper and migration runner.

Typical use from the workspace root:

    from db import connect, run_migrations
    run_migrations()                 # apply db/migrations/*.sql once
    conn = connect()                 # -> db/jobs.db ($JOBS_DB_PATH overrides)

`connect` and path helpers import eagerly; migration symbols import lazily so
`python3 -m db.migrate` does not find `db.migrate` already in sys.modules.
"""

from typing import TYPE_CHECKING

from db.connection import DEFAULT_DB_PATH, connect, default_db_path

if TYPE_CHECKING:
    from db.migrate import MigrationResult, run_migrations

__all__ = [
    "DEFAULT_DB_PATH",
    "MigrationResult",
    "connect",
    "default_db_path",
    "run_migrations",
]


def __getattr__(name: str):
    """Lazily expose `run_migrations` / `MigrationResult` from db.migrate."""
    if name in ("run_migrations", "MigrationResult"):
        from db import migrate

        return getattr(migrate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

