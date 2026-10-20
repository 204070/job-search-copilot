"""Read a job out of an X bookmarked tweet.

X bookmarks are captured as whatever the tweet said: the whole text as the
title, company `Unknown`, no location, score 0. That buries real leads — a
bookmarked "Hiring!!! Remote Full-Stack Developer" or "Acme is expanding and
we're looking for talented developers" is a posting, not noise, and a small
local employer will never surface if its row says `Unknown`.

This pulls the three fields a lead needs out of the text:

  company   "Acme is expanding" / "Join Northwind Software" / "brightpath (yc-w23)"
  location  "(Spain)" / "(Remote)" / a named city
  title     "Senior Full Stack Developer", with the tweet's own wording kept
            as the description when no role phrase is present

It is a heuristic on informal prose, so it never invents: an unmatched row
keeps the tweet text and `Unknown`, and every decision is advisory. The
`job_like` flag says the text reads like a posting, which is what lets a board
separate "worth a look" from "just a link I saved".

Run `python3 -m scanner.bookmarks` for the worked cases.
"""
from __future__ import annotations

import re

# --- is this a posting at all? ---------------------------------------------

#: Unambiguous posting wording: a hiring act, not a topic.
_STRONG = re.compile(
    r"\b(?:hiring|open roles?|open positions?|job openings?|vacanc(?:y|ies)"
    r"|we'?re? (?:expanding|recruiting|growing)|join (?:our|the) team"
    r"|send (?:us )?(?:your )?cv|applications? (?:are )?open|internships?"
    r"|(?:sde|swe) (?:interns?|roles?|positions?))\b",
    re.I,
)

#: A role noun; needs an action word or a job URL to count (devs discuss dev).
_ROLE = re.compile(
    r"\b(full[- ]?stack (?:developer|engineer)s?"
    r"|back[- ]?end (?:developer|engineer)s?"
    r"|front[- ]?end (?:developer|engineer)s?"
    r"|software (?:developer|engineer)s?"
    r"|web (?:developer|engineer)s?|mobile (?:developer|engineer)s?"
    r"|devops|sde|swe|developers?|engineers?|programmers?"
    r"|(?:data )?scientists?|product managers?|designers?)\b",
    re.I,
)

_ACTION = re.compile(
    r"\b(looking for|seeking|apply|cv|resume|r[eé]sum[eé]|role|position"
    r"|opportunit\w*|we'?re? (?:building|hiring|growing)|dm me|reach out"
    r"|join us|join (?:our|the) team)\b",
    re.I,
)

_JOB_URL = re.compile(
    r"(?:greenhouse|lever\.co|workable|ashby|bamboohr|smartrecruiters|recruitee"
    r"|/jobs?/|/careers?/|/apply|/vacanc|jobs\.|careers\.)",
    re.I,
)

#: Words that look like a company to a naive pattern but are not.
_STOPWORDS = {
    "the", "our", "their", "this", "that", "these", "those", "we", "i", "you",
    "they", "it", "he", "she", "top", "great", "many", "more", "most", "best",
    "a", "an", "and", "or", "but", "if", "when", "while", "after", "before",
    "everyone", "someone", "anyone", "people", "team", "teams", "company",
    "companies", "startup", "startups", "clients", "client", "role", "roles",
    "job", "jobs", "position", "positions", "candidates", "engineers",
    "developers", "designers", "hiring", "remote", "sponsorship", "visa",
    "austria", "germany", "europe", "africa", "nigeria", "usa", "us", "uk",
    "today", "tomorrow", "now", "here", "there", "next", "last", "new",
}

_ROLE_NOUN = (
    r"(?:Developer|Engineer|Designer|Manager|Analyst|Scientist|Architect"
    r"|Interns?|Programmer|Consultant|Specialist|Lead)"
)

_TITLE = re.compile(
    rf"(?P<t>(?:[A-Za-z][\w/&+.-]*\s+){{0,4}}?{_ROLE_NOUN})\b"
)

_TITLE_FILLER = {
    "we're", "we", "i'm", "i", "hiring", "hiring:", "looking", "for", "a", "an",
    "the", "join", "our", "team", "is", "are", "now", "new", "role", "position",
    "and", "multiple", "several", "positions", "open", "seeking", "senior!",
    "remote", "hybrid", "on-site", "onsite", "fully", "anywhere", "worldwide",
}

#: (pattern, require_a_brand_looking_name). The brand check rejects the loose
#: patterns' favourite false positive - a lowercase common noun - while still
#: accepting camelCase brands like "iPhone" or "eBay". The YC badge is proof
#: on its own, so that pattern skips the check (e.g. an all-lowercase startup handle).
_COMPANY_PATTERNS = [
    # "Acme is expanding", "Acme is hiring", "Foo are recruiting"
    (re.compile(
        r"(?P<c>[A-Za-z][\w.&'’-]*(?:\s+[A-Z][\w.&'’-]*){0,3})\s+(?:is|are)\s+"
        r"(?:now\s+)?(?:hiring|expanding|recruiting|looking for|growing|building)"
    ), True),
    # "hiring at Acme", "hiring @Acme", "join us at Acme"
    (re.compile(r"\b(?:hiring|join(?:ing)?)(?:\s+us)?\s+(?:at|@)\s*"
                r"(?P<c>[A-Za-z][\w.&'’-]*)"), True),
    # "Join Northwind Software"
    (re.compile(r"\bJoin\s+(?P<c>[A-Za-z][\w.&'’-]*(?:\s+[A-Z][\w.&'’-]*){0,2})"),
     True),
    # "brightpath (yc-w23)"
    (re.compile(r"(?P<c>[A-Za-z][\w.&'’-]*)\s*\((?:yc|YC)[- ]?\w+\)"), False),
    # A bare "@handle" is too weak to call a company, so it is not used.
]

_LOCATION_PAREN = re.compile(
    r"\((?P<loc>Remote|Hybrid|On-?site|Worldwide|Anywhere"
    r"|[A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)?)\)"
)
_LOCATION_WORD = re.compile(
    r"\b(remote|hybrid|on-?site|worldwide|anywhere|fully remote)\b", re.I
)


def looks_like_job(text: str, url: str | None = None) -> bool:
    """True when the text reads like a posting rather than a saved link."""
    if _STRONG.search(text):
        return True
    if _ROLE.search(text) and (_ACTION.search(text) or _JOB_URL.search(url or "")):
        return True
    return False


def _brand_like(word: str) -> bool:
    """A capitalised or camelCase word: "Acme", "iPhone", "eBay"."""
    return word[:1].isupper() or any(ch.isupper() for ch in word[1:])


def _clean_company(candidate: str, require_brand: bool) -> str | None:
    """Trim filler words off a candidate and reject non-names."""
    words = [w for w in candidate.split() if w]
    while words and words[0].lower().strip(".,:;!?-") in _STOPWORDS:
        words.pop(0)
    while words and words[-1].lower().strip(".,:;!?-") in _STOPWORDS:
        words.pop()
    if not words:
        return None
    name = " ".join(words).strip(" .,:;!?-")
    if not name or name.lower() in _STOPWORDS:
        return None
    if require_brand and not _brand_like(words[0]):
        return None
    return name


def extract_company(text: str) -> str | None:
    """The company named in the text, or None. Never guesses."""
    for pattern, require_brand in _COMPANY_PATTERNS:
        for match in pattern.finditer(text):
            name = _clean_company(match.group("c"), require_brand)
            if name:
                return name
    return None


def extract_location(text: str) -> str | None:
    """A named place or work mode from the text, or None."""
    match = _LOCATION_PAREN.search(text)
    if match:
        return match.group("loc")
    match = _LOCATION_WORD.search(text)
    if match:
        return match.group(1).capitalize()
    return None


def workplace_type(location: str | None) -> str:
    """Map an extracted location onto jobs.workplace_type's enum."""
    low = (location or "").lower()
    if "hybrid" in low:
        return "hybrid"
    if "on-site" in low or "onsite" in low:
        return "onsite"
    if "remote" in low or "worldwide" in low or "anywhere" in low:
        return "remote"
    return "unknown"


def extract_title(text: str) -> str | None:
    """The role phrase, with filler words trimmed, or None."""
    for match in _TITLE.finditer(text):
        words = match.group("t").split()
        while words and words[0].lower() in _TITLE_FILLER:
            words.pop(0)
        if not words:
            continue
        candidate = " ".join(words)
        if len(candidate) <= 60:
            return candidate
    return None


def enrich(text: str, url: str | None = None) -> dict:
    """Derive {job_like, company, location, title} from a tweet's text."""
    text = " ".join((text or "").split())
    return {
        "job_like": looks_like_job(text, url),
        "company": extract_company(text),
        "location": extract_location(text),
        "title": extract_title(text),
    }


# --- self-test: the cases this module is specified by ----------------------
# Representative of the shapes real bookmarks take, not quotations of any.

_CASES: list[tuple[str, dict]] = [
    (
        "Acme Payments is expanding and we're looking for talented developers "
        "to help create the next generation of digital payments.",
        {"job_like": True, "company": "Acme Payments", "location": None},
    ),
    (
        "I'm hiring. (Spain) You know how to: - Build AI products with AI",
        {"job_like": True, "location": "Spain"},
    ),
    (
        "Hiring!!! Remote Full-Stack Developer We're looking for a Full-Stack "
        "Developer who can build complete products.",
        {"job_like": True, "location": "Remote", "title": "Full-Stack Developer"},
    ),
    (
        "We're Hiring: Senior Full Stack Developer (AI-Enabled Software "
        "Engineering) Join Northwind Software and help build products",
        {"job_like": True, "company": "Northwind Software",
         "title": "Senior Full Stack Developer"},
    ),
    (
        "18 vacancies to fill for different clients. Mostly remote roles but "
        "experience working with US timezones is required.",
        {"job_like": True},
    ),
    (
        "brightpath (yc-w23) is looking for sde interns to join the team.",
        {"job_like": True, "company": "brightpath"},
    ),
    (
        "Silence, like a cancer, grows.",
        {"job_like": False, "company": None, "location": None, "title": None},
    ),
    (
        "New paper: every law is technically public. But not really, until now!",
        {"job_like": False},
    ),
    (
        "Strata 1.0 is here. The best file manager on Linux, fully open source. "
        "45 days, 775 commits, 38 contributors, ~300K lines of Rust.",
        {"job_like": False},
    ),
]


def _self_test() -> int:
    failures = 0
    for text, expected in _CASES:
        got = enrich(text)
        bad = [k for k, v in expected.items() if got[k] != v]
        failures += bool(bad)
        flag = "ok  " if not bad else "FAIL"
        detail = "" if not bad else "  " + str({k: got[k] for k in bad})
        print(f"{flag} job_like={got['job_like']}  company={got['company']!r} "
              f"loc={got['location']!r} title={got['title']!r}{detail}")
        print(f"      {text[:88]!r}")
    print(f"\n{len(_CASES) - failures}/{len(_CASES)} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
