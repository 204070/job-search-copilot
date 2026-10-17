"""Sync curated boards config into the database (idempotent, safe by default).

    python3 -m db.seed                 # boards from db/seeds/boards.jsonc
    python3 -m db.seed --prune         # also disable boards missing from config
    python3 -m db.seed --dry-run       # report what would change, write nothing

Boards sync by `name` (the stable key the scanner and add_job.py match on).
Without --prune, rows absent from the config are left alone. With --prune,
absent boards are disabled (`enabled=0`) — never deleted, so job history
stays intact. Scan-owned columns (`last_checked_at`, `updated_at`) are never
overwritten — only curated config columns.
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from db.connection import connect
_BOARDS_FILE = Path(__file__).resolve().parent / "seeds" / "boards.jsonc"
_COMMENT_LINE = re.compile(r"(?m)^\s*//.*$")
def _load_jsonc(path: Path) -> dict:
    return json.loads(_COMMENT_LINE.sub("", path.read_text(encoding="utf-8")))
def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
@dataclass
class SeedReport:
    added: int = 0
    updated: int = 0
    disabled: int = 0
    def describe(self) -> str:
        return f"boards +{self.added} ~{self.updated} -{self.disabled}"
def run_seeds(db_path=None, *, prune=False, dry_run=False) -> SeedReport:
    report = SeedReport()
    boards = _load_jsonc(_BOARDS_FILE)["boards"]
    seen = set()
    conn = connect(db_path)
    try:
        for b in boards:
            name = b["name"]; seen.add(name)
            config = json.dumps(b.get("scan_config") or {})
            row = conn.execute("SELECT kind, url, enabled, notes,"
                " scan_strategy, scan_config FROM boards WHERE name = ?",
                (name,)).fetchone()
            wanted = (b.get("kind", "job_board"), b.get("url"),
                b.get("enabled", 1), b.get("notes"),
                b.get("scan_strategy", "manual"), config)
            if row is None:
                if not dry_run: conn.execute("INSERT INTO boards (name, kind,"
                    " url, enabled, notes, scan_strategy, scan_config)"
                    " VALUES (?,?,?,?,?,?,?)", (name, *wanted))
                report.added += 1
            elif tuple(row) != wanted:
                if not dry_run: conn.execute("UPDATE boards SET kind=?, url=?,"
                    " enabled=?, notes=?, scan_strategy=?, scan_config=?"
                    " WHERE name = ?", (*wanted, name))
                report.updated += 1
        if prune:
            for row in conn.execute("SELECT name FROM boards WHERE enabled=1"):
                if row["name"] not in seen:
                    if not dry_run: conn.execute(
                        "UPDATE boards SET enabled=0 WHERE name=?",
                        (row["name"],))
                    report.disabled += 1
        if not dry_run: conn.commit()
    finally: conn.close()
    return report
def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m db.seed",
        description="Sync db/seeds/boards.jsonc into the database.")
    p.add_argument("--prune", action="store_true",
        help="disable boards absent from the config")
    p.add_argument("--dry-run", action="store_true",
        help="report changes without writing")
    p.add_argument("--db-path", type=Path, default=None)
    a = p.parse_args(argv)
    r = run_seeds(a.db_path, prune=a.prune, dry_run=a.dry_run)
    print(("DRY-RUN " if a.dry_run else "") + r.describe())
    return 0
if __name__ == "__main__":
    raise SystemExit(main())