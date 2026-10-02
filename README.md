# dsh-origin-thesis

**Format OriginLab Origin figures to a fixed house style from inside DeepSeek Harness.**
One command turns a whole `.opju` project into publication-ready figures: per-layer
grid layout, unified fonts and sizes, render-measured axis-title placement,
overlap resolution, panel labels, and 600-dpi export with corrected dpi metadata.

Built for a PhD-thesis workflow where dozens of Origin graphs must end up looking
identical, and rebuilt as a DSH bundle so the formatting runs from chat instead of
a command line.

```
you:  把这份项目按论文格式重排，保留我手摆的图例
      → thesis_format_project(project="...\MIL-101-S_graphs.opju",
                              profile="thesis", keep_legend_pos=true)
      → 23 figures reformatted, <name>_thesis.opju + <name>_thesis_figures/*.png
```

---

## Requirements

| | |
|---|---|
| **OS** | **Windows only.** Origin's automation interface is Windows COM; there is no macOS/Linux path. |
| **Origin** | A locally installed, licensed copy of **Origin / OriginPro 2018 or newer**. Tested on OriginPro 2026b and Origin 2021. **Not bundled with this plugin** — you must own an Origin licence. |
| **Python** | An interpreter with `originpro`, `numpy` and `Pillow` installed. ⚠️ `originpro` currently ships wheels **only up to Python 3.9**, so this is normally a 3.9 environment (e.g. a conda env named `origin`). |
| **DSH** | DeepSeek Harness with the `@deepseek-ai/dsh-mcp-client` plugin available (any DSH profile that can mount an MCP client). |

```bat
:: create the interpreter this plugin will drive Origin with
conda create -n origin python=3.9 -y
conda activate origin
pip install originpro numpy Pillow
```

> The plugin itself needs **no `mcp` package**: `thesis_mcp_server.py` implements the
> MCP stdio JSON-RPC loop directly, so it runs on Python 3.9 or 3.10 alike.

### Why there is a `.cmd` launcher

`cordis.patch.yml` names **[`start-thesis-mcp.cmd`](start-thesis-mcp.cmd)** rather than
`python.exe`. That is deliberate, and it is what makes the package location-independent.

DSH evaluates the `!!js` expressions in its patch files in a sandbox where
**`__dirname`, `__filename` and `require` do not exist** — only `process` is reliably
available. Measured, not assumed:

```
mcp-origin-thesis (@deepseek-ai/dsh-mcp-client): ReferenceError: __dirname is not defined
```

So the patch cannot compute its own package directory in JavaScript, and any
`!!js require('node:path').join(__dirname, …)` construction fails at startup. A Windows
batch file, by contrast, gets its own directory from the built-in `%~dp0` expansion with
no JavaScript involved. The launcher therefore:

1. locates `thesis_mcp_server.py` next to itself via `%~dp0`;
2. picks an interpreter — `DSH_THESIS_PYTHON`, else a conda env named `origin` in the
   usual places, else `python` on `PATH`;
3. forwards all arguments (`-u -X utf8` plus anything DSH passes) and runs the server.

The patch only has to name the launcher, so **the package can live anywhere** — the
default `~/dsh-vendor/dsh-origin-thesis` is just a convention. If you install it
elsewhere, edit the two `args`/`cwd` values in `cordis.patch.yml` accordingly.

---

## Install

### 1. Get the files

```bat
git clone https://github.com/<your-github-user>/dsh-origin-thesis.git "%USERPROFILE%\dsh-vendor\dsh-origin-thesis"
```

Everything needed at runtime — the server, the style profiles, **and the plotting
scripts** — lives in that one directory.

### 2. Wire it into a DSH profile

Clone into the location DSH expects (or point the profile at wherever you put it),
then link it into the profile the way any out-of-tree bundle is linked:

```bat
cd "%USERPROFILE%\.dsh\profiles\web"
pnpm add link:%USERPROFILE%\dsh-vendor\dsh-origin-thesis
```

and make sure the bundle is listed in that profile's `package.json`:

```json
"dsh": {
  "profile": {
    "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app",
                "dsh-origin-thesis"]
  }
}
```

The bundle's own `cordis.patch.yml` then registers the loader entry
(`mcp-origin-thesis` → `@deepseek-ai/dsh-mcp-client`, stdio) and resolves both the
server path and the interpreter automatically — **no absolute paths to edit**.

### 3. Restart DSH

The tools appear as `mcp__origin_thesis__*`. Check the wiring with:

```
thesis_batch_dir_info()
```

It reports which interpreter was used, whether `originpro` imports, and which
copy of the plotting scripts is active.

---

## Configuration

Everything is resolved at startup; nothing is hard-coded to a machine.

| Environment variable | Default | Meaning |
|---|---|---|
| `DSH_THESIS_PYTHON` | auto-detect | Interpreter that drives Origin. Detection order: this variable → `~/miniconda3/envs/origin/python.exe` → `~/anaconda3/envs/origin/python.exe` → `C:/ProgramData/miniconda3/envs/origin/python.exe` → `python` on `PATH`. |
| `DSH_THESIS_BATCH_DIR` | the package directory | Use **your own** `origin-batch-style` checkout instead of the scripts vendored in this package. |
| `DSH_THESIS_STYLES` | `styles.json` in the package directory | Use your own style profiles file. |

### Style profiles

`styles.json` is the single source of truth for the look of the figures. **Edit the
JSON to change the format — no Python changes needed.** Three profiles ship:

| Profile | For | Page | Tick / axis-title / legend | Line |
|---|---|---|---|---|
| `thesis` | Thesis figures, re-laid-out by layer count | 1 layer 9.8594×7.3999 cm (4:3); 2 layers 16×7.4; 3–4 16×13.2; 6 16×10.4; 8 16×8.6 | 9 / 10.5 bold / 9 pt | 1.0 pt |
| `composite` | Hand-assembled multi-panel plates | 17.5 cm wide, height from the original aspect (or re-gridded) | 6.5 / 7.5 / 6.5 pt | 0.75 pt |
| `manuscript` | Journal single figures (keeps the author's hand-placed legends) | same as `thesis` | same as `thesis` | same as `thesis` |

`manuscript` is `inherits: thesis` + one override (`move_legend: false`), so editing
`thesis` also affects it. Change a value at runtime with `thesis_style_set`
(dry-run first, then `dry_run=false`; a `.bak` is written automatically).

---

## Tools

**Offline (no Origin needed, instant):**

| Tool | Purpose |
|---|---|
| `thesis_styles_list` | List profiles and their key values |
| `thesis_style_show` | Show a full profile (with inheritance resolved) |
| `thesis_style_set` | Edit `styles.json` (dry-run by default) |
| `thesis_batch_dir_info` | Report resolved interpreter / scripts / styles (troubleshooting) |

**Formatting and export:**

| Tool | Purpose |
|---|---|
| `thesis_format_project` | Format **every graph in a project** by layer count; saves `*_thesis.opju` + `*_thesis_figures/*.png` |
| `thesis_format_composite` | Format a hand-assembled multi-panel plate; `regrid=true` re-spaces rows and trims the page |
| `thesis_batch` | Point it at many projects / a directory; returns a per-project report |
| `thesis_export_project` | Export only, no restyling (multiple formats, unified width, margin cropping) |
| `thesis_verify_project` | Read-only check of fonts / sizes / defects |

**Atomic, for free composition:**

| Tool | Purpose |
|---|---|
| `thesis_format_graph` | Format **one named graph** — the rest of the project is untouched |
| `thesis_apply_style_only` | Apply style/layout only: **no save, no export** |
| `thesis_export_open` | Export from the **already-open** session (no file reopen) |

These three are what let you interleave with fine-grained editing. The plugin shares
the Origin session with any other Origin tooling, so this works:

```
① thesis_apply_style_only(project=..., graph="Graph20", keep_open=true)   # ~21 s
② origin_edit_plot / origin_edit_axis / origin_edit_legend ...             # ms
③ thesis_export_open(graph="Graph20", out_path="D:\fig\Graph20.png")       # ~0.3 s
```

Use `keep_open=true` for chaining: `op.exit()` closes the project, and the next step
would then fail to find the graph.

The **original files are never modified** — formatting works on a copy in `%TEMP%`.

---

## Why the exported figures are physically sized correctly

Origin writes **300 dpi** into image headers no matter how many pixels you asked for,
so a 600-dpi figure dropped into Word is placed at twice its intended size. This
plugin patches the header after export (PNG `pHYs`, TIFF tags 282/283, JPEG JFIF,
BMP `PelsPerMeter`) without re-encoding, so the declared physical size equals the page
size set in Origin. Oversized output is also downscaled to the page width you meant
(2102 px for 8.9 cm at 600 dpi).

---

## How the formatting works (and what it deliberately preserves)

The heavy lifting lives in the vendored scripts, unchanged:

- **Layout by structure** — layers are classified (`main` / `inset` / `linked_inset` /
  overlay / `linked_ext`), then either gridded, stacked, or page-scaled. A vertical
  stack of spectra (XPS peak fits, MS comparisons) counts as **one** panel.
- **Axis titles are measured, not guessed** — `fit_axis_titles` writes a title,
  renders, measures the ink with Pillow, derives the anchor offset for that graph,
  and corrects over several rounds. Fixed offsets do not work: two graphs with the
  same frame and font size rendered their titles 0.28 cm apart.
- **Overlaps are resolved vertically only** — `clamp_texts` pulls annotations back
  inside the frame, then `separate_texts` pushes them apart **vertically**. Horizontal
  nudging would move a label off the peak it points at.
- **Inset layers only ever shrink** — tick label sizes inside a millimetre-scale
  inset are left alone; enlarging them fuses `7.2` and `7.0` into `7.27.0`.
- **Never rewritten**: legend strings (their own `|`-separated syntax with per-entry
  escapes — wrapping the whole string bolds entry 1 and appends a stray `)`), `\g()`
  Symbol-font regions (stripping the inner `\f:` wrapper turns `C` into Chi), data
  values, axis ranges, curve colours, and inserted image content.

`README-origin-batch-style.md` is the original engineers' log — several hundred lines
of measured failure modes (LabTalk silently ignoring writes, linked-layer stale
frames, expgraph's undocumented argument traps). Read it before changing the scripts.

---

## Limitations

- **Windows + a licensed Origin installation** are hard requirements; without Origin
  the tools have nothing to drive.
- **One graph takes ~20–30 s.** Each call starts the Origin COM session and runs the
  render-measure-correct loop. That step cannot be made fast; the payoff is that
  everything *after* it (`origin_edit_*`, `thesis_export_open`) is sub-second.
- **Origin is an exclusive resource.** Formatting uses the single-instance COM server,
  so do not edit figures by hand in Origin while a batch is running.
- **Python ≤ 3.9 for the interpreter** until OriginLab ships newer wheels.
- `PER_GRAPH_TWEAKS` ships **empty**. Per-figure exceptions are inherently
  project-specific (which label collided with which curve, how many millimetres a text
  box had to move), so the table is documented but not populated. Add your own entries
  in the shape shown next to it in `format_thesis_figures.py` — the outer key is the
  project file stem, because `Graph8` means different things in different projects.
  It is applied automatically when a project matches, and `no_tweaks=true` skips it.

---

## Repository layout

```
thesis_mcp_server.py          MCP server (stdlib only; no `mcp` package needed)
start-thesis-mcp.cmd          launcher: self-locates via %~dp0, picks the interpreter
styles.json                   style profiles — the file you edit to change the look
cordis.patch.yml              DSH loader entry (names the launcher; no toolchain paths)
index.js                      bundle entry artifact (no-op apply)
format_thesis_figures.py  ┐
format_composite.py       ├── vendored plotting scripts (replaceable via
export_figures.py         ┘    DSH_THESIS_BATCH_DIR)
README-thesis.md              internal reference: every tool, parameter and pitfall
README-origin-batch-style.md  the original scripts' engineering log
sync_to_vendor.ps1            copy this repo to the DSH runtime directory
```

## Licence

MIT — see [LICENSE](LICENSE). Origin itself is commercial software licensed
separately; `originpro` / `OriginExt` are BSD-licensed by OriginLab and installed by
you, not redistributed here.
