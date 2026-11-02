// Xing job search results, read from the list DOM in your own Chrome.
//
// Xing's search is a React app: `/jobs/search?keywords=...` redirects to
// `/jobs/search/ki?keywords=...&id=...`, the results render client-side, and
// only a page or two of them are in the DOM until "Show more" is clicked. So
// scan_config mode "opencli_eval" opens the search URL in your logged-in Chrome
// through OpenCLI's Browser Bridge and evaluates THIS FILE in the page.
//
// Contract with scanner/fetchers.fetch_opencli_eval:
//   - the file must be one expression whose value is a JSON string
//   - that JSON must be an array of rows keyed as store.upsert_job expects
//   - return null (not []) while the page is not ready, so the fetcher retries
//     ("jobs found" in the body is the marker that the result list settled;
//      a login wall or a redirect has no such line, and never reads as an
//      empty board)
//
// What it reads, and why:
//   title      [data-testid=job-teaser-list-title] on the card
//   company    the employer logo's title attribute; the card's own second
//              text line when there is no logo (partner "external job ad"
//              cards carry the name only as text)
//   location   the remaining card line. Xing writes a place, or the word
//              Remote, and the region classifier reads it either way.
//   salary     the card's own band ("EUR 54,500 - 70,500"), split into
//              salary_min/salary_max/salary_currency
//   description the card text. A row without an advert scores on its title
//              alone, so scan_config `details: true` reads the posting's own
//              JSON-LD and overwrites it (mode `xing` in scanner/html_boards).
(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const JUNK = new Set([
    "Save job", "External job ad", "External job ad. Posted by a partner.",
    "Visit employer website", "Be an early applicant", "Show more", "New",
    "Hot", "Direct employer",
  ]);
  // The card's own age line ("3 days ago", "Posted 3 days ago"). It is the
  // list page's wording, not the posting's, and it belongs in neither the
  // place nor the advert: the JSON-LD datePosted in the detail pass is what
  // becomes posted_at.
  const AGE = /^(?:posted\s+)?\d+\s+(?:minutes?|hours?|days?|weeks?|months?|years?)\s+ago$/i;
  const cards = () => Array.from(
    document.querySelectorAll('[data-testid="job-search-result"]'));

  // Not settled yet: the page has no result count. A signed-out or
  // redirected page has no count either, so it stays null and the fetcher
  // reports an error instead of storing an empty run. The body itself can be
  // missing when the first evaluation races the tab's own load.
  const bodyText = (document.body && document.body.innerText) || "";
  if (!/\bjobs?\s+found\b/i.test(bodyText)) return null;

  const read = () => cards().map((card) => {
    const lines = (card.innerText || "").split("\n").map((s) => s.trim())
      .filter(Boolean).filter((s) => !JUNK.has(s));
    const titleNode = card.querySelector('[data-testid="job-teaser-list-title"]');
    const title = (titleNode ? titleNode.innerText : lines[0] || "").trim();
    const logo = card.querySelector("img[title]");
    // The title line leaves first: a posting called "Full Stack Engineer"
    // would otherwise be read as the employment type, and the card's own
    // "Full-time" badge would land in the location instead of the type.
    const others = lines.filter((s) => s !== title);
    const type = others.find((s) =>
      /^(full[-\s]?time|part[-\s]?time|internship|working student|freelance|permanent|temporary|contract|vollzeit|teilzeit|praktikum|werkstudent)/i.test(s)) || "";
    // The band, recognised by its currency mark: "€66,000 – €83,500". The
    // mark first, because a bare "2024 - 2026" would be a place line.
    const salaryLine = others.find((s) => /[€$£]|EUR|USD|GBP/i.test(s)
      && /\d/.test(s) && /[–—-]/.test(s)) || "";
    const rest = others.filter((s) => s !== type && s !== salaryLine && !AGE.test(s));
    // No logo means a partner card, whose employer name is the first line
    // after the title. One line left is the place, not the employer.
    const company = logo ? (logo.title || logo.getAttribute("aria-label") || "")
      : rest.length > 1 ? rest[0] : "";
    const place = (logo || rest.length < 2 ? rest : rest.slice(1))
      .filter((s) => s !== company).join(", ");

    let href = (card.querySelector("a[href]") || {}).getAttribute
      ? card.querySelector("a[href]").getAttribute("href") : "";
    if (!href) return null;
    const url = href.startsWith("http") ? href : "https://www.xing.com" + href;

    const numbers = salaryLine.match(/\d[\d.,]*/g) || [];
    const money = numbers.map((n) => Number(n.replace(/[.,]/g, ""))).filter((n) => !Number.isNaN(n));
    const currency = /€|EUR/i.test(salaryLine) ? "EUR"
      : /\$|USD/i.test(salaryLine) ? "USD"
      : /£|GBP/i.test(salaryLine) ? "GBP" : null;
    const where = place.toLowerCase();
    const workplace = /\bremote\b/.test(where) ? "remote"
      : /\bhybrid\b/.test(where) ? "hybrid" : "unknown";
    const ref = (url.match(/-(\d{6,})\/?$/) || [])[1] || "";
    const query = (new URLSearchParams(window.location.search).get("keywords")) || "";

    return {
      title,
      company,
      url,
      source_ref: ref || undefined,
      location: place || undefined,
      workplace_type: workplace,
      // The card in reading order, minus the chrome. The posting's own advert
      // overwrites this on the same run (scan_config `details`).
      description: [title, company, place, type, salaryLine]
        .filter(Boolean).join("\n"),
      salary_min: money.length ? money[0] : undefined,
      salary_max: money.length > 1 ? money[1] : undefined,
      salary_currency: money.length && currency ? currency : undefined,
      metadata: {
        via: "xing",
        employment_type: type || null,
        search_keywords: query || null,
      },
    };
  }).filter((row) => row && row.title && row.url);

  // Expand the list: Xing renders a few cards and puts the rest behind
  // "Show more". Four clicks take the page to roughly thirty cards, which is
  // worth the four seconds on a scan that runs once a day.
  const more = () => Array.from(document.querySelectorAll("button")).find(
    (b) => (b.innerText || "").trim() === "Show more");
  return (async () => {
    for (let i = 0; i < 4 && more(); i++) {
      more().click();
      await sleep(1200);
    }
    return JSON.stringify(read());
  })();
})()
