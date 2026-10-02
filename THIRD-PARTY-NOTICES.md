# Third-party notices and runtime requirements

This repository is MIT licensed (see [LICENSE](LICENSE)). The items below are
either **not** covered by that licence, or are runtime requirements you must
provide yourself.

## 1. OriginLab Origin / OriginPro — commercial software, licensed separately

This plugin drives a **locally installed** copy of Origin through its COM
automation interface. It does **not** bundle, redistribute, or sublicense
Origin, and it contains no plotting kernel of its own. You must own a valid
Origin licence to use these tools. Without Origin installed, every formatting
tool has nothing to drive.

<https://www.originlab.com>

## 2. `originpro` / `OriginExt` — BSD licence, © OriginLab

Installed by the user (`pip install originpro`); **not** redistributed here.
The interpreter that drives Origin must be able to `import originpro`.

Note the version constraint: OriginLab currently publishes wheels up to
Python 3.9 only, which is why the launcher looks for a 3.9 environment.

## 3. The vendored figure-formatting scripts

`format_thesis_figures.py`, `format_composite.py` and `export_figures.py`
originate from the author's own PhD-thesis plotting toolchain. They are
released here by their copyright holder under the same MIT terms as the rest
of this repository (see [LICENSE](LICENSE)).

They are a **curated variant**: project-specific per-figure exception tables
and sample identifiers were removed before publication. `README-origin-batch-style.md`
is their engineering log and is kept for reference.
See the "Relationship to the upstream origin-batch-style toolkit" section of
[README.md](README.md) for what that means if you maintain your own copy.

## 4. Optional runtime dependencies of the vendored scripts

| Package | Licence | Used for |
|---|---|---|
| NumPy | BSD-3-Clause | render-measurement arithmetic |
| Pillow (PIL) | MIT-CMU | measuring rendered ink for axis-title placement and text clamping |
| openpyxl | MIT | reading `.xlsx` inputs (file-import paths) |
| matplotlib | PSF-based (BSD-compatible) | `origin_import_matplotlib` style figure import |
| python-pptx | MIT | `origin_export_pptx` slide assembly |

The scripts import NumPy and Pillow defensively: if either is missing, the
corresponding render-measurement self-checks are skipped rather than failing.
