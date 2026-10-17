"""Daily job-board scanner.

Strategy per board comes from `boards.scan_strategy` + `boards.scan_config`:
  rss    - public RSS/Atom feed (feed_url)
  api    - public JSON API (currently remotive)
  jobspy - scraped via the python-jobspy library (source, search_term, ...)
  html   - placeholder: no scraper yet, skipped with a note
  manual - never scanned automatically (e.g. saved Google searches)

Run: python3 -m scanner [--board NAME] [--dry-run] [--min-score N]
"""
