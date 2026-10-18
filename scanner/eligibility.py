"""Where a posting says it will hire, and whether that opens or closes it.

Classifies the *stated restriction*, never the company's home country. A US
company that says "Remote" with no restriction stays `unknown` (and visible),
because plenty of them hire worldwide; a US company that says "Remote, USA"
is `us_only`. Getting this backwards is the difference between a useful board
and one that hides your best leads, so every tag carries the phrase that
produced it.

Scopes:

  worldwide     the posting says it hires anywhere
  us_only       it demands US residence or US work authorisation
  region_gated  it names specific countries or regions (a list to check)
  unknown       it states no restriction - the common case, and NOT a bar

Only `us_only` is a real bar for a candidate who needs no US sponsorship.
Nothing is ever excluded on this basis; it is a triage tag.

Three subtleties this deliberately gets right:

- "USA timezones" / "US hours" / "US clients" are NOT bars. They describe
  overlap, and overlapping ET afternoons is an explicitly accepted condition.
- A list that includes the US among other regions ("Europe, USA, Canada,
  APAC") is `region_gated`, not `us_only`.
- Not every `region_gated` list excludes. EMEA, MEA and Africa include West
  Africa; Europe alone, the Americas, APAC and the Gulf do not. `scope_rank`
  puts the covering lists above `unknown`, because "open to a region you are
  in" is better information than "says nothing" - the tag alone cannot tell
  the two apart, which is what `covers_home` is for.

Run `python3 -m scanner.eligibility` for the worked cases this is specified by.
"""
from __future__ import annotations

import re

WORLDWIDE = "worldwide"
US_ONLY = "us_only"
REGION_GATED = "region_gated"
UNKNOWN = "unknown"

SCOPES = (WORLDWIDE, US_ONLY, REGION_GATED, UNKNOWN)

# --- signals ---------------------------------------------------------------

#: "Hire anywhere" wording. Checked first, and it beats a US mention — but a
#: region word in the same string ("Anywhere in Europe") cancels it.
_WORLDWIDE = re.compile(
    r"\b(world[- ]?wide|anywhere|any location|"
    r"no location restriction|all locations|remote \(global\)|globally remote|"
    r"open to candidates worldwide)\b",
    re.I,
)

#: An explicit demand for US presence or US work authorisation. Each pattern
#: needs an obligation ("must", "only", "required to be"), so a bare mention
#: of the US never trips it.
_US_ONLY = re.compile(
    r"(?:"
    r"\b(?:us|u\.s\.|usa|united states)[- ]?(?:only|based|residents?|citizens?)\b"
    r"|\bmust be (?:located|based|residing|authorized|eligible|able) in the "
    r"(?:us|u\.s\.|usa|united states)\b"
    r"|\b(?:authorized|eligible|permitted) to work in the (?:us|u\.s\.|usa|"
    r"united states)\b"
    r"|\bus work (?:authorization|authorisation|permit)\b"
    r"|\bonly (?:us|u\.s\.|usa|united states)[- ]based\b"
    r"|\bremote[, ]+(?:in |within )?(?:the )?(?:us|u\.s\.|usa|united states)\b"
    r"|,\s*(?:usa|u\.s\.a?\.?|united states)\s*$"
    r"|^\s*(?:usa|u\.s\.a?\.?|united states)\s*$"
    r")",
    re.I | re.M,
)

#: US states by full name, plus "United States". Deliberately full names only:
#: two-letter codes collide with country codes ("DE" Germany, "IN" India,
#: "CA" Canada), and "City, ST, USA" is already caught by the pattern above.
#: Georgia is omitted - it is a country as often as a state.
_US_PLACE = re.compile(
    r"\b(alabama|alaska|arizona|arkansas|california|colorado|connecticut"
    r"|delaware|florida|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky"
    r"|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi"
    r"|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico"
    r"|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania"
    r"|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont"
    r"|virginia|washington|west virginia|wisconsin|wyoming|united states)\b",
    re.I,
)

#: Regions/countries other than the US: naming any of these alongside a US
#: mention makes it a list to check rather than a US-only bar. The short
#: abbreviations (AMER, EMEA, APAC, MEA) are here because job boards use them
#: as location strings in their own right, and a missing one silently reads as
#: "no restriction stated" rather than as a list.
_REGION = re.compile(
    r"\b(europe|emea|apac|amer|americas|latam|latin america|mea|asia|africa|"
    r"sub-saharan africa|west africa|oceania|north america|"
    r"canada|united kingdom|uk|ireland|germany|france|spain|portugal|netherlands|"
    r"poland|romania|ukraine|switzerland|sweden|norway|denmark|finland|estonia|"
    r"australia|new zealand|india|pakistan|bangladesh|philippines|indonesia|"
    r"malaysia|vietnam|thailand|singapore|japan|south korea|israel|brazil|"
    r"mexico|argentina|colombia|chile|peru|nigeria|kenya|ghana|egypt|morocco|"
    r"south africa|middle east|gcc|dubai|uae)\b",
    re.I,
)

#: The regions that actually include the candidate's own region (West Africa).
#: A gate naming one of these is open to them rather than closed; Europe alone,
#: the Americas, APAC and the Gulf are not on the list even though all of them
#: are `region_gated`. This is the vocabulary `scope_rank` triages by.
_HOME_REGION = re.compile(
    r"\b(africa|sub[- ]saharan|west africa|emea|mea|nigeria|ecowas)\b",
    re.I,
)

#: Conservative description-only signals: strong obligation wording only, so a
#: passing mention of the US in a long job description never flips a scope.
_DESC_WORLDWIDE = re.compile(
    r"\b(?:we (?:hire|work with (?:people|developers|engineers)) (?:from )?"
    r"(?:anywhere|worldwide|globally)|hiring (?:anywhere|worldwide|globally)|"
    r"remote (?:first )?(?:and )?worldwide|distributed team (?:worldwide|globally))\b",
    re.I,
)
_DESC_US_ONLY = re.compile(
    r"\b(?:must be (?:a )?(?:authorized|eligible|able) to work in the "
    r"(?:us|u\.s\.|usa|united states)|us work authorization (?:is )?required|"
    r"(?:this|the) (?:role|position) is (?:open only to|limited to) "
    r"(?:us|u\.s\.|usa|united states))\b",
    re.I,
)


def classify(location: str | None, description: str | None = None) -> tuple[str, str | None]:
    """Return (scope, evidence) for a posting.

    `location` carries the authoritative, short restriction text; `description`
    is scanned only for strong obligation wording. Evidence is the matched
    phrase (whitespace-collapsed) so a wrong tag is visible and cheap to fix.
    """
    loc = " ".join((location or "").split())
    desc = " ".join((description or "").split())

    if loc:
        match = _WORLDWIDE.search(loc)
        if match and not _REGION.search(loc):
            return WORLDWIDE, loc
    if desc:
        match = _DESC_WORLDWIDE.search(desc)
        if match:
            return WORLDWIDE, match.group(0)

    match = _US_ONLY.search(loc) or _DESC_US_ONLY.search(desc)
    if match:
        phrase = match.group(0)
        return US_ONLY, loc if phrase.lower() in loc.lower() else phrase

    # A bare state name ("Kansas") is a US-only location; a list that also names
    # another region is a list to check, not a bar.
    if loc and _US_PLACE.search(loc) and not _REGION.search(loc):
        return US_ONLY, loc

    if loc and _REGION.search(loc):
        return REGION_GATED, loc

    return UNKNOWN, loc or None


# --- coverage and triage order ---------------------------------------------


def covers_home(scope: str, evidence: str | None = None) -> bool:
    """Whether this tag actually includes the candidate's own region.

    `worldwide` always does. `unknown` says nothing, so it is not coverage.
    A `region_gated` tag covers only when the named region includes West
    Africa: EMEA, MEA, Africa and Nigeria do; Europe alone, the Americas, APAC
    and the Gulf do not.
    """
    if scope == WORLDWIDE:
        return True
    if scope == REGION_GATED:
        return bool(_HOME_REGION.search(evidence or ""))
    return False


def scope_rank(scope: str | None, evidence: str | None = None) -> int:
    """Triage order for where a posting hires. Lower is seen first.

    Coverage outranks ignorance, which outranks a gate that excludes:

        0  worldwide
        1  a named region that includes West Africa (EMEA, MEA, Africa)
        2  unknown - no restriction stated, and not a bar
        3  a named list that does not include West Africa
        4  us_only, the only real bar

    The tag alone cannot separate 1 from 3 (both are `region_gated`), which is
    why this takes the evidence phrase too.
    """
    if scope == WORLDWIDE:
        return 0
    if covers_home(scope, evidence):
        return 1
    if scope == UNKNOWN:
        return 2
    if scope == REGION_GATED:
        return 3
    return 4


# --- self-test: the cases this module is specified by ----------------------

_CASES: list[tuple[str | None, str | None, str]] = [
    ("Remote, USA", None, US_ONLY),
    ("Chicago, IL, USA", None, US_ONLY),
    ("USA", None, US_ONLY),
    ("Remote", None, UNKNOWN),
    ("", None, UNKNOWN),
    (None, None, UNKNOWN),
    ("Worldwide", None, WORLDWIDE),
    ("Anywhere", None, WORLDWIDE),
    ("Anywhere in Europe", None, REGION_GATED),
    ("Europe, USA, Canada, APAC", None, REGION_GATED),
    ("Northern America, LATAM, Europe, APAC", None, REGION_GATED),
    ("Kansas", None, US_ONLY),          # bare state name
    ("Texas", None, US_ONLY),
    ("Georgia", None, UNKNOWN),         # country as often as a state: under-claims
    ("New York, NY", None, US_ONLY),
    ("USA, Canada, USA timezones", None, REGION_GATED),
    ("Texas, Europe", None, REGION_GATED),  # state name alongside another region
    (None, "You must be authorized to work in the US.", US_ONLY),
    (None, "We hire from anywhere in the world.", WORLDWIDE),
    # the correction that matters: overlap wording is not a bar
    ("US timezones", None, UNKNOWN),
    ("Remote | US hours", None, UNKNOWN),
    ("Remote (US clients)", None, UNKNOWN),
    # abbreviations a board uses as the whole location string: a missing token
    # reads as "no restriction stated", which is the wrong kind of wrong
    ("Remote, AMER", None, REGION_GATED),
    ("Remote, APAC", None, REGION_GATED),
    ("EMEA", None, REGION_GATED),
    ("Remote, EMEA", None, REGION_GATED),
    ("Sub-Saharan Africa", None, REGION_GATED),
]

#: (scope, evidence, rank) - the order the digest triages leads by.
_RANK_CASES: list[tuple[str, str | None, int]] = [
    (WORLDWIDE, "Worldwide", 0),
    (REGION_GATED, "EMEA", 1),
    (REGION_GATED, "Remote, EMEA", 1),
    (REGION_GATED, "Africa", 1),
    (REGION_GATED, "Sub-Saharan Africa", 1),
    (REGION_GATED, "Lagos, Nigeria", 1),
    (UNKNOWN, None, 2),
    (REGION_GATED, "Europe, USA, Canada, APAC", 3),
    (REGION_GATED, "Remote, AMER", 3),
    (REGION_GATED, "GCC", 3),
    (US_ONLY, "Remote, USA", 4),
    (None, None, 4),
]

#: (scope, evidence, covers) - what `covers_home` is for.
_COVER_CASES: list[tuple[str, str | None, bool]] = [
    (WORLDWIDE, "Anywhere", True),
    (UNKNOWN, None, False),
    (US_ONLY, "USA", False),
    (REGION_GATED, "EMEA", True),
    (REGION_GATED, "MEA", True),
    (REGION_GATED, "Africa", True),
    (REGION_GATED, "West Africa", True),
    (REGION_GATED, "Europe", False),
    (REGION_GATED, "APAC", False),
    (REGION_GATED, "Middle East", False),
    (REGION_GATED, "North America, LATAM", False),
    (REGION_GATED, None, False),
]


def _self_test() -> int:
    failures = 0
    for location, description, expected in _CASES:
        got, evidence = classify(location, description)
        ok = got == expected
        failures += not ok
        flag = "ok  " if ok else "FAIL"
        shown = f"loc={location!r}" + (f" desc={description!r}" if description else "")
        print(f"{flag} {got:<12} (want {expected:<12}) {shown}   evidence={evidence!r}")
    for scope, evidence, expected in _RANK_CASES:
        got = scope_rank(scope, evidence)
        ok = got == expected
        failures += not ok
        flag = "ok  " if ok else "FAIL"
        print(f"{flag} rank {got} want {expected} {scope!r} {evidence!r}")
    for scope, evidence, expected in _COVER_CASES:
        got = covers_home(scope, evidence)
        ok = got == expected
        failures += not ok
        flag = "ok  " if ok else "FAIL"
        print(f"{flag} covers {got} want {expected} {scope!r} {evidence!r}")
    total = len(_CASES) + len(_RANK_CASES) + len(_COVER_CASES)
    print(f"\n{total - failures}/{total} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
