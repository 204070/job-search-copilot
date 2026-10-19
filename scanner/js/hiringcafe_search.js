// HiringCafe search results, read from the page's own SSR state.
//
// HiringCafe's listing is a React app whose first page arrives server-rendered
// into window.__NEXT_DATA__.props.pageProps.ssrHits, and plain HTTP gets a
// Cloudflare 403, so scan_config mode "opencli_eval" opens the search URL in
// your own logged-in Chrome through OpenCLI's Browser Bridge and evaluates
// THIS FILE in the page.
//
// Contract with scanner/fetchers.fetch_opencli_eval:
//   - the file must be one expression whose value is a JSON string
//   - that JSON must be an array of rows keyed as store.upsert_job expects
//   - return null (not []) while the page is not ready, so the fetcher retries
//
// What it reads, and why:
//   location   the posting's own place string ("Bangalore, Karnataka, India",
//              "Minnesota or District of Columbia"), which is what the region
//              classifier reads. HiringCafe's derived is_workplace_worldwide_ok
//              flag is reported in metadata instead of posing as the ad's
//              wording; across a 120-row page it was true for none of them.
//   description  HiringCafe's own requirements summary plus the tools it lists,
//              so the job scores on the stack rather than the title alone.
(() => {
  const props = window.__NEXT_DATA__ && window.__NEXT_DATA__.props
    && window.__NEXT_DATA__.props.pageProps;
  if (!props || !Array.isArray(props.ssrHits)) return null;  // not ready yet

  const rows = props.ssrHits.filter(h => h && !h.is_expired).map(h => {
    const info = h.job_information || {};
    const data = h.v5_processed_job_data || {};
    const countries = Array.isArray(data.workplace_countries) ? data.workplace_countries : [];
    const tools = Array.isArray(data.technical_tools) ? data.technical_tools.join(", ") : "";
    return {
      title: info.title || info.job_title_raw || "",
      company: data.company_name || "",
      // The employer's own posting, which is what a deduped row should point at.
      url: h.apply_url || "",
      source_ref: String(h.id || h.objectID || ""),
      location: data.formatted_workplace_location || countries.join(", "),
      workplace_type: (data.workplace_type || "").toLowerCase(),
      description: [data.requirements_summary, tools].filter(Boolean).join(" "),
      posted_at: data.estimated_publish_date || "",
      metadata: {
        via: "hiringcafe",
        workplace_type_raw: data.workplace_type || null,
        worldwide_ok: data.is_workplace_worldwide_ok === true,
        countries: countries
      }
    };
  });
  return JSON.stringify(rows);
})()
