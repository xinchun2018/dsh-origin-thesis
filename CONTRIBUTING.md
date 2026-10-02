# Contributing

Thanks for considering a contribution. This project wraps a plotting toolkit that has
been used on real manuscripts, so the bar for changing the formatting logic is
deliberately high — but the wrapper, the tool surface and the docs are all fair game.

## What is most welcome

- **Bug reports with a reproduction.** If a tool produced a wrong figure, say which
  tool, which profile, and paste the returned JSON (it carries `trace_id` and
  `error_code`). A tiny `.opju` that reproduces it is ideal; screenshots of the wrong
  output are almost as good.
- **Fixes in the wrapper** — `thesis_mcp_server.py`, `cordis.patch.yml`,
  `start-thesis-mcp.cmd`, `index.js` (error handling, path resolution, tool ergonomics,
  Windows launch robustness).
- **New style profiles** in `styles.json`.
- **Documentation**, especially limitations you hit and failure modes you diagnosed.
- **Platform coverage** if you can make something work where it currently does not
  (the COM automation itself is Windows-only, so that is bounded).

## What needs discussion first

Open an issue before working on these, so we do not duplicate effort or break existing
behaviour:

- Changes to the **layout / anchor-calibration / overlap-resolution logic** in the
  vendored scripts. Those numbers were measured against real figures, and the comments
  next to them record what went wrong when they were wrong. Explain what you measured
  and on what; "it looks cleaner" is not enough.
- Changes to **export** behaviour or the dpi-metadata patching.
- Anything that changes the **tool set** (new tools, renamed tools, changed arguments) —
  it is a public interface.

## Ground rules

1. **Python 3.9 compatibility is mandatory.** The interpreter that drives Origin is
   normally a 3.9 conda environment, because `originpro` ships wheels up to 3.9 only.
   Use `Optional[X]` instead of `X | None`, and `typing` constructs rather than PEP 604
   syntax.

2. **Never reintroduce `from __future__ import annotations` in the server.** Tool JSON
   Schemas are derived from live type annotations (see `_infer_json_type`); stringised
   annotations silently degrade every parameter to `"string"` and mislead the model about
   argument types. `tests/smoke.py` checks this ("parameter types survive introspection").

3. **Keep the patch free of machine-specific paths.** DSH evaluates `!!js` in a sandbox
   where `__dirname`, `__filename` and `require` do **not** exist (measured: `typeof
   __dirname` throws `ReferenceError`). Only `process` is reliable. That is why
   `cordis.patch.yml` names `start-thesis-mcp.cmd`, which self-locates with `%~dp0`.
   Do not replace it with a `require('node:path').join(__dirname, ...)` construction.

4. **The launcher must forward its arguments** (`%*` in the `.cmd`). Without it the
   server never receives DSH's stdio arguments and the tools silently never register.

5. **Write-then-read-back.** If you touch formatting code, follow the existing
   discipline: after writing a property, read it back and report `applied` /
   `applied_unverified` / `rejected`. Silently "successful" writes are the main failure
   mode of Origin's scripting interfaces.

6. **Do not commit** `.opju` files, exported figures, or contents of `work/` — see
   `.gitignore`.

## Testing

Run the smoke test before opening a pull request. It exercises the exact path DSH uses
and needs no DSH session:

```powershell
python tests\smoke.py                                   # 14 checks, incl. MCP handshake
python tests\smoke.py --skip-handshake                  # if you cannot spawn processes
python tests\smoke.py --python C:\path\to\python.exe     # a specific interpreter
```

It verifies: the launcher and server are adjacent, the interpreter can `import
originpro`, `--info` is self-consistent (scripts found, profiles load), `--list-tools`
registers exactly the expected 12 tools with typed object schemas, and a real
`initialize -> tools/list -> tools/call` round trip over stdio.

**If your change touches formatting, also run a real figure through it** and report what
you saw:

```
thesis_format_graph(project="...\some_project.opju", graph="Graph1",
                    profile="thesis", out_dir="...\out")
```

Expected: `ok: true`, `verify_issues: []`, a saved `.opju`, an exported PNG, and
`origin_release: exited` (unless you passed `keep_open=true`). Then re-open the saved
product and check it read-only with `thesis_verify_project` — it should come back
`clean: true`. The product, not your in-memory session, is the thing that has to be
right.

## About the vendored scripts

`format_thesis_figures.py`, `format_composite.py` and `export_figures.py` come from the
author's own `origin-batch-style` toolkit and are shipped here as a curated variant:

- `PER_GRAPH_TWEAKS` is **empty** on purpose. Per-figure exceptions are project-specific
  (which annotation collided with which curve, how far a text box had to move) and would
  be meaningless — or harmful — in someone else's project. The grouping scheme is
  documented next to the empty table; add your own entries there rather than in an issue.
- Comments were genericized: sample identifiers, manuscript filenames and figure numbers
  were replaced, while the technical insight each comment carried was kept verbatim.
  Please keep it that way in pull requests — describe the pattern, not your sample.

`README-origin-batch-style.md` is the original engineering log and is intentionally left
in its raw form. It is the best available explanation of *why* the tricky code is
tricky; read it before "simplifying" anything.

## Releasing

Maintainers:

1. Bump the version in both `package.json` and `thesis_mcp_server.py`
   (`_SERVER_VERSION`), and add a `CHANGELOG.md` entry.
2. `python tests\smoke.py` — must be all-pass.
3. `powershell -ExecutionPolicy Bypass -File sync_to_vendor.ps1` to refresh the DSH
   runtime directory (the profile links to it).
4. Commit, push to `main`.

GitHub's licence detection requires a **bare, unmodified MIT text** in `LICENSE`; the
third-party notes live in `THIRD-PARTY-NOTICES.md`. Do not merge them back.
