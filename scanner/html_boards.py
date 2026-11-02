"""Parsers for job boards whose list page is plain server-rendered HTML.

These boards publish no feed and no JSON endpoint, but their listing pages are
rendered server-side, so a browser is not needed either: one `_http_get` and a
few anchored patterns give the card. Each board gets its own function because
the cards differ (one carries Remote/Worldwide badges, the other a relative
age); the functions are pure, so they are exercised by the self-test below
against real card markup instead of by hitting the live sites.

Every parser returns rows in the shape `store.upsert_job` accepts. Rules that
apply to all of them:

- Nothing is filtered out. A card that names a country is stored too; where it
  hires is the classifier's job, not the parser's.
- The card's *place* span is the employer's location; its *eligibility*
  wording (a "Worldwide" badge) is what the classifier must read, so that is
  what becomes `location`. The raw place is kept in metadata.
- The card alone is stored by default: a description lives on the detail page,
  which costs one request per posting, so `parse_*_detail` is deliberately
  separate and the fetcher only calls it when the board asks (`details`).
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta

# --- shared helpers ---------------------------------------------------------


def _text(fragment: str | None) -> str:
    """HTML fragment -> collapsed text with entities decoded."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


_REL_AGE = re.compile(
    r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?|mo|[wdhms])\b", re.I
)
_REL_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365,
             "mo": 30, "d": 1, "w": 7, "h": 0, "m": 30, "s": 0}


def _relative_date(text: str | None, today: date | None = None) -> str | None:
    """'20 hours ago' / '1W' -> ISO date, or None when the card says nothing.

    Boards show age, not a date, so the row gets an approximation. It is only
    used for ordering, and the stored `last_seen_at` remains the real evidence
    of when this board first showed the posting.
    """
    match = _REL_AGE.search(text or "")
    if not match:
        return None
    unit = match.group(2).lower()
    days = _REL_DAYS.get(unit.rstrip("s") or unit, 0) * int(match.group(1))
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def _chunks(body: str, item_pattern: re.Pattern) -> list[str]:
    """Split a listing page into per-card slices at each item match."""
    spans = [m.start() for m in item_pattern.finditer(body)]
    return [body[start:end] for start, end in zip(spans, spans[1:] + [len(body)])]


_ABSOLUTE_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def _absolute_date(text: str | None) -> str | None:
    """'October 18, 2026' (a detail page's Posted field) -> ISO date."""
    match = _ABSOLUTE_DATE.search(text or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _inner_div(body: str, start: int) -> str:
    """Inner HTML of the `<div>` that starts at `start`.

    A regex cannot match nesting and the description is nested, so this counts
    `<div`/`</div>` from the opening tag to the one that closes it.
    """
    inner_start = body.find(">", start) + 1  # past the opening tag's attributes
    depth = 0
    for match in re.finditer(r"</?div\b", body[start:]):
        depth += 1 if match.group(0) == "<div" else -1
        if depth == 0:
            return body[inner_start: start + match.start()]
    return body[inner_start:]


# --- jsgurujobs.com ---------------------------------------------------------

_JG_ITEM = re.compile(r'<a href="(?P<url>https://jsgurujobs\.com/jobs/\d+)"[^>]*>(?P<title>.*?)</a>', re.S)
_JG_COMPANY = re.compile(r'<p class="mt-1[^"]*">(?P<company>.*?)</p>', re.S)
_JG_META = re.compile(r'<div class="mt-2 flex flex-wrap gap-x-4[^"]*">(?P<body>.*?)</div>', re.S)
_JG_BADGES = re.compile(r'<div class="mt-2 flex flex-wrap items-center gap-1\.5">(?P<body>.*?)</div>', re.S)
_JG_AGE = re.compile(r'<span class="text-xs text-gray-400">(?P<when>[^<]*)</span>')
_SPAN = re.compile(r"<span[^>]*>(?P<text>.*?)</span>", re.S)


def parse_jsgurujobs(body: str, today: date | None = None) -> list[dict]:
    """Cards of https://jsgurujobs.com/jobs.

    A card reads: title link, employer, then spans for place / job type /
    salary, then Remote and (sometimes) Worldwide badges, then an age. The
    detail page confirms the split this relies on: it lists Location "Armenia"
    for a posting whose Work Format says "Remote / Worldwide".
    """
    jobs: list[dict] = []
    for chunk in _chunks(body, _JG_ITEM):
        item = _JG_ITEM.search(chunk)
        if not item:
            continue
        url = item.group("url")
        company = _JG_COMPANY.search(chunk)
        meta = _JG_META.search(chunk)
        badge_block = _JG_BADGES.search(chunk)
        age = _JG_AGE.search(chunk)
        spans = [_text(m.group("text")) for m in _SPAN.finditer(meta.group("body"))] if meta else []
        badges = [re.sub(r"^[^\w]+", "", _text(m.group("text")))
                  for m in _SPAN.finditer(badge_block.group("body"))] if badge_block else []
        worldwide = any(b.lower() == "worldwide" for b in badges)
        remote = any("remote" in b.lower() for b in badges)
        jobs.append({
            "title": _text(item.group("title")),
            "company": _text(company.group("company")) if company else None,
            # The badge is the eligibility statement; the place span is where
            # the employer sits. A card reading place "Armenia" + badge
            # "Worldwide" is open to everyone, so the badge wins.
            "location": "Worldwide" if worldwide else (spans[0] if spans and spans[0] else None),
            "url": url,
            "source_ref": url.rstrip("/").rsplit("/", 1)[-1],
            "workplace_type": "remote" if remote else "unknown",
            "posted_at": _relative_date(age.group("when") if age else None, today),
            "metadata": {
                "via": "jsgurujobs",
                "employer_location": spans[0] if spans else None,
                "job_type": spans[1] if len(spans) > 1 else None,
                "salary_raw": spans[2] if len(spans) > 2 else None,
                "badges": badges,
            },
        })
    return jobs


# --- javascript.jobs --------------------------------------------------------

_JS_ITEM = re.compile(r'<a href="(?P<url>https://javascript\.jobs/job/[^"]+)"[^>]*class="[^"]*jobcardStyle1', re.S)
_JS_TITLE = re.compile(r'<div class="[^"]*tw-text-lg tw-font-medium[^"]*">\s*(?P<title>.*?)\s*</div>', re.S)
_JS_AGE = re.compile(r'<div class="[^"]*tw-pl-3[^"]*">\s*(?P<age>.*?)\s*</div>', re.S)
_JS_TYPE = re.compile(r'<span class="[^"]*tw-bg-\[[^\]]*\][^"]*">\s*(?P<job_type>[^<]*?)\s*</span>')
_JS_COMPANY = re.compile(r'<span[^>]*class="[^"]*tw-card-title[^"]*"[^>]*>(?P<company>.*?)</span>', re.S)
_JS_PLACE = re.compile(r'<span class="tw-location">(?P<place>.*?)</span>', re.S)


def parse_javascript_jobs(body: str, today: date | None = None) -> list[dict]:
    """Cards of https://javascript.jobs/jobs (title, employer, place, age)."""
    jobs: list[dict] = []
    for chunk in _chunks(body, _JS_ITEM):
        item = _JS_ITEM.search(chunk)
        if not item:
            continue
        title = _JS_TITLE.search(chunk)
        company = _JS_COMPANY.search(chunk)
        place = _JS_PLACE.search(chunk)
        age = _JS_AGE.search(chunk)
        job_type = _JS_TYPE.search(chunk)
        url = item.group("url")
        jobs.append({
            "title": _text(title.group("title")) if title else None,
            "company": _text(company.group("company")) if company else None,
            "location": _text(place.group("place")) if place else None,
            "url": url,
            "source_ref": url.rstrip("/").rsplit("/", 1)[-1],
            "workplace_type": "unknown",
            "posted_at": _relative_date(age.group("age") if age else None, today),
            "metadata": {
                "via": "javascript_jobs",
                "job_type": _text(job_type.group("job_type")) if job_type else None,
            },
        })
    return jobs


# --- relocate.me -------------------------------------------------------------
#
# The card is a country and a city (in the URL), the employer, the title and a
# truncated preview. A `job_featured` card is a partner advert, not a posting
# on this board, so it is dropped: the one on file sells a list of other jobs.
# The search box is a narrow phrase match (a query for one job title finds 17 of
# 25 live postings), so this board is read whole and the scorer decides.

_REL_ITEM = re.compile(r'<div class="jobs-list__job(?P<extra>[^"]*)"')
_REL_INFO = re.compile(
    r'<div class="job__info">(?P<body>.*?)<div class="job__title', re.S)
_REL_P = re.compile(r"<p>(?P<text>.*?)</p>", re.S)
_REL_LINK = re.compile(r'<a href="(?P<url>/[^"]+)">\s*<b>(?P<title>.*?)</b>', re.S)
_REL_PREVIEW = re.compile(r'class="job__preview">(?P<text>.*?)</p>', re.S)
_REL_TAIL_ID = re.compile(r"-(\d+)/?$")


def _relocate_place(url: str) -> dict:
    """`/netherlands/amsterdam/picnic/slug-10256` -> country and city slugs."""
    parts = [p for p in url.split("/") if p]
    return {"country_slug": parts[0] if parts else None,
            "city_slug": parts[1] if len(parts) > 1 else None}


def parse_relocate_me(body: str, today: date | None = None) -> list[dict]:
    """Cards of https://relocate.me/international-jobs.

    The first `<p>` in a card is where the employer sits ("Netherlands",
    "Japan", or "Remote"), the second is the employer. A relocation board's
    premise is that the posting comes with a visa, so the place is the useful
    statement; the classifier turns it into `region_gated`, which is correct:
    a role in Japan needs a permit that is not in hand.
    """
    jobs: list[dict] = []
    for chunk in _chunks(body, _REL_ITEM):
        item = _REL_ITEM.search(chunk)
        if not item:
            continue
        if "job_featured" in item.group("extra"):
            continue  # a partner advert, not one of this board's postings
        link = _REL_LINK.search(chunk)
        if not link:
            continue
        info = _REL_INFO.search(chunk)
        places = ([_text(m.group("text")) for m in _REL_P.finditer(info.group("body"))]
                  if info else [])
        place = places[0] if places else None
        company = places[1] if len(places) > 1 else None
        preview = _REL_PREVIEW.search(chunk)
        href = link.group("url")
        tail = _REL_TAIL_ID.search(href)
        jobs.append({
            "title": _text(link.group("title")),
            "company": company,
            "location": place,
            "url": "https://relocate.me" + href,
            "source_ref": tail.group(1) if tail else href.rstrip("/").rsplit("/", 1)[-1],
            "workplace_type": "remote" if (place or "").lower() == "remote" else "unknown",
            "metadata": {
                "via": "relocate_me",
                "employer_location": place,
                "preview": _text(preview.group("text")) if preview else None,
                **_relocate_place(href),
            },
        })
    return jobs


#: scan_config["mode"] -> parser.
LIST_MODES = {
    "jsgurujobs": parse_jsgurujobs,
    "javascript_jobs": parse_javascript_jobs,
    "relocate_me": parse_relocate_me,
}


# --- detail pages -----------------------------------------------------------
#
# Called only when a board sets scan_config `details`, because each one costs a
# request. Both return a partial row: whatever the detail page knows that the
# card did not (the fetcher decides what to overwrite and what to fill in).

_JD_PROSE = re.compile(r'<div class="[^"]*prose prose-sm[^"]*">')
_JD_POSTED = re.compile(r">Posted</dt>\s*<dd[^>]*>([^<]+)</dd>")
_LD_JSON = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)


def parse_jsgurujobs_detail(body: str) -> dict:
    """A jsgurujobs posting page: the description, and the date the card hides.

    The listing shows an age ("20 hours ago") while this page prints "Posted:
    October 18, 2026", which is worth the request on its own.
    """
    prose = _JD_PROSE.search(body)
    posted = _JD_POSTED.search(body)
    return {
        "description": _text(_inner_div(body, prose.start())) if prose else None,
        "posted_at": _absolute_date(posted.group(1)) if posted else None,
    }


def parse_javascript_jobs_detail(body: str) -> dict:
    """The fields a javascript.jobs posting page states in its JSON-LD block.

    Read field by field rather than parsed as a document, because this
    publisher's JSON-LD is malformed often enough to matter: members run
    together with no comma, strings carry raw newlines, and the last member is
    followed by a trailing comma. A strict parse loses the whole advert over
    damage that sits in another member (roughly one posting in ten when this
    was written), so each field is matched on its own and unescaped as the JSON
    string it is. The alternative is scoring those postings on the title alone.
    """
    match = _LD_JSON.search(body)
    if not match:
        return {}
    block = match.group(1)
    low, high = (_ld_number(block, "minValue") or None,
                 _ld_number(block, "maxValue") or None)  # 0 = the page states none
    detail = {
        "description": _text(_ld_string(block, "description")),
        "posted_at": (_ld_string(block, "datePosted") or "")[:10] or None,
        "employment_type": _ld_string(block, "employmentType"),
        "location": _text(", ".join(
            part for part in (_ld_string(block, "addressRegion"),
                              _ld_string(block, "addressCountry")) if part
        )) or None,
    }
    if low or high:
        detail |= {"salary_min": low, "salary_max": high,
                   "salary_currency": _ld_string(block, "currency")}
    return detail


#: Month abbreviations as Xing's JavaScript dates write them.
_MONTHS = {name: i for i, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def _xing_day(value) -> str | None:
    """`datePosted` in any of the shapes Xing publishes it -> ISO day.

    Four shapes are real, and taking the first ten characters of any of them
    stores something that is not a date ("Fri Aug 07" was in posted_at, where
    no lead digest can read an age from it):
      2026-09-18T00:26:18Z   the ISO timestamp schema.org asks for
      Fri Aug 07 2026 ...    a JavaScript Date string
      Fri, 07 Aug 2026 ...   RFC 2822
      Fri Oct 09 11:12:25 CEST 2026   what a partner's own posting (jobware)
                              publishes instead, with the year at the end
    Each is matched as a whole pattern; only when none fits is the day sought
    next to the month and the year looked for later in the string.
    """
    text = str(value or "").strip()
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return "-".join(iso.groups())
    month_day = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+((?:19|20)\d{2})\b", text)
    if month_day and month_day.group(1) in _MONTHS:
        return _day(month_day.group(3), month_day.group(1), month_day.group(2))
    day_month = re.search(r"\b(\d{1,2})\s+([A-Z][a-z]{2})\s+((?:19|20)\d{2})\b", text)
    if day_month and day_month.group(2) in _MONTHS:
        return _day(day_month.group(3), day_month.group(2), day_month.group(1))
    # Month and day together, year anywhere after: the day must not be two
    # digits of a time, so it may not touch a digit, a colon or a dot.
    for month in re.finditer(r"\b([A-Z][a-z]{2})\b", text):
        if month.group(1) not in _MONTHS:
            continue
        day = re.search(r"(?<![\d:.])(\d{1,2})(?![\d:.])", text[month.end():])
        year = re.search(r"(?<![\d:])((?:19|20)\d{2})\b", text[month.end():])
        if day and year:
            return _day(year.group(1), month.group(1), day.group(1))
    return None


def _day(year: str, month: str, day: str) -> str | None:
    """Year, month name and day of month -> ISO day, or None when the day is
    not a day (a date that reads 32 October is a parse that went wrong)."""
    if month not in _MONTHS or not 1 <= int(day) <= 31:
        return None
    return "%s-%02d-%02d" % (int(year), _MONTHS[month], int(day))


def parse_xing_detail(body: str) -> dict:
    """The fields a Xing posting page states in its JobPosting JSON-LD block.

    Xing renders its posting pages server-side, so one plain `_http_get` gets
    the whole advert (roughly 300 KB) and the block below it is the employer's
    own structured record. That is worth the request on a search-driven board,
    whose card carries the title, the company, the place and a salary band and
    nothing else: without it every posting scores on its title alone.

    Two members of the block decide where a posting may be worked, and they are
    not the same question:
      jobLocationType             "TELECOMMUTE" means the work is remote
      applicantLocationRequirements  which countries the employer accepts an
                                  application from, which is the eligibility
                                  sentence in structured form. A posting can
                                  be remote and still be closed to every
                                  country but one, so both go into metadata
                                  where the classifier reads them.

    The block is read as JSON when it parses, and member by member when it does
    not (the same defence as `parse_javascript_jobs_detail`, for the same
    reason: a stray comma must not cost the whole advert).
    """
    match = _LD_JSON.search(body)
    if not match:
        return {}
    block = match.group(1).strip()
    detail: dict = {"description": None, "posted_at": None, "location": None,
                    "employment_type": None, "workplace_type": None, "metadata": {}}
    data: dict | None = None
    try:
        parsed = json.loads(block)
        data = parsed if isinstance(parsed, dict) else None
    except ValueError:
        data = None

    if data:
        detail["description"] = _text(data.get("description") or "") or None
        detail["posted_at"] = _xing_day(data.get("datePosted"))
        detail["employment_type"] = _xing_type(data.get("employmentType"))
        detail |= _xing_salary(data.get("baseSalary"))
        detail |= _xing_place(data.get("jobLocation"))
        detail["workplace_type"] = (
            "remote" if str(data.get("jobLocationType") or "").upper() == "TELECOMMUTE"
            else None
        )
        detail["metadata"]["applicant_location_requirement"] = (
            _xing_countries(data.get("applicantLocationRequirements")) or None
        )
        detail["metadata"]["valid_through"] = _xing_day(data.get("validThrough"))
    else:
        detail["description"] = _text(_ld_string(block, "description")) or None
        detail["posted_at"] = _xing_day(_ld_string(block, "datePosted"))
        detail["employment_type"] = _xing_type(_ld_string(block, "employmentType"))
        low, high = (_ld_number(block, "minValue") or None,
                     _ld_number(block, "maxValue") or None)  # 0 = unstated
        if low or high:
            detail |= {"salary_min": low, "salary_max": high,
                       "salary_currency": _ld_string(block, "currency")}
        country = _ld_string(block, "addressCountry")
        locality = _ld_string(block, "addressLocality")
        region = _ld_string(block, "addressRegion")
        detail["location"] = ", ".join(
            part for part in (locality, region, country) if part
        ) or None
        detail["workplace_type"] = (
            "remote" if (_ld_string(block, "jobLocationType") or "").upper() == "TELECOMMUTE"
            else None
        )
    detail["metadata"] = {k: v for k, v in detail["metadata"].items() if v}
    return detail


def _xing_type(value) -> str | None:
    """`employmentType` as schema.org allows it: a string, or several kinds at
    once ("OTHER, FULL_TIME" on a partner's posting). One string either way,
    because metadata.job_type is read as one, and `OTHER` is dropped while
    another kind is stated — it says nothing on its own."""
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    kinds = list(dict.fromkeys(str(item) for item in items if item))
    if len(kinds) > 1 and "OTHER" in kinds:
        kinds = [kind for kind in kinds if kind != "OTHER"]
    return ", ".join(kinds) or None


def _xing_countries(value) -> str | None:
    """`applicantLocationRequirements`, in any of the shapes schema.org allows:
    one Country object, a list of them, or a bare string. Joined with ", "."""
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    names = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("alternateName")
        else:
            name = str(item)
        if name and name not in names:
            names.append(name)
    return ", ".join(names) or None


def _xing_place(value) -> dict:
    """`jobLocation` (one Place, or several) -> the "City, Region, CC" string
    the classifier reads, and nothing when the block states no address."""
    if not value:
        return {}
    places = value if isinstance(value, list) else [value]
    for place in places:
        address = (place or {}).get("address") if isinstance(place, dict) else None
        if not isinstance(address, dict):
            continue
        parts = [address.get(key) for key in ("addressLocality", "addressRegion",
                                              "addressCountry")]
        text = ", ".join(str(part) for part in parts if part)
        if text:
            return {"location": text}
    return {}


def _xing_salary(value) -> dict:
    """`baseSalary` -> the store's salary keys. A stated band of 0/0 means the
    employer printed no figure, so nothing is stored (the card's own band is
    already in the row and is not overwritten by an absent value)."""
    if not isinstance(value, dict):
        return {}
    currency = str(value.get("currency") or "").upper() or None
    raw = value.get("value") if isinstance(value.get("value"), dict) else value
    low, high = raw.get("minValue"), raw.get("maxValue")
    if not low and not high:
        return {}
    detail = {"salary_min": float(low) if low else None,
              "salary_max": float(high) if high else None}
    if currency:
        detail["salary_currency"] = currency
    return detail


def _ld_string(block: str, field: str) -> str | None:
    """One string member of the JSON-LD block, unescaped, or None.

    The match never spans a `\\` escape, so the captured token is always a
    well-formed JSON string even when the document around it is not.
    """
    match = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % field, block)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"', strict=False)  # raw newlines
    except ValueError:
        return None


def _ld_number(block: str, field: str) -> float | None:
    """One numeric member of the JSON-LD block, or None."""
    match = re.search(r'"%s"\s*:\s*(-?\d+(?:\.\d+)?)' % field, block)
    return float(match.group(1)) if match else None


#: relocate.me keeps its whole advert in a `JobPosting` JSON-LD block that is
#: not valid JSON: the strings carry raw newlines, so a document parse fails on
#: the first one. The fields are read one at a time instead.
_LD_BLOCK = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(?P<body>.*?)</script>',
    re.S | re.I,
)


def _ld_section(block: str, member: str, span: int = 500) -> str:
    """The slice after `"member"`, for fields nested inside an object."""
    at = block.find(f'"{member}"')
    return block[at: at + span] if at >= 0 else ""


def parse_relocate_me_detail(body: str) -> dict:
    """A relocate.me posting page: the advert, the dates, and the employer.

    The description arrives HTML-escaped inside the JSON string (`&lt;p&gt;`),
    so one `_text` pass both unescapes it and drops the tags. `validThrough` is
    kept in metadata because it is the board's own statement of when the
    posting closes, which a later run can use to archive it.
    """
    for match in _LD_BLOCK.finditer(body):
        block = match.group("body")
        if '"JobPosting"' not in block:
            continue
        low = _ld_number(block, "minValue")
        high = _ld_number(block, "maxValue")
        detail = {
            # The advert is escaped HTML inside the JSON string, so it needs one
            # unescape before `_text` can see the tags it must drop.
            "description": _text(html.unescape(_ld_string(block, "description") or "")),
            "posted_at": (_ld_string(block, "datePosted") or "")[:10] or None,
            "metadata": {
                "employment_type": _ld_string(block, "employmentType"),
                "hiring_org": _ld_string(_ld_section(block, "hiringOrganization"), "name"),
                "expires_at": (_ld_string(block, "validThrough") or "")[:10] or None,
            },
        }
        if low or high:
            detail |= {"salary_min": low, "salary_max": high,
                       "salary_currency": _ld_string(block, "currency")}
        return detail
    return {}


DETAIL_MODES = {
    "jsgurujobs": parse_jsgurujobs_detail,
    "javascript_jobs": parse_javascript_jobs_detail,
    "xing": parse_xing_detail,
    "relocate_me": parse_relocate_me_detail,
}


# --- self-test: real card markup, trimmed ----------------------------------

_JG_CARD = """
<div class="col-md-6"><div class="job-card">
  <div><h3 class="text-lg font-semibold leading-snug">
    <a href="https://jsgurujobs.com/jobs/1" class="hover:text-primary">
        Senior Full Stack JS Engineer
    </a></h3></div>
  <p class="mt-1 text-sm text-gray-500 break-words">Northwind Software</p>
  <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 items-center text-sm text-gray-500">
      <span>Armenia</span><span>Full-time</span><span>Not specified</span>
  </div>
  <div class="mt-2 flex flex-wrap items-center gap-1.5">
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">&#127757; Remote</span>
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">Worldwide</span>
  </div>
  <div class="flex items-center shrink-0 sm:pl-4">
      <span class="text-xs text-gray-400">20 hours ago</span>
  </div>
</div></div>
<div class="col-md-6"><div class="job-card">
  <div><h3 class="text-lg font-semibold leading-snug">
    <a href="https://jsgurujobs.com/jobs/2" class="hover:text-primary">
        Backend Engineer
    </a></h3></div>
  <p class="mt-1 text-sm text-gray-500 break-words">Acme</p>
  <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 items-center text-sm text-gray-500">
      <span>United States</span><span>Full-time</span><span>$150,000 - $200,000</span>
  </div>
  <div class="mt-2 flex flex-wrap items-center gap-1.5">
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">&#127757; Remote</span>
  </div>
  <div class="flex items-center shrink-0 sm:pl-4">
      <span class="text-xs text-gray-400">2 days ago</span>
  </div>
</div></div>
"""

_JS_CARD = """
<div class="col-xl-4 col-md-6 fade-in-bottom rt-mb-24 cat-1 cat-3"><div class="tw-relative tw-h-full">
<a href="https://javascript.jobs/job/full-stack-software-engineer-javascript"
    class="tw-h-full card tw-card tw-block jobcardStyle1 ">
    <div class="tw-p-6 tw-h-full">
        <div class="tw-mb-5">
            <div class="tw-mb-1.5 d-flex justify-content-between">
                <div class="tw-text-[#18191C] tw-text-lg tw-font-medium">
                    2 x Full stack Software Engineer - JavaScript Environment
                </div>
                <div class="tw-text-sm tw-text-[#767F8C] mt-1 tw-pl-3">
                    1W
                </div>
            </div>
            <div class="tw-flex tw-flex-wrap tw-gap-2 tw-items-center tw-mb-1.5">
                <span class="tw-text-[#0BA02C] tw-text-[12px] tw-leading-[12px] tw-font-semibold tw-bg-[#E7F6EA] tw-px-2 tw-py-1 tw-rounded-[3px]">
                    Full Time
                </span>
            </div>
        </div>
        <div class="rt-single-icon-box tw-flex-wrap tw-gap-4">
            <span><div class="tw-w-[56px] tw-h-[56px] d-flex align-items-center">
                <img class="tw-rounded-lg tw-w-[56px] tw-h-[56px] object-fit-contain" src="https://javascript.jobs/storage/images/company/6acb434c1f6e9.png"
                        alt="" draggable="false">
            </div></span>
            <div class="iconbox-content">
                <div class="tw-mb-1 tw-inline-flex">
                    <span
                        class="tw-text-base tw-font-medium tw-text-[#18191C] tw-card-title">Northwind</span>
                </div>
                <span class="tw-flex tw-items-center tw-gap-1 tw-text-[#18191C]">
                    <i class="ph ph-map-pin"></i>
                    <span class="tw-location">Australia</span>
                </span>
            </div>
        </div>
    </div>
</a>
</div></div>
<div class="col-xl-4 col-md-6 fade-in-bottom rt-mb-24 cat-1"><div class="tw-relative tw-h-full">
<a href="https://javascript.jobs/job/senior-front-end-developer-react"
    class="tw-h-full card tw-card tw-block jobcardStyle1 ">
    <div class="tw-p-6 tw-h-full">
        <div class="tw-mb-5">
            <div class="tw-mb-1.5 d-flex justify-content-between">
                <div class="tw-text-[#18191C] tw-text-lg tw-font-medium">
                    Senior Front-end Developer (React)
                </div>
                <div class="tw-text-sm tw-text-[#767F8C] mt-1 tw-pl-3">
                    3D
                </div>
            </div>
        </div>
        <div class="iconbox-content">
            <div class="tw-mb-1 tw-inline-flex">
                <span class="tw-text-base tw-font-medium tw-text-[#18191C] tw-card-title">Acme</span>
            </div>
            <span class="tw-flex tw-items-center tw-gap-1 tw-text-[#18191C]">
                <span class="tw-location">Poland</span>
            </span>
        </div>
    </div>
</a>
</div></div>
"""


_JG_DETAIL = """
                    <dl class="mt-5 grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-3">
                        <div class="sm:col-span-1">
                            <dt class="text-sm font-medium text-gray-500">Posted</dt>
                            <dd class="mt-1 text-sm text-gray-900">October 18, 2026</dd>
                        </div>
                    </dl>
                    <div class="bg-white shadow-none overflow-hidden">
                        <div class="px-4 py-5 sm:px-6">
                            <h3 class="text-lg font-medium text-gray-900">Job Description</h3>
                        </div>
                        <div class="border-t border-gray-200 px-4 py-5 sm:p-0">
                            <div class="px-4 py-5 sm:p-6 prose prose-sm max-w-none min-w-0 overflow-x-auto">
                                <h3>About the role</h3>
                                <p>Build things with <strong>TypeScript</strong>.</p>
                                <div class="nested"><p>Nested, so the depth count matters.</p></div>
                            </div>
                        </div>
                    </div>
                    <p class="page-chrome">Get hot jobs first on Telegram</p>
"""

_JS_DETAIL = """
<script type="application/ld+json">
{
    "@context" : "https://schema.org/",
    "@type" : "JobPosting",
    "title" : "Senior Front-end Developer",
    "description" : "<div><p>React and
    TypeScript, in a very long advert.</p></div>",
    "datePosted" : "2026-10-11 00:44:21"
    "employmentType" : "FULL_TIME",
    "jobLocation" : { "@type" : "Place", "address" : { "@type" : "PostalAddress",
        "addressRegion" : "New South Wales", "addressCountry" : "Australia" } },
    "baseSalary" : { "@type" : "MonetaryAmount", "currency": "USD",
        "value": { "@type": "QuantitativeValue", "minValue": 0, "maxValue": 0,
                   "unitText": "YEAR" } },
}
</script>
"""

#: Two cards and the partner advert, trimmed from the live listing. The
#: featured card is kept in the fixture because dropping it is the behaviour
#: under test: it sells a list of other jobs, not a job.
_REL_CARD = """
<div class="jobs-list">
  <div class="jobs-list__job job_featured">
    <div class="job__info">
      <div class="job__company text4-medium"><svg></svg><p>Remote</p></div>
      <div class="job__company text4-medium"><svg></svg><p>The Global Move</p></div>
    </div>
    <div class="job__title">
      <a href="/remote/remote/the-global-move/1700-curated-visa-sponsorship-and-remote-tech-jobs-paid-option-10080">
        <b>1700+ Curated Visa Sponsorship and Remote Tech Jobs (Paid Option)</b>
      </a>
    </div>
    <p class="job__preview">An archive of tech jobs.</p>
  </div>
  <div class="jobs-list__job">
    <div class="job__info">
      <div class="job__company text4-medium"><svg></svg><p>Netherlands</p></div>
      <div class="job__company text4-medium"><svg></svg><p>Picnic</p></div>
    </div>
    <div class="job__title">
      <a href="/netherlands/amsterdam/picnic/software-engineer-consumer-products-10256">
        <b>Software Engineer - Consumer Products</b>
                                in
        Amsterdam
      </a>
    </div>
    <p class="job__preview">In a nutshell At Picnic, we&rsquo;re redefining how people buy groceries and...</p>
  </div>
  <div class="jobs-list__job">
    <div class="job__info">
      <div class="job__company text4-medium"><svg></svg><p>Remote</p></div>
      <div class="job__company text4-medium"><svg></svg><p>Northwind</p></div>
    </div>
    <div class="job__title">
      <a href="/remote/remote/northwind/senior-backend-engineer-10310"><b>Senior Backend Engineer</b></a>
    </div>
    <p class="job__preview">Build the ledger.</p>
  </div>
</div>
"""

#: The posting page's JSON-LD, trimmed and kept broken on purpose: `title` spans
#: a raw newline, as every relocate.me block does, and the advert is escaped
#: HTML inside the JSON string. The BreadcrumbList block comes first, so a
#: parser that simply takes the first block fails this fixture.
_REL_DETAIL = """
<script type="application/ld+json">{"@context":"https://schema.org/","@type":"BreadcrumbList","itemListElement":[]}</script>
<script type="application/ld+json">{
  "@context" : "https://schema.org/",
  "@type" : "JobPosting",
  "title" : "Software Engineer - Consumer Products
| Relocation Offered
",
  "description" : "<b>About Picnic</b><br/><br/>&lt;p&gt;&lt;strong&gt;Building the supermarket on wheels&lt;/strong&gt;&lt;/p&gt;",
  "datePosted" : "2026-10-20",
  "validThrough" : "2027-10-20T00:00:00Z",
  "employmentType" : "FULL_TIME",
  "hiringOrganization" : { "@type" : "Organization", "name" : "Picnic" },
  "jobLocation" : [ { "@type" : "Place", "address" : { "@type" : "PostalAddress",
      "addressLocality" : "Amsterdam", "addressCountry" : "NL" } } ]
}</script>
"""

#: A real Xing block, trimmed: the same posting whose card the search page
#: shows. `÷` stands for the `\u002F` escape Xing writes its slashes as, so the
#: fixture is what a page looks like rather than a restatement of it.
_XING_DETAIL = """
<script type="application/ld+json">{"@context":"https:÷schema.org÷","@type":"JobPosting","title":"Backend Engineer (Node.js) (m÷w÷d)","description":"<H3>Ihre Vorteile:</H3><UL><LI>Du erhältst eine unbefristete Festanstellung</LI><LI>30 Tage Urlaub</LI></UL><H3>Ihre Aufgaben:</H3><UL><LI>Du entwickelst moderne Backend-Services mit Node.js</LI><LI>Du implementierst REST-APIs</LI></UL>","datePosted":"2026-09-18T00:26:18Z","directApply":true,"url":"https:÷www.xing.com÷jobs÷leipzig","validThrough":"2027-09-18T00:34:14Z","industry":"Beratung, Consulting","employmentType":"FULL_TIME","hiringOrganization":{"@type":"Organization","name":"Hays AG"},"jobLocation":[{"@type":"Place","address":{"@type":"PostalAddress","streetAddress":null,"addressLocality":"Leipzig","addressRegion":"Sachsen","postalCode":null,"addressCountry":"DE"}}]}</script>
"""

#: A remote posting whose employer named the country it accepts applications
#: from, plus a stated band. Xing's own blocks usually carry neither (the
#: salary band lives in the search page's own data, and the region gate is
#: applied server-side), so the parser treats both as optional.
_XING_DETAIL_REMOTE = """
<script type="application/ld+json">{"@context":"https:÷schema.org÷","@type":"JobPosting","title":"Full-Stack Engineer","description":"<P>Build the editor.</P>","datePosted":"2026-10-16","employmentType":"CONTRACTOR","jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"@type":"Country","name":"Germany"},"baseSalary":{"@type":"MonetaryAmount","currency":"EUR","value":{"@type":"QuantitativeValue","minValue":60000,"maxValue":80000,"unitText":"YEAR"}}}</script>
"""


def _xing_fixture(block: str) -> str:
    """The fixture with Xing's `\u002F` escapes restored, so a test reads against
    what the page really carries."""
    return block.replace("÷", "\\u002F")


def _self_test() -> int:
    total = failures = 0
    fixed = date(2026, 10, 19)

    def check(label: str, got, want) -> None:
        nonlocal total, failures
        total += 1
        ok = got == want
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))

    jg = parse_jsgurujobs(_JG_CARD, today=fixed)
    check("jsgurujobs rows", len(jg), 2)
    check("  title", jg[0]["title"], "Senior Full Stack JS Engineer")
    check("  company", jg[0]["company"], "Northwind Software")
    check("  worldwide badge becomes location", jg[0]["location"], "Worldwide")
    check("  employer place kept in metadata", jg[0]["metadata"]["employer_location"], "Armenia")
    check("  url", jg[0]["url"], "https://jsgurujobs.com/jobs/1")
    check("  source_ref", jg[0]["source_ref"], "1")
    check("  workplace_type", jg[0]["workplace_type"], "remote")
    check("  relative age (hours round to the same day)", jg[0]["posted_at"], "2026-10-19")
    check("  salary raw", jg[0]["metadata"]["salary_raw"], "Not specified")
    check("  no badge: the place span stands", jg[1]["location"], "United States")
    check("  second age", jg[1]["posted_at"], "2026-10-17")

    js = parse_javascript_jobs(_JS_CARD, today=fixed)
    check("javascript.jobs rows", len(js), 2)
    check("  title", js[0]["title"], "2 x Full stack Software Engineer - JavaScript Environment")
    check("  company", js[0]["company"], "Northwind")
    check("  location", js[0]["location"], "Australia")
    check("  job type", js[0]["metadata"]["job_type"], "Full Time")
    check("  age 1W", js[0]["posted_at"], "2026-10-12")
    check("  second company", js[1]["company"], "Acme")
    check("  age 3D", js[1]["posted_at"], "2026-10-16")
    check("  no job-type badge on 2nd card", js[1]["metadata"]["job_type"], None)

    jd = parse_jsgurujobs_detail(_JG_DETAIL)
    check("jsgurujobs detail: description", jd["description"],
          "About the role Build things with TypeScript . Nested, so the depth count matters.")
    check("  absolute posted date (not the card's age)", jd["posted_at"], "2026-10-18")
    check("  the description stops at its own div", "page-chrome" in (jd["description"] or ""), False)

    jd2 = parse_javascript_jobs_detail(_JS_DETAIL)
    check("javascript.jobs detail: advert despite broken JSON-LD", jd2["description"],
          "React and TypeScript, in a very long advert.")
    check("  datePosted", jd2["posted_at"], "2026-10-11")
    check("  employmentType", jd2["employment_type"], "FULL_TIME")
    check("  jobLocation -> region, country", jd2["location"], "New South Wales, Australia")
    check("  salary 0/0 is unstated, not zero", "salary_min" in jd2, False)

    xd = parse_xing_detail(_xing_fixture(_XING_DETAIL))
    check("xing detail: advert text, tags dropped", xd["description"],
          "Ihre Vorteile: Du erhältst eine unbefristete Festanstellung 30 Tage Urlaub "
          "Ihre Aufgaben: Du entwickelst moderne Backend-Services mit Node.js "
          "Du implementierst REST-APIs")
    check("  datePosted is a timestamp, stored as a day", xd["posted_at"], "2026-09-18")
    check("  employmentType", xd["employment_type"], "FULL_TIME")
    check("  jobLocation list -> locality, region, country", xd["location"],
          "Leipzig, Sachsen, DE")
    check("  no band in the block, so no salary keys", "salary_min" in xd, False)
    check("  no TELECOMMUTE, so no workplace claim", xd["workplace_type"], None)
    check("  no country requirement stated", "applicant_location_requirement" in xd["metadata"],
          False)
    check("  validThrough kept as a day", xd["metadata"]["valid_through"], "2027-09-18")

    xr = parse_xing_detail(_xing_fixture(_XING_DETAIL_REMOTE))
    check("xing remote detail: TELECOMMUTE becomes remote", xr["workplace_type"], "remote")
    check("  the country the employer accepts", xr["metadata"]["applicant_location_requirement"],
          "Germany")
    check("  stated band, integer values", (xr["salary_min"], xr["salary_max"]),
          (60000.0, 80000.0))
    check("  currency", xr["salary_currency"], "EUR")
    check("  description still text", xr["description"], "Build the editor.")

    check("xing detail: no block at all", parse_xing_detail("<html><body>nope</body></html>"),
          {})

    rl = parse_relocate_me(_REL_CARD, today=fixed)
    check("relocate.me rows: the featured partner card is dropped", len(rl), 2)
    check("  title from the anchor, not the 'in City' tail", rl[0]["title"],
          "Software Engineer - Consumer Products")
    check("  company from the second place line", rl[0]["company"], "Picnic")
    check("  country is the location", rl[0]["location"], "Netherlands")
    check("  url made absolute", rl[0]["url"],
          "https://relocate.me/netherlands/amsterdam/picnic/"
          "software-engineer-consumer-products-10256")
    check("  source_ref is the posting id", rl[0]["source_ref"], "10256")
    check("  place-based card is not claimed remote", rl[0]["workplace_type"], "unknown")
    check("  country and city slugs kept", (rl[0]["metadata"]["country_slug"],
                                            rl[0]["metadata"]["city_slug"]),
          ("netherlands", "amsterdam"))
    check("  preview kept as metadata, not description", rl[0]["metadata"]["preview"],
          "In a nutshell At Picnic, we’re redefining how people buy groceries and...")
    check("  a Remote card is remote", rl[1]["workplace_type"], "remote")
    check("  second card location", rl[1]["location"], "Remote")

    rd = parse_relocate_me_detail(_REL_DETAIL)
    check("relocate.me detail: advert from the escaped HTML string", rd["description"],
          "About Picnic Building the supermarket on wheels")
    check("  datePosted", rd["posted_at"], "2026-10-20")
    check("  employmentType", rd["metadata"]["employment_type"], "FULL_TIME")
    check("  hiring organization", rd["metadata"]["hiring_org"], "Picnic")
    check("  validThrough kept as a day", rd["metadata"]["expires_at"], "2027-10-20")
    check("  no band stated, so no salary keys", "salary_min" in rd, False)
    check("relocate.me detail: no JobPosting block", parse_relocate_me_detail("<html></html>"),
          {})

    check("xing day: ISO timestamp", _xing_day("2026-09-18T00:26:18Z"), "2026-09-18")
    check("xing day: bare day", _xing_day("2026-10-16"), "2026-10-16")
    check("xing day: JavaScript Date string", _xing_day("Fri Aug 07 2026 00:26:18 GMT+0200"),
          "2026-08-07")
    check("xing day: JavaScript Date string with its zone name",
          _xing_day("Fri Aug 07 2026 00:26:18 GMT+0200 (Mitteleuropäische Sommerzeit)"),
          "2026-08-07")
    check("xing day: RFC 2822", _xing_day("Fri, 07 Aug 2026 00:26:18 GMT"), "2026-08-07")
    check("xing day: partner's own shape, year at the end",
          _xing_day("Fri Oct 09 11:12:25 CEST 2026"), "2026-10-09")
    check("xing day: the time's digits are not the day",
          _xing_day("Mon Dec 29 11:12:25 CET 2026"), "2026-12-29")
    check("xing day: no date at all", _xing_day("yesterday"), None)
    check("xing day: empty", _xing_day(None), None)

    check("xing employment: one kind", _xing_type("FULL_TIME"), "FULL_TIME")
    check("xing employment: several kinds at once", _xing_type(["OTHER", "PART_TIME", "FULL_TIME"]),
          "PART_TIME, FULL_TIME")
    check("xing employment: only OTHER is stated", _xing_type(["OTHER"]), "OTHER")
    check("xing employment: nothing stated", _xing_type(None), None)

    print(f"\n{total - failures}/{total} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
