"""Probe boards for the cheapest automation path. Run before writing a parser.

For each enabled `html` board, checks (all read-only, one GET per URL):
  1. fetchability: status code + anti-bot markers (Cloudflare, consent walls)
  2. RSS/Atom: <link rel=alternate> hints, then conventional feed paths
     (/feed, /rss.xml, /jobs.rss, /sitemap.xml)
  3. structured data: application/ld+json (JobPosting) blocks
  4. frontend markers (__NEXT_DATA__ etc.) implying a JSON endpoint exists

Verdict logic (cheapest first):
  rss     - a feed exists: flip scan_strategy to 'rss', config only
  api     - JSON endpoint hint: add an api branch, usually small
  ld+json - structured data on the page: generic parser will work
  html    - plain HTML: generic selector parser + per-board config
  blocked - unreachable/JS-only/bot-walled: revisit later or go manual

Usage:
    python3 -m scanner.tools.probe_boards                # all html boards
    python3 -m scanner.tools.probe_boards --strategy html
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

sys.path.insert(0, __file__.rsplit("/", 3)[0])  # repo root

from db import connect  # noqa: E402
from scanner.fetchers import USER_AGENT  # noqa: E402

TIMEOUT = 12
FEED_PATHS = ("/feed", "/rss.xml", "/jobs.rss", "/feed.xml", "/sitemap.xml")


class _HeadParser(HTMLParser):
    """Collects <link rel=alternate> hints and ld+json script bodies."""

    def __init__(self) -> None:
        super().__init__()
        self.feed_links: list[tuple[str, str]] = []  # (type, href)
        self.in_ldjson = False
        self.ldjson: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or ""):
            if "rss" in (a.get("type") or "") or "atom" in (a.get("type") or ""):
                self.feed_links.append((a.get("type", ""), a.get("href", "")))
        if tag == "script" and a.get("type") == "application/ld+json":
            self.in_ldjson = True
            self.ldjson.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_ldjson = False

    def handle_data(self, data):
        if self.in_ldjson and self.ldjson:
            self.ldjson[-1] += data


def _get(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
            return resp.status, resp.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def _jobposting_count(ldjson_blocks: list[str]) -> int:
    n = 0
    for block in ldjson_blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                n += 1
    return n


def probe(board: dict) -> str:
    url = board["url"]
    name = board["name"]
    status, body = _get(url)

    if status is None or status in (403, 429, 503) or "just a moment" in body.lower():
        reason = "timeout/unreachable" if status is None else f"HTTP {status}"
        return f"{name:26} BLOCKED ({reason}) — JS-only or bot-walled; manual or playwright later"

    parser = _HeadParser()
    try:
        parser.feed(body)
    except Exception:
        pass

    findings = []
    if parser.feed_links:
        findings.append(f"feed hint: {parser.feed_links[0][1]}")
    jobpostings = _jobposting_count(parser.ldjson)
    if jobpostings:
        findings.append(f"{jobpostings} JobPosting ld+json block(s)")
    if "__NEXT_DATA__" in body:
        findings.append("Next.js (JSON endpoint likely)")
    if re.search(r"window\.__NUXT__|data-nuxt", body):
        findings.append("Nuxt (JSON endpoint likely)")
    if "gatsby" in body.lower():
        findings.append("Gatsby (page-data JSON likely)")

    found_feed = None
    if not parser.feed_links:
        for path in FEED_PATHS:
            s, _b = _get(url.rstrip("/") + path)
            if s == 200:
                found_feed = path
                break
    if found_feed:
        findings.append(f"feed responds 200 at {found_feed}")

    if found_feed or parser.feed_links:
        verdict = "RSS"
    elif jobpostings:
        verdict = "LD+JSON"
    elif findings:
        verdict = "API?"
    else:
        verdict = "HTML"
    return f"{name:26} {verdict:9} HTTP {status} | " + ("; ".join(findings) or "plain HTML")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--strategy", default="html")
    args = p.parse_args()
    conn = connect()
    conn.row_factory = None
    boards = conn.execute(
        "SELECT name, url FROM boards WHERE enabled = 1 AND scan_strategy = ? ORDER BY name",
        (args.strategy,),
    ).fetchall()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for line in pool.map(lambda b: probe({"name": b[0], "url": b[1]}), boards):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
