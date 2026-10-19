"""CLI entry point: scan all enabled boards, store jobs, surface matches.

    python3 -m scanner                  # full run, report to stdout + logs
    python3 -m scanner --board RemoteOK # one board only
    python3 -m scanner --dry-run        # fetch + score, write nothing
    python3 -m scanner --min-score 25   # override lead threshold

New matches (score >= threshold) are appended to
logs/leads/YYYY-MM-DD.md so one day's cron runs accumulate.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root

from db import connect  # noqa: E402
from scanner import fetchers  # noqa: E402
from scanner.eligibility import SCOPES, classify, scope_rank  # noqa: E402
from scanner.keywords import Matcher, min_score  # noqa: E402
from scanner.store import classify_stored_jobs, now_iso, upsert_job  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEADS_DIR = ROOT / "logs" / "leads"


def _lead_order(item: dict) -> tuple:
    """Report sort key: where it hires first, then score.

    A named region that includes us (EMEA, Africa) beats "says nothing", and
    both beat a list that excludes us, so 77 "Remote, USA" postings stop
    burying everything else on the page. Ordering lives in the classifier.
    """
    return scope_rank(item["scope"], item.get("evidence")), -item["match_score"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scan enabled job boards.")
    p.add_argument("--board", help="scan only the board with this name")
    p.add_argument("--dry-run", action="store_true", help="fetch and report, but do not write")
    p.add_argument("--min-score", type=int, default=None, help="lead threshold (default 15)")
    args = p.parse_args(argv)

    conn = connect()
    conn.row_factory = sqlite3.Row
    matcher = Matcher()
    threshold = args.min_score if args.min_score is not None else min_score()

    sql = "SELECT * FROM boards WHERE enabled = 1"
    params: list = []
    if args.board:
        sql += " AND name = ?"
        params.append(args.board)
    else:
        sql += " AND scan_strategy NOT IN ('manual')"  # manual = by hand only
    boards = conn.execute(sql + " ORDER BY id", params).fetchall()

    run_ts = now_iso()
    lines: list[str] = []          # report lines
    matches: list[dict] = []
    bookmarked: list[dict] = []    # X-bookmark intent (any score)
    new_total = seen_total = 0
    errors: list[str] = []

    # Postings the store already holds text for. A board whose assurance of a
    # description is its posting's own page (the HTML list boards) is told this
    # so it only pays that request where the text is missing, instead of
    # re-reading every posting on every run.
    described = {
        (row["url"] or "").lower()
        for row in conn.execute(
            "SELECT url FROM jobs WHERE url IS NOT NULL "
            "AND raw_text IS NOT NULL AND trim(raw_text) <> ''"
        )
    }

    for board in boards:
        name, strategy = board["name"], board["scan_strategy"]
        cfg = json.loads(board["scan_config"] or "{}")
        mode = cfg.get("mode")
        if strategy == "manual" or (
            strategy == "html" and mode not in fetchers.KNOWN_HTML_MODES
        ):
            lines.append(f"- {name}: strategy `{strategy}` — not scanned yet")
            continue
        if cfg.get("on_demand") and not args.board:
            # Runs when asked for, never on a scheduled or full run: this board
            # needs a browser the user is driving, or costs more than it is worth.
            lines.append(f"- {name}: on demand only — `--board {name}` to scan it")
            continue
        try:
            jobs = fetchers.fetch(board, described)
        except Exception as exc:  # noqa: BLE001 - one bad board must not stop the run
            errors.append(f"{name}: {exc}")
            lines.append(f"- {name}: ERROR {exc}")
            traceback.print_exc()
            continue
        new = seen = 0
        for job in jobs:
            if not job.get("title") or not job.get("url"):
                continue  # incomplete posting; nothing to score or apply to
            job["company"] = (job.get("company") or "").strip() or "Unknown"
            score, matched = matcher.score(job.get("title"), job.get("description"))
            job["match_score"] = score
            scope, scope_evidence = classify(
                job.get("location"), job.get("description")
            )
            if args.dry_run:
                status = "new"  # nothing written
            else:
                status, _job_id = upsert_job(conn, board["id"], job)
            if status == "new":
                new += 1
                if score >= threshold:
                    matches.append({**job, "board": name, "matched": matched,
                                    "scope": scope, "evidence": scope_evidence})
            else:
                seen += 1
            if (job.get("metadata") or {}).get("bookmarked"):
                bookmarked.append({**job, "board": name, "status": status,
                                   "scope": scope, "evidence": scope_evidence})
        if not args.dry_run:
            conn.execute(
                "UPDATE boards SET last_checked_at = ? WHERE id = ?",
                (run_ts, board["id"]),
            )
            conn.commit()
        new_total += new
        seen_total += seen
        lines.append(f"- {name}: {len(jobs)} fetched, {new} new, {seen} already known")

    # --- report -----------------------------------------------------------
    # Re-tag the stored rows after the run so region_scope stays current even
    # for jobs this scan only re-saw (upsert refreshes last_seen_at only).
    scope_counts = None
    if not args.dry_run:
        scope_counts, _changed = classify_stored_jobs(conn)

    today = run_ts[:10]
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = LEADS_DIR / f"{today}.md"
    body = [f"\n## Run {run_ts}" + (" (dry run)" if args.dry_run else ""),
            f"Threshold: score >= {threshold} | new: {new_total} | already known: {seen_total}",
            "\n### Boards"]
    body.extend(lines)
    if scope_counts is not None:
        body.append("\n### Region scope (whole board)")
        body.append("  " + " | ".join(
            f"{scope}: {scope_counts.get(scope, 0)}" for scope in SCOPES))
    if matches:
        body.append(f"\n### New matches ({len(matches)})")
        body.append("Sorted by region scope first: a role that names a region "
                    "you are in (EMEA, Africa) ranks with one that states no "
                    "restriction, and both rank above a list that excludes you "
                    "or demands US work authorisation.")
        for m in sorted(matches, key=_lead_order):
            body.append(f"- **{m['match_score']}** [{m['scope']}] {m['title']}"
                        f" — {m.get('company') or '?'} [{m['board']}] ({', '.join(m['matched'])})\n  {m['url']}")
    else:
        body.append("\nNo new matches this run.")
    if bookmarked:
        # Bookmark = user intent: shown regardless of match threshold.
        body.append(f"\n### Bookmarked on X ({len(bookmarked)})")
        for b in sorted(bookmarked, key=_lead_order):
            body.append(f"- **{b['match_score']}** [{b['scope']}] {b['title']}"
                        f" — {b.get('company') or '?'} ({b['status']})\n  {b['url']}")
    if errors:
        body.append("\n### Errors")
        body.extend(f"- {e}" for e in errors)
    report = "\n".join(body) + "\n"
    print(report)
    if not args.dry_run:
        new_file = not report_path.exists()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "a", encoding="utf-8") as f:
            if new_file:
                f.write(f"# Leads {today}\n")
            f.write(report)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
