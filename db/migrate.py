"""Apply `db/migrations/*.sql` in order and record what was applied.

Plain numbered `.sql` files applied in sequence as one migration history; each
file is named for the change it makes. Zero-padded numbers mean sorting by
filename is sorting numerically.

The runner:

- sorts the `.sql` files in the migrations directory;
- creates its own `schema_migrations(filename TEXT PRIMARY KEY, applied_at TEXT
  NOT NULL)` table if absent, so a fresh database can bootstrap;
- applies each unrecorded file through the connection helper and records it by
  filename only after its SQL succeeds;
- prints what it ran and what was already applied.

Run as `python3 -m db.migrate` from the workspace root, or programmatically
via `run_migrations()`. Accepts explicit migrations dir and database path so
tests can exercise ordered/partial/repeated runs against a temp directory.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from db.connection import connect, default_db_path

#: Committed migrations, resolved from this module rather than the CWD.
DEFAULT_MIGRATIONS_DIR: Path = Path(__file__).resolve().parent / "migrations"

#: Bookkeeping table created by the runner, not by a numbered migration.
TRACKING_TABLE = "schema_migrations"

_CREATE_TRACKING_TABLE = (
    f"CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} ("
    "filename TEXT PRIMARY KEY, "
    "applied_at TEXT NOT NULL"
    ")"
)

_SELECT_APPLIED = f"SELECT filename FROM {TRACKING_TABLE}"
_INSERT_APPLIED = (
    f"INSERT INTO {TRACKING_TABLE} (filename, applied_at) VALUES (?, ?)"
)


@dataclass(frozen=True)
class MigrationResult:
    """What one `run_migrations()` did: applied now vs already recorded."""

    applied: tuple[str, ...]
    already_applied: tuple[str, ...]

    @property
    def applied_count(self) -> int:
        return len(self.applied)

    @property
    def already_applied_count(self) -> int:
        return len(self.already_applied)

    def describe(self) -> str:
        """One line: what this run applied and how many were already in."""
        noun = "migration" if self.applied_count == 1 else "migrations"
        summary = f"Applied {self.applied_count} {noun}"
        if self.applied:
            summary += ": " + ", ".join(self.applied)
        return f"{summary} ({self.already_applied_count} already applied)."


def _utc_now() -> str:
    """Current time as ISO-8601 UTC text."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_migrations(
    migrations_dir: Path | str | None = None,
    db_path: Path | str | None = None,
) -> MigrationResult:
    """Apply unrecorded `.sql` files and return what was applied.

    `migrations_dir` defaults to the committed `db/migrations/`; `db_path`
    defaults to the configured database path. An empty or missing directory is
    not an error: nothing applies and the tracking table is still created.
    """
    directory = (
        Path(migrations_dir) if migrations_dir is not None
        else DEFAULT_MIGRATIONS_DIR
    )
    files = (
        sorted(directory.glob("*.sql"), key=lambda path: path.name)
        if directory.is_dir()
        else []
    )

    connection = connect(db_path)
    try:
        connection.execute(_CREATE_TRACKING_TABLE)
        connection.commit()
        recorded = {
            row["filename"] for row in connection.execute(_SELECT_APPLIED)
        }

        applied: list[str] = []
        for path in files:
            if path.name in recorded:
                continue
            connection.executescript(path.read_text(encoding="utf-8"))
            connection.execute(_INSERT_APPLIED, (path.name, _utc_now()))
            connection.commit()
            applied.append(path.name)
    finally:
        connection.close()

    applied_names = tuple(applied)
    already_applied = tuple(
        path.name
        for path in files
        if path.name in recorded and path.name not in applied_names
    )
    return MigrationResult(applied=applied_names, already_applied=already_applied)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the migrations and print what was applied; exit 0 on success."""
    parser = argparse.ArgumentParser(
        prog="python3 -m db.migrate",
        description="Apply db/migrations/*.sql to the configured database.",
    )
    parser.add_argument(
        "--migrations-dir", type=Path, default=None,
        help="Directory of numbered .sql files (default: db/migrations/).",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help=f"Database file to migrate (default: {default_db_path()}).",
    )
    args = parser.parse_args(argv)

    result = run_migrations(
        migrations_dir=args.migrations_dir,
        db_path=args.db_path,
    )
    print(result.describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
