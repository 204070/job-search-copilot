// Work at a Startup (Y Combinator): the search, read from the page's own
// Algolia credentials.
//
// What was checked before writing this (19/10/2026), cheapest path first:
//   - no feed exists. /jobs.rss and /jobs.json answer 406 (the Rails route has
//     no rss or json format), /feed, /rss.xml, /feed.xml and /sitemap.xml are
//     404, robots.txt is empty. ycombinator.com/jobs has an alternate link, but
//     it points at the blog feed.
//   - the list is not in the page either. https://www.workatastartup.com/jobs
//     server-renders 28 sample rows into its Inertia payload and ignores the
//     query string entirely (same 28 ids with the filters, and again for
//     page=2). The signed-in /companies?<filters> URL renders a company page
//     whose job rows arrive afterwards.
//   - the search behind both is Algolia: index WaaSPublicCompanyJob_production
//     on app 45BWZJ1SGC. Each page load mints a search credential into
//     window.AlgoliaOpts (renewed from /jobs_algolia_credential.json when it
//     lapses, valid_until about a day out), so it cannot be stored and plain
//     HTTP cannot do this: the credential the *public* pages mint is tag
//     filtered to (none) and answers 0 hits to every query.
//
// So this adapter asks for the credential the page is already holding and
// queries the index itself, in the page, and returns the rows the store takes.
//
// Contract with scanner/fetchers.fetch_opencli_eval: one expression whose value
// is a JSON string - an array of rows keyed as store.upsert_job expects - or
// null while the page is not ready (that is what makes the fetcher retry).
//
// What it reads, and why:
//   url          the public posting on ycombinator.com (Algolia's `search_path`,
//                .../companies/<company>/jobs/<slug>); the WaS page /jobs/<id>
//                is kept in metadata. A row needs no detail fetch at all here:
//                the index stores the whole advert inline (2-4 KB).
//   description  that advert, which is what the score reads.
//   location     the most specific places the ad names ("San Francisco, CA, US"),
//                joined with " | " when there are several that are not just a
//                country, because the region classifier reads a list that names
//                another region as a list to check rather than a US-only bar.
//                The full hierarchy, `remote` and `us_visa_required` ride in
//                metadata.
(async () => {
  if (document.readyState !== "complete") return null;  // not ready yet

  const opts = window.AlgoliaOpts;
  const tags = String((opts && opts.tag_filters) || "");
  if (!opts || !opts.app || !opts.key || tags.indexOf("jobs_applicant") < 0) {
    // Signed out, the page either carries no credentials or the public ones,
    // which are tag filtered to (none) and can read nothing. Falling through
    // would report an empty board, which reads as "no jobs today".
    throw new Error(
      "Work at a Startup: the YC session in Chrome is not signed in (credentials "
      + (opts ? "are the public ones, tag filtered to " + tags : "are absent")
      + "). Sign in at workatastartup.com, then scan this board again."
    );
  }

  const INDEX = "WaaSPublicCompanyJob_production";
  // Exactly what the site itself sends for the saved search in scan_config.url
  // (taken from its own request body): engineering roles, full time, and only
  // ads that do not require a US visa.
  const FILTERS = '(role:eng) AND (us_visa_required:none OR us_visa_required:possible) '
    + 'AND (job_type:"fulltime")';
  const FIELDS = ["id", "title", "description", "created_at", "search_path",
    "locations_for_search", "remote", "us_visa_required", "job_type", "eng_type",
    "skills", "min_experience", "has_salary", "has_equity", "company_name",
    "company_id", "company_website"];
  const PER_PAGE = 100;
  const MAX_PAGES = 12;  // 758 ads answered this filter on 19/10/2026

  const endpoint = "https://" + String(opts.app).toLowerCase()
    + "-dsn.algolia.net/1/indexes/*/queries";
  const rows = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        "X-Algolia-Application-Id": opts.app,
        "X-Algolia-API-Key": opts.key,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        requests: [{
          indexName: INDEX,
          params: "query=&filters=" + encodeURIComponent(FILTERS)
            + "&hitsPerPage=" + PER_PAGE + "&page=" + page + "&distinct=false"
            + "&attributesToRetrieve=" + encodeURIComponent(JSON.stringify(FIELDS))
        }]
      })
    });
    if (!res.ok) {
      throw new Error(
        "Work at a Startup: the search answered HTTP " + res.status
        + " (the page credential lapses after about a day - reload the page and rescan)"
      );
    }
    const json = await res.json();
    const result = (((json || {}).results) || [])[0] || {};
    const hits = result.hits || [];
    for (const h of hits) {
      // The field can repeat an entry (one ad carried its place blurb twice),
      // and the order is country -> region -> city, so the city-level entries
      // are the ones worth keeping when there are any.
      const all = (Array.isArray(h.locations_for_search) ? h.locations_for_search : [])
        .filter((p, i, a) => typeof p === "string" && p && a.indexOf(p) === i);
      const specific = all.filter(p => p.indexOf(",") >= 0);
      rows.push({
        title: h.title || "",
        company: h.company_name || "",
        url: h.search_path || ("https://www.workatastartup.com/jobs/" + h.id),
        source_ref: String(h.id == null ? (h.objectID || "") : h.id),
        location: (specific.length ? specific : all).join(" | "),
        workplace_type: h.remote === "yes" || h.remote === "only" ? "remote"
          : h.remote === "no" ? "onsite" : "unknown",
        description: h.description || "",
        posted_at: h.created_at || "",
        metadata: {
          via: "workatastartup",
          waas_url: "https://www.workatastartup.com/jobs/" + h.id,
          remote: h.remote || null,
          us_visa_required: h.us_visa_required || null,
          job_type: h.job_type || null,
          eng_type: h.eng_type || [],
          skills: h.skills || [],
          min_experience: h.min_experience,
          has_salary: h.has_salary === true,
          has_equity: h.has_equity === true,
          company_website: h.company_website || null,
          locations_for_search: all
        }
      });
    }
    if (page + 1 >= (result.nbPages || 1)) break;
  }
  return JSON.stringify(rows);
})()
