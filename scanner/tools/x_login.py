"""One-time session setup for the X Bookmarks board.

Two paths:

    python3 -m scanner.tools.x_login --import-cookies secrets/x_cookies.json
        Preferred. Reads auth_token/ct0 from a JSON file exported from your
        normal Chrome (where you're already logged in) — no login flow ever
        runs inside the automation, so X's bot detection never sees a login
        attempt. A window opens to validate the session and save the profile;
        solve any challenge it shows.

    python3 -m scanner.tools.x_login
        Interactive fallback: log in manually in the opened window. Uses the
        real Chrome binary with webdriver patched out (a bare Playwright
        profile reads as a bot to X — that's what triggered the temporary
        login block). If X still blocks login here, use --import-cookies.

Cookie file format (chmod 600; delete afterwards if you like — the imported
session then lives only in secrets/x_profile):

    {"auth_token": "...", "ct0": "..."}

Get the values from Chrome DevTools (F12 -> Application -> Cookies ->
https://x.com); a Cookie-Editor extension list export also works. These
cookies are full account access — keep them out of chat logs and shared dirs.

Re-run whenever the daily scan logs "session expired" or a challenge. Don't
run while a cron scan is in progress (the profile is locked then).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # repo root

from playwright.sync_api import sync_playwright  # noqa: E402

from scanner.fetchers import launch_x_profile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
BOARD_NAME = "X Bookmarks"


def _profile_dir() -> Path:
    """Profile path from the board row (single source of truth); fallback if
    the migration has not been applied yet."""
    default = ROOT / "secrets" / "x_profile"
    try:
        from db import connect

        conn = connect()
        conn.row_factory = None
        row = conn.execute(
            "SELECT scan_config FROM boards WHERE name = ?", (BOARD_NAME,)
        ).fetchone()
        conn.close()
        if row:
            cfg = json.loads(row[0] or "{}")
            if cfg.get("profile_dir"):
                return (ROOT / cfg["profile_dir"]).resolve()
    except Exception:  # noqa: BLE001 - fall back to the default path
        pass
    return default.resolve()


def _cookie_values(path: Path) -> dict[str, str]:
    """Accept a simple {name: value} dict, a Cookie-Editor list export, or a
    Playwright cookies JSON ({'cookies': [...]}). Keep only x.com cookies."""
    raw = json.loads(path.read_text())
    if isinstance(raw, dict) and isinstance(raw.get("cookies"), list):
        raw = raw["cookies"]
    if isinstance(raw, list):
        return {
            c["name"]: c["value"]
            for c in raw
            if isinstance(c, dict)
            and str(c.get("domain", "x.com")).endswith("x.com")
            and "name" in c
            and "value" in c
        }
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, str)}
    raise ValueError(f"unrecognised cookie file format: {path}")


def _wait_for_feed(ctx, timeout_s: int = 600) -> bool:
    """Poll until the bookmarks feed renders (auth cookie + tweets present)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        names = {c["name"] for c in ctx.cookies()}
        if "auth_token" in names:
            page = ctx.pages[0] if ctx.pages else None
            try:
                if page and page.locator('article[data-testid="tweet"]').count() > 0:
                    return True
            except Exception:  # noqa: BLE001 - page may be mid-navigation
                pass
        time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--import-cookies",
        metavar="FILE",
        help="JSON file with auth_token/ct0 from your logged-in Chrome "
        "(preferred; no login happens inside the automation)",
    )
    args = ap.parse_args()

    profile = _profile_dir()
    profile.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(profile.parent, 0o700)  # profile holds session cookies
    print(f"Profile: {profile}")

    with sync_playwright() as p:
        ctx = launch_x_profile(p, profile, headless=False)
        try:
            if args.import_cookies:
                vals = _cookie_values(Path(args.import_cookies).expanduser())
                missing = [k for k in ("auth_token", "ct0") if not vals.get(k)]
                if missing:
                    raise ValueError(f"cookie file missing: {', '.join(missing)}")
                ctx.add_cookies([
                    {"name": n, "value": v, "domain": ".x.com", "path": "/"}
                    for n, v in vals.items()
                ])
                print("Cookies imported. Validating the session on the "
                      "bookmarks page — solve any challenge in the window.")
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(
                        "https://x.com/i/bookmarks",
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                except Exception:  # noqa: BLE001 - challenge page may stall nav
                    pass
                ok = _wait_for_feed(ctx)
            else:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://x.com/i/bookmarks", wait_until="domcontentloaded")
                print("Log in to X in the opened browser window (or re-run with "
                      "--import-cookies if X blocks automated logins).")
                print("Waiting for the bookmarks feed (up to 10 min; Ctrl+C to "
                      "stop early and keep whatever is there)...")
                try:
                    ok = _wait_for_feed(ctx)
                except KeyboardInterrupt:
                    ok = False
                print(f"Final page: {page.url}")
            print(
                "Session saved — you can close the browser window."
                if ok
                else "Saved without a confirmed feed; the daily scan will verify "
                     "and tell you if another login is needed."
            )
        finally:
            ctx.close()  # persistent profile (cookies, storage) is flushed here
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
