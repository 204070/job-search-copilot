# Tooling: OpenCLI Browser Bridge + desktop

Load when driving the browser (nearly every application session).

## Session pattern

- `opencli --profile <name> browser jobfit <cmd>` — reuse the `jobfit`
  session to keep tab/state alive.
- Two profiles connect (`g3pxjge8`, `6bfymbf4`) → always pass
  `--profile <name>`. `opencli doctor` FAILs on multi-profile even with
  `--profile` given (ignore that; commands work).

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

## Desktop (GNOME/Wayland)

- Cannot maximize or move the Chrome window programmatically: wmctrl absent,
  xdotool blind to Wayland windows, GNOME Shell Eval disabled
  (`gdbus … Eval` → `(false,'')`). CDP port 9222 exposes extension targets
  only (no pages) — no `Browser.setWindowBounds` either. OpenCLI `--window
  foreground` sets focus only. Ask the human to press `Super+Up`.
