# Tooling: OpenCLI Browser Bridge + desktop

Load when driving the browser (nearly every application session).

## Session pattern

- `opencli --profile <name> browser jobfit <cmd>` — reuse the `jobfit`
  session to keep tab/state alive.
- Two profiles connect (`g3pxjge8`, `6bfymbf4`) → always pass
  `--profile <name>`. `opencli doctor` FAILs on multi-profile even with
  `--profile` given (ignore that; commands work).
- Options go AFTER the subcommand: `browser jobfit tab list --window
  background` works, `browser --window background jobfit …` dies with
  `unknown command 'jobfit'` (commander reads the session name as its
  subcommand).

## Reading a page's data (not filling a form)

The same bridge that fills forms also reads a page whose data never leaves the
browser. Three commands, and the tab is closed again (tested 19/10/2026):

```bash
# 1. open a fresh tab; prints {"page": "<target id>", "url": "..."}
opencli --profile g3pxjge8 browser jobfit tab new '<url>' --window background
# 2. run one JS expression in that tab; prints its value
opencli --profile g3pxjge8 browser jobfit eval 'JSON.stringify([...])' --tab '<id>'
# 3. always close it, including on failure
opencli --profile g3pxjge8 browser jobfit tab close '<id>'
```

- `eval` prints the expression's value: a bare `JSON.stringify(...)` comes back
  as JSON text, so parse from the first `[`/`{` rather than expecting an
  envelope.
- Return a JSON string of only the fields wanted. Shipping a page's whole state
  through stdout is slow; HiringCafe's `__NEXT_DATA__` is megabytes, the
  adapter's 120 rows are not.
- A client-rendered page is empty for the first seconds. `eval` does await a
  promise it is handed (both adapters are async IIFEs, and the Work at a Startup
  one makes its own requests inside the eval), but a page that has not fetched
  its data yet has nothing to give. So the convention the scanner relies on:
  return `null` until the data exists (`[]` means "loaded, nothing found"), and
  the caller retries.
- `--window background` keeps focus where it was; the tab may still take
  focus for a moment while it loads.
- This is what `mode: opencli_eval` does per scan (`scanner/js/<js_file>` is the
  adapter); `python3 -m scanner --board HiringCafe --dry-run` is the manual
  equivalent.


## Commands that matter

- `type '<css>' '<text>'` — clicks then types (comboboxes); `fill '<css>'
  '<text>'` — plain inputs, verifies value afterwards; `keys
  ArrowUp|ArrowDown|Enter|Escape|Tab`; `click '<css>|<ref>|--role/--name'`;
  `state` (full AX tree — best readback); `find --css/--role/--name`;
  `select` for react-select comboboxes; `upload` for file inputs (fails on
  hidden/styled inputs like Greenhouse's); `screenshot [path] [--annotate]
  [--full-page] [--width/--height]`.

## Inspection gotchas

- OpenCLI `eval` does not await promises — stash async results on `window.*`
  and read back in a second call.
- `eval` output can vanish when the CLI prints update notices to stdout —
  always pipe through `tail`/`grep`, or prefer `state` for readbacks.
- Screenshots capture always works; whether the active model can VIEW them
  varies. Test 17/10/2026: `read_files` on the png → "Current model does not
  support image input" — so for this runtime fall back to text/DOM
  (`state`/`extract`/`find`/`eval`); screenshots only for layout/overlap
  questions when viewable. Re-test before assuming either way.

## Session tab survival (tested 18/10/2026)

A long-running fill can come back to `about:blank`, losing everything typed so
far. ATS forms keep no server-side draft, so this is lost work, not a refresh.

- What it is NOT: a plain idle timeout. Test: opened the form, ran nothing for
  100s, re-read the URL — the tab was still on the form. So do not assume
  "work fast or lose it" is the whole story.
- What it most likely is: the session tab going away underneath the bridge
  (window/tab closed, browser or machine restarted/slept, extension reloaded),
  after which the next command silently reconnects to a placeholder blank tab
  with a NEW page id. Observed once after a multi-minute gap: same page id as
  the very first `open`, URL `about:blank`, and it was the only tab.
- Guards that work:
  - Re-read `tab list` (or `eval location.href`) before resuming any session
    and treat `about:blank` as "the page is gone, reopen it".
  - Pin the tab explicitly: `tab new <url>` then `tab select <targetId>`, so
    there is a handle to re-select instead of landing on a placeholder.
  - Fill the whole form in one pass and hand over for submission immediately;
    do not leave a part-filled ATS form sitting between turns.
- Version note: v1.8.8 / extension v1.0.24 were current; v2.0.0 / v1.0.25
  were offered as updates. Worth applying before blaming the workflow.

## Reuse: recipes for now, a plugin only if filling becomes the bottleneck

Decided 18/10/2026. Reuse belongs on the side we control, and that side already
has it (`review submitted`, `review reply`, the `FOLLOW_UP_AFTER_DAYS`
follow-up reminder).
The browser side stays case by case, because we do not control those forms.

OpenCLI does have the extension point if that changes: `opencli plugin create
<name>` scaffolds a plugin, `plugin install github:user/repo` installs one, and
`adapter eject <site>` copies one of the 1568 official site CLIs into
`~/.opencli/clis/` to edit locally (`adapter status` reports local overrides
against the official baseline). None of the 1568 is Greenhouse, Lever, Ashby or
Workday, so a Greenhouse plugin would be new work rather than a tweak, and every
employer's board adds its own custom questions on top of the form anyway. Until
the recipe is genuinely the slow part, `_docs/greenhouse.md` is the mechanism.

## Ashby field ids change per page load

Ashby regenerates the UUID prefix of each field wrapper on every render, e.g.
`064e91b4-…-labeled-radio-5` became `2e81d594-…-labeled-radio-5` after a
reload, so a selector captured earlier silently stops matching (a `fill` on it
fails `selector_not_found`, and a stale `label[for=…]` click hits nothing).

- Prefer stable suffix selectors for the parts that do repeat:
  `label[for$="-labeled-radio-5"]`, or re-read ids from `state` immediately
  before acting.
- System fields (`#_systemfield_name/email/resume`) are stable; the
  application's own custom fields are not.
- Ids beginning with a digit are invalid CSS ids: use `[id="064e91b4-…"]`,
  not `#064e91b4-…`.

## Desktop (GNOME/Wayland)

- Cannot maximize or move the Chrome window programmatically: wmctrl absent,
  xdotool blind to Wayland windows, GNOME Shell Eval disabled
  (`gdbus … Eval` → `(false,'')`). CDP port 9222 exposes extension targets
  only (no pages) — no `Browser.setWindowBounds` either. OpenCLI `--window
  foreground` sets focus only. Ask the human to press `Super+Up`.
