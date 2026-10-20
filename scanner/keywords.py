"""Keyword matcher for job leads.

Strategy: two title rules decide whether a posting is worth scoring at all,
then weighted coverage over the keyword entries.

    title_exclude  any match vetoes the posting (a "Support Engineer" whose ad
                   mentions Kubernetes scores 0, not 25).
    title_admit    the title must match at least one pattern.

Then `score = 100 x matched weight / target`, capped at 99 so a perfect keyword
hit stays distinguishable from a future classifier's 100. `target` is the
weight of the entries at or above `core_weight`, so matching the whole core
tier is a full score and the long tail extends the scale instead of compressing
it. Without a `core_weight` the target falls back to the total weight.

All rules live in `scanner/keywords.jsonc`, which is yours and gitignored,
copied from the committed `scanner/keywords.example.jsonc`. `python3 -m
scanner` picks up edits automatically, and `Matcher.reload()` re-reads the file
when it changes. With no local copy, the example is read instead.

The previous strategy used the title as a fixed OR-gate of nine phrasings, so
every role family outside those nine scored 0 regardless of content: 383 of
455 bookmarked postings, including plainly engineering-titled ones. The gate
is now a rule with an exclude half, and `admits()` exposes it so reports can
tell "not our kind of role" apart from "our kind of role with nothing we
recognise in the text".

Config entry: {"term", "weight", "enabled", optional "pattern", optional
"field"}. Plain terms compile to case-insensitive word-boundary regex
(`\bterm\b`, so 'rust' never hits 'robust' — same semantics as the old
DB-backed matcher). `pattern` is a hand-written regex override for cases terms
can't express (alternations, optional words); invalid patterns raise
ValueError at load with the entry's term named. A legacy `field: "title"`
entry still loads, as an extra admit pattern.

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
import sys
from pathlib import Path

DEFAULT_KEYWORDS_PATH = Path(__file__).resolve().parent / "keywords.jsonc"
KEYWORDS_PATH = Path(os.environ.get("MATCH_KEYWORDS_PATH", DEFAULT_KEYWORDS_PATH))
_COMMENT_LINE = re.compile(r"(?m)^\s*//.*$")


def _resolve_config(path: Path | str) -> Path:
    """The local config, or the committed template when it is absent.

    Your own `keywords.jsonc` is gitignored, so a fresh clone has only
    `keywords.example.jsonc` beside it. Reading the template keeps a clone
    working from the first command; the note says how to make the copy.
    """
    path = Path(path)
    if path.exists():
        return path
    example = path.with_name(f"{path.stem}.example{path.suffix}")
    if example.exists():
        print(f"note: {path} not found, reading {example.name}; copy it to "
              f"{path.name} to make it yours", file=sys.stderr)
        return example
    raise FileNotFoundError(f"{path} not found, and no {example.name} beside it")


def _term_pattern(entry: dict) -> str:
    return entry.get("pattern") or r"\b" + re.escape(entry["term"]) + r"\b"


def load_config(path: Path | str = KEYWORDS_PATH) -> dict:
    """Parse the JSONC config; validate + compile every pattern eagerly."""
    path = _resolve_config(path)
    data = json.loads(_COMMENT_LINE.sub(
        "", Path(path).read_text(encoding="utf-8")))
    for e in data.get("keywords", []):
        try:
            re.compile(_term_pattern(e), re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"bad pattern for keyword {e['term']!r}: {exc}")
    for key in ("title_admit", "title_exclude"):
        for pattern in data.get(key) or []:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"bad pattern in {key}: {pattern!r}: {exc}")
    return data


def load_entries(path: Path | str = KEYWORDS_PATH) -> list[dict]:
    """The keyword entries alone (kept for callers that predate the rules)."""
    return load_config(path).get("keywords", [])


def _compile_many(patterns) -> list:
    return [re.compile(p, re.IGNORECASE) for p in patterns or []]


def _target_weight(entries, core_weight) -> int:
    """Scoring denominator: the core tier's weight, or all of it.

    With `core_weight` set, a posting naming the whole core tier scores 100 and
    the longer tail can only pull other postings up toward it. Without it the
    target is the total weight, which is the older behaviour: every incidental
    term added to the list shaves a little off everybody's score.
    """
    if core_weight:
        core = sum(w for _, _, w in entries if w >= core_weight)
        if core:
            return core
    return sum(w for _, _, w in entries) or 1


class Matcher:
    """Scores a job posting against the keyword strategy.

    See the module docstring for the rules. `admits(title)` answers the title
    question on its own, which is what lets a report separate postings that are
    not this kind of role from postings whose text simply names nothing on the
    list.
    """

    def __init__(self, path: Path | str = KEYWORDS_PATH):
        self.path = _resolve_config(path)
        self._mtime = 0.0
        self._admit: list = []
        self._exclude: list = []
        self._any: list = []
        self._target = 1
        self.reload(force=True)

    def reload(self, force: bool = False) -> bool:
        """Re-read + recompile when the config changed. Returns True if so."""
        mtime = self.path.stat().st_mtime
        if not force and mtime <= self._mtime:
            return False
        self._mtime = mtime
        cfg = load_config(self.path)
        any_: list = []
        admit = _compile_many(cfg.get("title_admit"))
        for e in cfg.get("keywords", []):
            if not e.get("enabled", 1):
                continue
            rx = re.compile(_term_pattern(e), re.IGNORECASE)
            if e.get("field", "any") == "title":
                admit.append(rx)  # legacy shape: a title entry is a gate
            else:
                any_.append((rx, e["term"], e.get("weight", 1)))
        self._admit = admit
        self._exclude = _compile_many(cfg.get("title_exclude"))
        self._any = any_
        self._target = _target_weight(any_, cfg.get("core_weight"))
        return True

    @property
    def target_weight(self):
        """The denominator: weight of a full-score match under this config."""
        self.reload()
        return self._target

    def admits(self, title: str | None) -> bool:
        """Would this title be scored at all? Excludes win over admits."""
        self.reload()
        t = title or ""
        if any(p.search(t) for p in self._exclude):
            return False
        return not self._admit or any(p.search(t) for p in self._admit)

    def score(self, title: str | None, text: str | None) -> tuple[int, list[str]]:
        """Return (score 0-100, matched terms)."""
        self.reload()
        t = title or ""
        if not self.admits(t):
            return 0, []
        blob = f"{t} {text or ''}"
        matched = [term for p, term, _ in self._any if p.search(blob)]
        got = sum(w for _, term, w in self._any if term in matched)
        return min(99, round(100 * got / self._target)), matched


def min_score(default: int = 15) -> int:
    """Lead threshold: matches at or above this score are surfaced."""
    return int(os.environ.get("MATCH_MIN_SCORE", default))


_EXAMPLE_CONFIG = DEFAULT_KEYWORDS_PATH.with_name("keywords.example.jsonc")


def _selftest() -> int:
    """Check the matcher against the committed example config.

    Each case is (title, text, expected admits(), expected score check). The
    fixture is `keywords.example.jsonc`, not your own copy: the scoring rules
    are yours to tune, and a term you rename must not turn this red. A bad
    pattern in your own file still raises when it loads.
    """
    m = Matcher(_EXAMPLE_CONFIG if _EXAMPLE_CONFIG.exists()
                else DEFAULT_KEYWORDS_PATH)
    core_text = "React, TypeScript, GraphQL and Postgres. Kubernetes, AWS."
    cases: list[tuple[str, str, bool, str, object]] = [
        # title, text, admits(), description, score check
        ("Senior Frontend Engineer", core_text, True,
         "frontend role with the core languages",
         lambda s, mt: s > 0 and "react" in mt and "typescript" in mt),
        ("Sales Engineer", "Kubernetes, AWS, Postgres", False,
         "sales engineer naming our whole stack", lambda s, mt: s == 0),
        ("Support Engineer II", "TypeScript, Postgres, Docker", False,
         "support engineer naming our stack", lambda s, mt: s == 0),
        ("Data Analyst", "Python, Postgres", False,
         "data analyst", lambda s, mt: s == 0),
        ("Marketing Manager, Devtools", "TypeScript", False,
         "marketing manager", lambda s, mt: s == 0),
        ("Engineering Manager, Platform", "Kubernetes, AWS", True,
         "engineering manager is a target role now, not a veto",
         lambda s, mt: s > 0 and "kubernetes" in mt),
        ("Manager, Engineering - Identity", "TypeScript, Postgres", True,
         "manager, engineering: the other word order admits too",
         lambda s, mt: s > 0 and "typescript" in mt),
        ("Product Engineer", "TypeScript, Postgres", True,
         "product engineer", lambda s, mt: s > 0),
        ("Forward Deployed Engineer", "Python, Docker", True,
         "forward deployed engineer", lambda s, mt: s > 0),
        ("Solutions Architect", "AWS, Terraform", True,
         "solutions architect admits; solutions engineer is separately out",
         lambda s, mt: s > 0 and "terraform" in mt),
        ("LLM Engineer", "RAG pipelines, embeddings, Python", True,
         "the AI vocabulary reaches AI/LLM roles",
         lambda s, mt: s > 0 and {"ai", "llm", "rag"} & set(mt)),
        ("Account Manager", "TypeScript, Postgres", False,
         "account manager is not engineering management",
         lambda s, mt: s == 0),
        ("Scrum Master, Engineering", "Kubernetes", False,
         "scrum master, even inside an engineering org",
         lambda s, mt: s == 0),
        ("Director of Engineering", "Kubernetes, AWS", False,
         "director: above first-line management, deliberately still out",
         lambda s, mt: s == 0),
        ("Member of Technical Staff, Engineering", "TypeScript, Postgres", True,
         "an IC title that says engineering and not engineer still admits",
         lambda s, mt: s > 0),
        ("Product Manager, API", "Postgres", False,
         "product manager", lambda s, mt: s == 0),
        ("Senior Staff Software Engineer, Query Execution",
         "Java, Scala, distributed systems", True,
         "staff engineer in an unfamiliar stack still admits and scores",
         lambda s, mt: s > 0 and "java" in mt),
        ("Senior Full Stack Developer", "TypeScript, React, Node, Postgres",
         True, "the core tier outscores a single incidental term",
         lambda s, mt: s >= 40),
        ("Backend Developer", "We write robust, resilient code.", True,
         "word boundaries hold: 'robust' is not 'rust'",
         lambda s, mt: "rust" not in mt),
        ("Platform Engineer", "", True,
         "an admitted title with empty text admits but scores 0",
         lambda s, mt: s == 0),
    ]
    failures = 0
    for title, text, want_admit, desc, check in cases:
        score, matched = m.score(title, text)
        got_admit = m.admits(title)
        ok = got_admit == want_admit and check(score, matched)
        if not ok:
            failures += 1
            print(f"FAIL  {desc}\n      title={title!r} text={text!r}\n"
                  f"      admits={got_admit} (want {want_admit}) "
                  f"score={score} matched={matched}")
    total = len(cases)
    # Cap check: a text naming every enabled term must return 99, not 100.
    samples = {"dotnet group": "C#", "gcp": "Google Cloud",
               "websocket group": "WebSockets"}
    everything = " ".join(samples.get(e["term"], e["term"])
                          for e in load_entries(m.path))
    peak, _ = m.score("Software Engineer", everything)
    if peak != 99:
        failures += 1
        print(f"FAIL  perfect keyword hit should cap at 99, got {peak}")
    total += 1
    # The target must stay a sane percentage base, not drift with the tail.
    if not 0 < m.target_weight <= sum(w for _, _, w in m._any):
        failures += 1
        print(f"FAIL  target_weight {m.target_weight} is not a weight subset")
    total += 1
    print(f"{total - failures}/{total} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
