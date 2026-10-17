"""Fetchers: one function per scan strategy.

All return a list of plain dicts with the keys `store.upsert_job` accepts
(title, company, url, source_ref, description, location, workplace_type,
salary_min/max/currency, posted_at, metadata). Fetchers never write to the
database; they only fetch and normalise.
"""
from __future__ import annotations

import email.utils
import html
import json
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

USER_AGENT = "job-search-copilot/1.0 (personal job-search bot)"


def _http_get(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https feeds only)
        return resp.read()


def strip_html(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _iso(value) -> str | None:
    """RFC-822 or ISO date -> ISO-8601 date string, or None."""
    if not value or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        return email.utils.parsedate_to_datetime(str(value)).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _clean(value):
    """JobSpy dataframes use NaN for missing values."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def _parse_xml(body: bytes):
    """Parse XML, tolerating the common malformation of real-world feeds
    (bare '&' in titles/descriptions). Used by fetch_rss."""
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        return ET.fromstring(re.sub(rb"&(?!#\w{1,8};|\w{2,10};)", b"&amp;", body))


# --- api (remotive, remoteok) ----------------------------------------------

def fetch_api(board: dict, cfg: dict) -> list[dict]:
    """Public JSON API board. One branch per supported source; add a branch
    (or a key->field mapping in scan_config) for the next API board."""
    source = cfg.get("source")
    if source == "remotive":
        data = json.loads(_http_get(cfg["endpoint"]))
        items = data.get("jobs", [])
    elif source == "remoteok":
        data = json.loads(_http_get(cfg["endpoint"]))
        # First element is a legal/meta notice dict, not a job.
        items = [j for j in data if isinstance(j, dict) and j.get("position")]
    else:
        raise ValueError(f"unsupported api source: {source!r}")

    jobs = []
    for j in items:
        if source == "remotive":
            jobs.append({
                "title": j.get("title"),
                "company": j.get("company_name"),
                "url": j.get("url"),
                "source_ref": str(j["id"]) if j.get("id") is not None else None,
                "description": strip_html(j.get("description")),
                "location": j.get("candidate_required_location") or None,
                "workplace_type": "remote",  # remotive is remote-only
                "posted_at": _iso(j.get("publication_date")),
                "metadata": {"salary_raw": j.get("salary")} if j.get("salary") else {},
            })
        else:  # remoteok
            jobs.append({
                "title": j.get("position"),
                "company": j.get("company"),
                "url": j.get("url"),
                "source_ref": str(j["id"]) if j.get("id") is not None else None,
                "description": strip_html(j.get("description")),
                "location": j.get("location") or None,
                "workplace_type": "remote",  # remote-only board
                "posted_at": _iso(j.get("date")),
                "salary_min": (j.get("salary_min") or None),  # 0 means unknown
                "salary_max": (j.get("salary_max") or None),
                "metadata": {"tags": j.get("tags") or []},
            })
    return jobs


# --- jobspy ----------------------------------------------------------------

def fetch_jobspy(board: dict, cfg: dict) -> list[dict]:
    """Scrape a JobSpy-supported board (indeed, linkedin, zip_recruiter,
    glassdoor, bayt, ...). Requires `pip install python-jobspy`."""
    from jobspy import scrape_jobs  # deferred: optional dependency

    df = scrape_jobs(
        site_name=cfg["source"],
        search_term=cfg.get("search_term"),
        location=cfg.get("location"),
        results_wanted=cfg.get("results_wanted", 25),
        hours_old=cfg.get("hours_old"),
    )
    if df is None or df.empty:
        return []
    jobs = []
    for r in df.to_dict("records"):
        title = _clean(r.get("title"))
        url = _clean(r.get("job_url_direct")) or _clean(r.get("job_url"))
        if not title or not url:
            continue
        is_remote = _clean(r.get("is_remote"))
        meta = {"site": _clean(r.get("site"))}
        if _clean(r.get("job_type")):
            meta["job_type"] = _clean(r.get("job_type"))
        if _clean(r.get("min_amount")) is not None:
            meta["salary_interval"] = _clean(r.get("interval"))
        jobs.append({
            "title": title,
            "company": _clean(r.get("company")),
            "url": url,
            "source_ref": str(_clean(r.get("id"))) or url,
            "description": strip_html(_clean(r.get("description"))),
            "location": _clean(r.get("location")),
            "workplace_type": "remote" if is_remote else "unknown",
            "posted_at": _iso(_clean(r.get("date_posted"))),
            "salary_min": _clean(r.get("min_amount")),
            "salary_max": _clean(r.get("max_amount")),
            "salary_currency": _clean(r.get("currency")),
            "metadata": meta,
        })
    return jobs


# --- html (mode-driven browser / selector scraping) ---------------------------

# An `html`-strategy board names its parser in scan_config["mode"]. Modes that
# do not appear here are reported as "not scanned yet", so boards can be seeded
# before their parser exists (see boards.notes + migrations 0009/0010).
KNOWN_HTML_MODES = {"x_bookmarks", "x_bookmarks_cli"}


def fetch_html(board: dict, cfg: dict) -> list[dict]:
    mode = cfg.get("mode")
    if mode == "x_bookmarks":
        return fetch_x_bookmarks(board, cfg)
    if mode == "x_bookmarks_cli":
        return fetch_x_bookmarks_cli(board, cfg)
    raise ValueError(f"no parser for html mode {mode!r}")


def _resolve_tco(url: str) -> str:
    """Follow an X t.co short link to the final URL. Best effort: on failure
    the short link itself is returned."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT}, method=method
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                return resp.geturl()
        except Exception:  # noqa: BLE001 - resolver is best-effort
            continue
    return url


# Shared X session launcher (scanner fetcher + tools/x_login use the exact
# same browser shape, so what the login helper validates is what cron runs).
# X's risk engine flags: Playwright's bundled Chromium binary (real Chrome
# with channel="chrome" is indistinguishable from a normal install) and
# navigator.webdriver=true (patched out via init script). A login attempt
# from automation is what gets accounts temporarily blocked — prefer
# importing cookies from your logged-in Chrome (see tools/x_login.py).
X_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]
X_STEALTH_INIT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)
_UA_TMPL = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
)


def _real_chrome_ua() -> str | None:
    """UA string matching the installed Chrome's major version — headless
    Chromium otherwise reports 'HeadlessChrome' and is trivially detected."""
    import re
    import subprocess

    for cmd in ("google-chrome", "google-chrome-stable"):
        try:
            out = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=5
            ).stdout
            m = re.search(r"(\d+)\.\d+", out)
            if m:
                return _UA_TMPL.format(v=m.group(1))
        except Exception:  # noqa: BLE001 - try the next binary name
            continue
    return None


def launch_x_profile(p, profile: "Path", headless: bool):
    """Persistent Chromium context for the X session profile.

    Uses the system's real Google Chrome when present (falls back to the
    bundled Chromium), with webdriver hidden, first-run noise disabled, and
    the UA patched to a non-headless string.
    """
    kwargs = dict(
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        args=X_STEALTH_ARGS,
    )
    ua = _real_chrome_ua()
    if ua:
        kwargs["user_agent"] = ua  # Playwright also syncs client hints to it
    try:
        ctx = p.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=headless, **kwargs
        )
    except Exception:  # noqa: BLE001 - no system Chrome installed
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=headless, **kwargs
        )
    ctx.add_init_script(X_STEALTH_INIT)
    return ctx


def _parse_bookmark_tweets(page, cap: int) -> list[dict]:
    """Extract job candidates from a loaded X bookmarks page (Playwright page).

    One row per external link inside a tweet; a tweet with no link still
    becomes one row pointing at the tweet itself, so every bookmark is kept.
    """
    jobs: list[dict] = []
    seen_paths: set[str] = set()
    for art in page.locator('article[data-testid="tweet"]').all():
        if len(jobs) >= cap:
            break
        link = art.locator('a[href*="/status/"]').first
        path = link.get_attribute("href") if link.count() else None
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        permalink = urljoin("https://x.com", path)
        text_el = art.locator('[data-testid="tweetText"]').first
        text = text_el.inner_text().strip() if text_el.count() else ""
        time_el = art.locator("time").first
        posted = time_el.get_attribute("datetime") if time_el.count() else None
        # External links inside the tweet body (X wraps them in t.co).
        targets: list[str] = []
        if text_el.count():
            for a in art.locator('[data-testid="tweetText"] a[href^="https://t.co/"]').all():
                href = a.get_attribute("href")
                if not href:
                    continue
                final = _resolve_tco(href)
                if final.rstrip("/") != permalink.rstrip("/") and final not in targets:
                    targets.append(final)
        if not targets:
            targets = [permalink]
        title = re.sub(r"\s+", " ", text) or f"X bookmark {path.rsplit('/', 1)[-1]}"
        for i, target in enumerate(targets):
            jobs.append({
                "title": title[:160],
                "company": None,  # unknown; __main__ stores 'Unknown'
                "url": target,
                "source_ref": path if i == 0 else f"{path}#{i}",
                "description": text or None,
                "location": None,
                "workplace_type": "unknown",
                "posted_at": _iso(posted),
                "metadata": {"via": "x_bookmarks", "tweet": permalink, "bookmarked": 1},
            })
    return jobs


def fetch_x_bookmarks(board: dict, cfg: dict) -> list[dict]:
    """The user's X (Twitter) bookmarks, read from a logged-in Chromium profile.

    The official API has no bookmark read on Free/Basic tiers (Pro+ only) and
    v1.1 dies Sep 2026, so this uses the user's own session instead:
    one-time interactive login via `python3 -m scanner.tools.x_login` creates
    the persistent profile; the daily cron reuses it headlessly.

    scan_config keys:
        profile_dir  (required, repo-relative) persistent Chromium profile
        scrolls  default 3   downward scrolls to load older bookmarks
        cap      default 60  max rows per run
    """
    from playwright.sync_api import sync_playwright  # deferred optional dependency

    profile = (Path(__file__).resolve().parent.parent / cfg["profile_dir"]).resolve()
    if not profile.exists() or not any(profile.iterdir()):
        raise RuntimeError(
            f"no X session profile at {profile} — run once: "
            "`python3 -m scanner.tools.x_login`"
        )

    jobs: list[dict] = []
    with sync_playwright() as p:
        ctx = launch_x_profile(p, profile, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(
                "https://x.com/i/bookmarks",
                wait_until="domcontentloaded",  # a Turnstile stall skips 'load'
                timeout=45000,
            )
            if "/login" in page.url:
                raise RuntimeError(
                    "X session expired — rerun: python3 -m scanner.tools.x_login"
                )
            if page.locator("iframe[src*='challenges.cloudflare.com']").count():
                raise RuntimeError(
                    "Cloudflare challenge on bookmarks — rerun x_login "
                    "(headed) and solve it there"
                )
            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            except Exception as exc:
                raise RuntimeError(
                    f"no bookmarks visible at {page.url!r} — session may have "
                    "expired or a challenge appeared; rerun x_login"
                ) from exc
            for _ in range(int(cfg.get("scrolls", 3))):
                page.mouse.wheel(0, 7000)
                page.wait_for_timeout(1200)
            jobs = _parse_bookmark_tweets(page, int(cfg.get("cap", 60)))
        finally:
            ctx.close()  # persistent profile state is flushed on close
    return jobs


# Hosts that are X plumbing, not job links: t.co links resolving here are
# media/profile navigation and would create junk job rows.
_X_INTERNAL_HOSTS = {
    "t.co", "x.com", "twitter.com", "video.twimg.com", "pbs.twimg.com",
    "abs.twimg.com",
}


def _parse_opencli_tweets(tweets: list[dict], cap: int) -> list[dict]:
    """Same row shape as _parse_bookmark_tweets, from opencli's JSON dicts
    (keys: id, author, name, text, created_at, url, ...)."""
    jobs: list[dict] = []
    seen_paths: set[str] = set()
    for t in tweets:
        if len(jobs) >= cap:
            break
        path = urllib.parse.urlparse(t.get("url") or "").path
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        permalink = urljoin("https://x.com", path)
        text = (t.get("text") or "").strip()
        # opencli: "Fri Oct 16 09:20:20 +0000 2026"; _iso handles ISO/RFC-822.
        try:
            posted = _iso(datetime.strptime(
                t["created_at"], "%a %b %d %H:%M:%S %z %Y"))
        except (KeyError, TypeError, ValueError):
            posted = _iso(t.get("created_at"))
        targets: list[str] = []
        for short in re.findall(r"https://t\.co/\w+", text):
            final = _resolve_tco(short)
            if urllib.parse.urlparse(final).netloc.lower() in _X_INTERNAL_HOSTS:
                continue
            if final.rstrip("/") != permalink.rstrip("/") and final not in targets:
                targets.append(final)
        if not targets:
            targets = [permalink]
        title = re.sub(r"\s+", " ", text) or f"X bookmark {path.rsplit('/', 1)[-1]}"
        for i, target in enumerate(targets):
            jobs.append({
                "title": title[:160],
                "company": None,  # unknown; __main__ stores 'Unknown'
                "url": target,
                "source_ref": path if i == 0 else f"{path}#{i}",
                "description": text or None,
                "location": None,
                "workplace_type": "unknown",
                "posted_at": posted,
                "metadata": {"via": "x_bookmarks", "tweet": permalink, "bookmarked": 1},
            })
    return jobs


def fetch_x_bookmarks_cli(board: dict, cfg: dict) -> list[dict]:
    """The user's X bookmarks via OpenCLI's Browser Bridge (primary path).

    Reads from the user's REAL logged-in Chrome through the installed
    extension — no automation browser, no session import, no bot detection.
    Requires: the opencli daemon running, Browser Bridge extension installed
    in Chrome, Chrome open, and X logged in (opencli doctor diagnoses all).
    The Playwright fetcher (mode 'x_bookmarks') stays as the dormant
    fallback for when Chrome can't be open.

    scan_config keys:
        profile  bridge profile id when several Chrome profiles are
                 connected (opencli profile list; doctor names them)
        cap      default 50  max bookmarks pulled (opencli --limit)
        timeout  default 120 subprocess timeout, seconds
    """
    import os
    import subprocess

    limit = int(cfg.get("cap", 50))
    cmd = [
        "opencli", "twitter", "bookmarks", "--limit", str(limit),
        "-f", "json", "--window", "background",  # background: no focus steal
    ]
    env = dict(os.environ)
    if cfg.get("profile"):
        env["OPENCLI_PROFILE"] = str(cfg["profile"])
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=int(cfg.get("timeout", 120)), env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "opencli not installed — see https://github.com/jackwener/opencli"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "opencli bookmarks timed out — is Chrome open? (opencli doctor)"
        ) from exc
    out = (res.stdout or "").strip()
    start = out.find("[")
    if res.returncode != 0 or start < 0:
        msg = out or (res.stderr or "").strip() or f"exit {res.returncode}"
        raise RuntimeError(
            f"opencli bookmarks failed: {msg[:300]} — run `opencli doctor`"
        )
    try:
        tweets, _end = json.JSONDecoder().raw_decode(out[start:])
    except ValueError as exc:  # JSONDecodeError
        raise RuntimeError(f"opencli returned unparseable output: {out[:200]}") from exc
    return _parse_opencli_tweets(tweets, limit)


def fetch(board: dict) -> list[dict]:
    """Dispatch on the board's scan_strategy."""
    strategy = board["scan_strategy"]
    cfg = json.loads(board["scan_config"] or "{}")
    if strategy == "rss":
        return fetch_rss(board, cfg)
    if strategy == "api":
        return fetch_api(board, cfg)
    if strategy == "jobspy":
        return fetch_jobspy(board, cfg)
    if strategy == "html":
        return fetch_html(board, cfg)
    raise ValueError(f"no fetcher for strategy {strategy!r}")


# --- rss -------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_rss(board: dict, cfg: dict) -> list[dict]:
    """RSS 2.0 feed -> jobs. Namespace-tolerant (works for plain RSS and
    feeds with custom namespaces like Himalayas/RemoteOK)."""
    root = _parse_xml(_http_get(cfg["feed_url"]))
    jobs = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        fields: dict[str, str] = {}
        for child in item:
            fields.setdefault(_local(child.tag), (child.text or "").strip())
        url = fields.get("link") or fields.get("guid")
        title = fields.get("title")
        if not title or not url:
            continue  # not a job item (some feeds mix in announcements)
        company = fields.get("company") or fields.get("companyName")
        # twice: some feeds double-encode (&amp;amp;); idempotent otherwise
        title = html.unescape(html.unescape(title))
        if company:
            company = html.unescape(company)
        jobs.append({
            "title": title,
            "company": company,
            "url": url,
            "source_ref": fields.get("guid") or url,
            "description": strip_html(fields.get("description")),
            "location": fields.get("location") or fields.get("locationRestriction"),
            "workplace_type": "remote",  # remote-only feeds
            "posted_at": _iso(fields.get("pubDate") or fields.get("date")),
            "metadata": {"feed": cfg["feed_url"]},
        })
    return jobs
