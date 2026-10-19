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


#: scan_config["mode"] -> parser.
LIST_MODES = {
    "jsgurujobs": parse_jsgurujobs,
    "javascript_jobs": parse_javascript_jobs,
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


DETAIL_MODES = {
    "jsgurujobs": parse_jsgurujobs_detail,
    "javascript_jobs": parse_javascript_jobs_detail,
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

    print(f"\n{total - failures}/{total} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
