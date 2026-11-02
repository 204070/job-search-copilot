# Tooling: OpenCLI Browser Bridge + desktop

Load when driving the browser (nearly every application session).

## Session pattern

- `opencli --profile <name> browser --session jobfit <cmd>` — reuse the
  `jobfit` session to keep tab/state alive.
- **opencli 2.x takes the session as `--session <name>`**, an option on
  `browser`. Version 1.x took it as a positional (`browser jobfit <cmd>`), and
  on 2.x that form dies with `unknown command 'jobfit'`. The upgrade from 1.8.8
  to 2.0.2 on 29/10/2026 changed this, so an old habit or an old note is the
  first thing to suspect when a browser command answers `unknown command`.
  `opencli browser --session jobfit tab list` and `opencli browser tab list
  --session jobfit` both work; keep the option before the subcommand.
- **`--tab` is an option of the subcommand, not of `browser`.** Put it after
  the subcommand (`... browser --session jobfit eval '<js>' --tab <id>`), which
  is where it was written on every earlier run. Placed before `eval` it dies
  with `unknown option '--tab'`, and a script that built its argv that way
  reports every call as failed while the session is fine.
- More than one profile can connect → always pass
  `--profile <name>`. `opencli doctor` FAILs on multi-profile even with
  `--profile` given (ignore that; commands work).
- **`open` in a session that holds no tab takes over a tab another session
  holds** (measured 22/10/2026). `browser --session tracium open <url>` with
  `tracium` empty came back with the target id `jobfit` was bound to, so it navigated
  that tab away and the filled form on it was lost. So: check `tab list`
  before `open`. Empty session? Make the tab with `tab new <url>` and close it
  after, which never reuses a tab. Need that session to own a tab? `bind` it
  first, so the tab is its own.
- **`tab close` can take the whole window, and every tab in it, down with the
  tab** (measured 23/10/2026). A session with one filled form open, then a
  second form made with `tab new`, then `tab close` on the second, left the
  session on `about:blank` and the filled form gone. Ashby keeps no
  server-side draft, so the fill had to be redone. Do not open a second form of
  the same board to compare: read the other posting with a plain `fetch` of the
  board's JSON API instead, and keep the one form tab alone until it is
  submitted.

## Reading a page's data (not filling a form)

The same bridge that fills forms also reads a page whose data never leaves the
browser. Three commands, and the tab is closed again (tested 19/10/2026):

```bash
# 1. open a fresh tab; prints {"page": "<target id>", "url": "..."}
opencli --profile <profile-id> browser --session jobfit tab new '<url>' --window background
# 2. run one JS expression in that tab; prints its value
opencli --profile <profile-id> browser --session jobfit eval 'JSON.stringify([...])' --tab '<id>'
# 3. always close it, including on failure
opencli --profile <profile-id> browser --session jobfit tab close '<id>'
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

- **`eval` awaits the promise it is handed** (measured 19/10/2026).
  `eval 'new Promise(r => setTimeout(() => r("x"), 700))'` prints `x`, and an
  async IIFE prints its resolved value, which is why an adapter can be one async
  IIFE. A rejection is an error, not a value: exit 1, empty stdout, and
  `✖ Error: <message>` plus a stack on stderr. That is how a board reports "my
  session expired" so the caller cannot read it as "0 postings".
- The `window.*` stash is for a value that arrives after the eval has returned:
  `eval 'window.__x = f(); window.__x'` prints the immediate value, and a second
  `eval 'window.__x'` prints the late one.
- `eval` output can vanish when the CLI prints update notices to stdout —
  always pipe through `tail`/`grep`, or prefer `state` for readbacks.
- Screenshots capture always works; whether the active model can VIEW them
  varies. Test 17/10/2026: `read_files` on the png → "Current model does not
  support image input" — so for this runtime fall back to text/DOM
  (`state`/`extract`/`find`/`eval`); screenshots only for layout/overlap
  questions when viewable. Re-test before assuming either way.

## Session tab survival: the 10-minute `about:blank` reset (resolved 23/10/2026)

A filled form left open for review can redirect to `about:blank` (or close)
after 10 minutes of CLI inactivity, losing everything typed on it.

- **Exact cause (verified in the OpenCLI Chrome extension `background.js`,
  v1.0.24 through v1.0.26):**
  - Every tab created via `opencli browser --session <session> open` or `tab new` is
    marked `session.owned = true` with a default idle timer of
    `IDLE_TIMEOUT_INTERACTIVE = 6e5` (**600,000 ms = 10 minutes**). That is why
    the 100-second test on 18/10 passed while a 10-minute review window lost the
    page.
  - When 10 minutes pass with no CLI command on `<session>`,
    `resetWindowIdleTimer` calls `releaseLease(leaseKey, "idle timeout")`:
    - If another owned lease shares the window, it calls
      `chrome.tabs.remove(tabId)` (closes the tab).
    - If it is the only owned lease in the container group, it calls
      `chrome.tabs.update(tabId, { url: "about:blank", active: true })` to turn
      the tab into a reusable blank placeholder.
- **Does updating the extension (`v1.0.24` → `v1.0.26`) change this?**
  - **No.** Both versions on disk carry the exact same `IDLE_TIMEOUT_INTERACTIVE
    = 6e5` and `releaseLease` reset logic.
- **How to keep a filled form open so it never resets during user review:**
  1. **Pass `OPENCLI_BROWSER_IDLE_TIMEOUT=86400` (in seconds = 24 hours) on
     every `opencli` command (`cli.js:517`):**
     ```bash
     OPENCLI_BROWSER_IDLE_TIMEOUT=86400 opencli --profile <id> browser --session <session> ...
     ```
     The CLI forwards `idleTimeout` to the extension, which stores
     `idleTimeoutMs = cmd.idleTimeout * 1000` (24 hours) in `sessionOverrides`
     for that session.
  2. **Or bind a user-opened tab (`opencli browser --session <session> bind`):**
     In `background.js`, `if (session?.kind === "bound") return IDLE_TIMEOUT_NONE;`
     (`-1`) and `session.owned === false`. A bound user tab has no idle timer
     and is never redirected to `about:blank` when detached.

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
