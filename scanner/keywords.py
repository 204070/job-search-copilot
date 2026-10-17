"""Keyword matcher for job leads.

Current strategy: title OR-gate + weighted coverage over the enabled entries
in `scanner/keywords.jsonc` (committed example — replace terms with your own;
`python3 -m scanner` picks up edits automatically, `Matcher.reload()`
re-reads the file when it changes).

Config entry: {"term", "field" ('title'|'any'), "weight", "enabled",
optional "pattern"}. Plain terms compile to case-insensitive word-boundary
regex (`\\bterm\\b`, so 'rust' never hits 'robust' — same semantics as the old
DB-backed matcher). `pattern` is a hand-written regex override for cases
terms can't express (alternations, optional words); invalid patterns raise
ValueError at load with the entry's term named.

This module is the seam for the planned upgrade: callers only use
`Matcher().score(title, text)`, so a classifier model can replace the
internals later without touching the scanner flow. A future
`scanner/classifier.py` should expose the same `score()` contract (0-100 +
human-readable matched terms) and be selected by the `MATCH_ENGINE` env var.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_KEYWORDS_PATH = Path(__file__).resolve().parent / "keywords.jsonc"
KEYWORDS_PATH = Path(os.environ.get("MATCH_KEYWORDS_PATH", DEFAULT_KEYWORDS_PATH))
_COMMENT_LINE = re.compile(r"(?m)^\s*//.*$")


def load_entries(path: Path | str = KEYWORDS_PATH) -> list[dict]:
    """Parse the JSONC config; validate + compile patterns eagerly."""
    entries = json.loads(_COMMENT_LINE.sub(
        "", Path(path).read_text(encoding="utf-8")))["keywords"]
    for e in entries:
        try:
            re.compile(e.get("pattern") or r"\b" + re.escape(e["term"]) + r"\b",
                       re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"bad pattern for keyword {e['term']!r}: {exc}")
    return entries


class Matcher:
    """Scores a job posting against the keyword strategy.

    score = 0 unless the title contains at least one `title` term, otherwise
    100 * matched `any` weight / total `any` weight (capped at 99, so a
    perfect keyword hit is distinguishable from a future classifier's 100).
    """

    def __init__(self, path: Path | str = KEYWORDS_PATH):
        self.path = Path(path)
        self._mtime = 0.0
        self._title: list = []
        self._any: list = []
        self.reload(force=True)

    def reload(self, force: bool = False) -> bool:
        """Re-read + recompile when the config changed. Returns True if so."""
        mtime = self.path.stat().st_mtime
        if not force and mtime <= self._mtime:
            return False
        self._mtime = mtime
        title, any_ = [], []
        for e in load_entries(self.path):
            if not e.get("enabled", 1):
                continue
            rx = re.compile(e.get("pattern")
                            or r"\b" + re.escape(e["term"]) + r"\b",
                            re.IGNORECASE)
            bucket = title if e.get("field", "any") == "title" else any_
            bucket.append((rx, e["term"], e.get("weight", 1)))
        self._title, self._any = title, any_
        return True

    def score(self, title: str | None, text: str | None) -> tuple[int, list[str]]:
        """Return (score 0-100, matched terms)."""
        self.reload()
        t = title or ""
        blob = f"{t} {text or ''}"
        if self._title and not any(p.search(t) for p, _, _ in self._title):
            return 0, []
        matched = [term for p, term, _ in self._any if p.search(blob)]
        total = sum(w for _, _, w in self._any) or 1
        got = sum(w for _, term, w in self._any if term in matched)
        return min(99, round(100 * got / total)), matched


def min_score(default: int = 15) -> int:
    """Lead threshold: matches at or above this score are surfaced."""
    return int(os.environ.get("MATCH_MIN_SCORE", default))
