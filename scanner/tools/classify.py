"""Tag stored jobs with where each posting says it is open.

    python3 -m scanner.tools.classify                 # all jobs, print a summary
    python3 -m scanner.tools.classify --dry-run       # show what would change
    python3 -m scanner.tools.classify --examples 5    # audit the tags by phrase
    python3 -m scanner.tools.classify --board RemoteOK
    python3 -m scanner.tools.classify --only-missing

`region_scope` is a triage tag derived from the posting's own text (see
scanner/eligibility.py), not a filter: nothing is hidden. It exists so a
US-only posting and an unstated one stop looking identical on the board.

This is a separate pass rather than part of the scan because a re-discovered
job keeps its original row (upsert only refreshes last_seen_at), so a tag
written at insert time would never refresh. Re-running this rewrites every
scope from the stored text, which also makes it safe to re-run after the
classifier improves — hence `--examples`, so the tags can be eyeballed.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner.eligibility import SCOPES  # noqa: E402
from scanner.store import classify_stored_jobs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Classify stored jobs by region scope.")
    p.add_argument("--board", help="limit to this board name")
    p.add_argument("--only-missing", action="store_true",
                   help="only rows never tagged (scope unknown, no evidence)")
    p.add_argument("--dry-run", action="store_true", help="report, write nothing")
    p.add_argument("--examples", type=int, default=0,
                   help="show up to N tagged rows per scope, with the evidence")
    args = p.parse_args(argv)

    conn = connect()
    conn.row_factory = sqlite3.Row

    board_id = None
    if args.board:
        row = conn.execute(
            "SELECT id FROM boards WHERE name = ?", (args.board,)
        ).fetchone()
        if row is None:
            p.error(f"no board named {args.board!r}")
        board_id = row["id"]

    counts, changed = classify_stored_jobs(
        conn, board_id=board_id, only_missing=args.only_missing, dry_run=args.dry_run
    )

    scope_desc = {
        "worldwide": "hires anywhere",
        "us_only": "US residence / work authorisation required",
        "region_gated": "names specific countries or regions",
        "unknown": "states no restriction (not a bar)",
    }
    total = sum(counts.values())
    where = f"board={args.board}" if args.board else "all boards"
    print(f"region_scope over {total} jobs ({where})"
          + (" [dry run]" if args.dry_run else ""))
    for scope in SCOPES:
        print(f"  {scope:<13} {counts.get(scope, 0):>4}   {scope_desc[scope]}")
    verb = "would change" if args.dry_run else "changed"
    print(f"{verb}: {changed}")

    if args.examples:
        print()
        for scope in SCOPES:
            sql = ("SELECT id, company, title, location, region_evidence FROM jobs "
                   "WHERE region_scope = ?")
            params: list = [scope]
            if board_id is not None:
                sql += " AND board_id = ?"
                params.append(board_id)
            sql += " ORDER BY id LIMIT ?"
            params.append(args.examples)
            rows = conn.execute(sql, params).fetchall()
            if not rows:
                continue
            print(f"--- {scope}")
            for r in rows:
                ev = r["region_evidence"] or "(none)"
                print(f"  #{r['id']:<5} {(r['company'] or '?')[:22]:<22} "
                      f"{(r['title'] or '')[:42]}")
                print(f"          loc={r['location']!r} evidence={ev!r}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
