#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh-origin-thesis — 论文插图格式 MCP 服务器（DSH 原生工具）。

设计目标
--------
把 origin-batch-style/ 里**已经验证过的**格式化逻辑暴露成 DSH 工具，供聊天中直接
调用，**不重写、不复制**那些逻辑：
  · format_thesis_figures.format_graph / verify_graph / font_index    (论文 4:3 版式)
  · format_composite.format_composite                                  (拼版大图)
  · export_figures.export_project                                      (只导出)
  · styles.json                                                        (共享样式档)

依赖与协议
----------
· 只用标准库 + 被复用脚本自身的依赖（originpro）。**不需要 mcp 包**——
  协议实现照 origin_mcp_server.py 的 _sync_stdio_server()：纯同步 stdio
  JSON-RPC 循环，不依赖 anyio/事件循环/回环 socket。
· 因此本服务器在 py3.9（origin 环境）与 py3.10 下都能跑；格式化仍必须用
  py3.9 origin 环境，因为 originpro 只发 ≤3.9。

能力边界（如实声明，来自 README 实测）
------------------------------------
· 完整保留：页面尺寸/图层几何/字体字号/轴属性/曲线样式/面板标签/导出+dpi修正。
· 依赖像素量测的部分（fit_axis_titles 锚点标定、clamp_texts/separate_texts
  标注互推）由被复用的原脚本**原样执行**，因此同样保留——这正是不重写的价值。
"""
import glob as _glob
import importlib.util
import json
import os
import sys
import traceback
from typing import Optional

# 注意：这里刻意不用 `from __future__ import annotations` —— 注解必须保持真实类型
# 对象，协议层的 _infer_json_type 才能把它们映射成正确的 JSON Schema 类型
# （否则 int/bool/float 全退化成 "string"，误导模型传参）。

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_PROTO_FALLBACK = "2024-11-05"
_SERVER_NAME = "origin_thesis"
_SERVER_VERSION = "1.0.0"

# 本文件所在目录（styles.json 与随包脚本的定位基准）
_HERE = os.path.dirname(os.path.abspath(__file__))

# 启动环境取证（排障用）：设了 DSH_THESIS_BOOT_LOG 时，每次启动把这个进程
# 看到的关键路径追加成一行 JSON —— 用于诊断"服务器到底从哪个目录、用哪个
# 解释器被拉起来的"。默认关闭，不产生任何副作用。
_BOOT_LOG = os.environ.get("DSH_THESIS_BOOT_LOG")


def _write_boot_log() -> None:
    if not _BOOT_LOG:
        return
    rec = {"argv": sys.argv[:4], "python": sys.executable,
           "python_version": sys.version.split()[0], "cwd": os.getcwd(),
           "here": _HERE}
    try:
        rec["batch_dir"] = _batch_dir()
        rec["styles_path"] = _styles_path()
        rec["originpro"] = True
        import originpro  # noqa: F401
    except Exception as exc:
        rec["probe_error"] = str(exc)
        rec.setdefault("originpro", False)
    try:
        with open(_BOOT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

# 随包脚本的文件名（判定一个目录是不是"脚本目录"用）
_SCRIPT_STEMS = ("format_thesis_figures", "format_composite", "export_figures")


def _looks_like_script_dir(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(
        os.path.join(path, "format_thesis_figures.py"))


# 脚本目录候选，按优先级：
#   1. DSH_THESIS_BATCH_DIR —— 想用你自己的 origin-batch-style/ 时设它
#   2. 本包目录            —— 随包 vendored 副本（开箱可用）
#   3. 历史默认位置        —— 仅作便利，装到别处时不存在也无所谓
_BATCH_DIR_CANDIDATES = [
    os.environ.get("DSH_THESIS_BATCH_DIR"),
    _HERE,
    os.path.join(os.path.expanduser("~"), "tu", "origin-batch-style"),
    os.path.join(os.path.expanduser("~"), "origin-batch-style"),
]


# --------------------------------------------------------------------------
# 资源定位与惰性加载
# --------------------------------------------------------------------------
def _styles_path() -> str:
    env = os.environ.get("DSH_THESIS_STYLES")
    if env and os.path.isfile(env):
        return env
    # 本包目录优先：随包分发的样式档是真源，不被外部目录的旧副本盖掉。
    for c in (os.path.join(_HERE, "styles.json"),
              os.path.join(_batch_dir() or "", "styles.json")):
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "找不到 styles.json；设置 DSH_THESIS_STYLES 指向它，或把它放在本服务器同目录。")


def _batch_dir() -> Optional[str]:
    for c in _BATCH_DIR_CANDIDATES:
        if _looks_like_script_dir(c):
            return c
    return None


_MOD_CACHE: dict = {}


def _load_module(stem: str):
    """按文件路径加载用户脚本模块（不要求它在 sys.path 上）。"""
    if stem in _MOD_CACHE:
        return _MOD_CACHE[stem]
    base = _batch_dir()
    if not base:
        raise FileNotFoundError(
            "找不到 origin-batch-style 目录；设置 DSH_THESIS_BATCH_DIR 指向它。")
    path = os.path.join(base, f"{stem}.py")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if base not in sys.path:          # 脚本之间互相 import（format_composite 依赖前者）
        sys.path.insert(0, base)
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[stem] = mod
    spec.loader.exec_module(mod)     # 注意：import originpro 不会启动 Origin
    _MOD_CACHE[stem] = mod
    return mod


def load_styles() -> dict:
    with open(_styles_path(), encoding="utf-8") as fh:
        return json.load(fh)


def resolve_profile(name: str, styles: Optional[dict] = None) -> dict:
    """解析配置档，处理 inherits/overrides（manuscript 继承 thesis）。"""
    styles = styles or load_styles()
    profs = styles["profiles"]
    if name not in profs:
        raise KeyError(f"未知配置档 {name!r}；可用：{', '.join(profs)}")
    prof = profs[name]
    if "inherits" not in prof:
        return prof
    base = resolve_profile(prof["inherits"], styles)
    merged = json.loads(json.dumps(base))          # 深拷贝
    ov = prof.get("overrides", {})
    for k, v in ov.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    merged["label"] = prof.get("label", merged.get("label"))
    merged["used_by"] = prof.get("used_by", merged.get("used_by"))
    return merged


def _flatten_style(prof: dict) -> dict:
    """把 profile 里的 style 与 composite 的 STYLE 键合并成一份扁平字典。

    两个脚本的 STYLE 键名不同（thesis 用 axis_title_pt/tick_pt，composite 用
    title_pt/tick_pt），这里统一映射到各自模块实际使用的键名。
    """
    st = dict(prof.get("style", {}))
    return st


def _apply_style_to_module(mod, prof: dict, font: Optional[str] = None,
                           keep_legend_pos: bool = False) -> dict:
    """把 styles.json 的值写进被复用模块的 STYLE / LAYOUTS（它们是模块级可变字典）。

    这是"共享样式档"的落地方式：脚本顶部的常量成为默认值，styles.json 成为真源。
    只覆盖脚本确实读取的键，未知键忽略并报告。
    """
    st = _flatten_style(prof)
    applied, ignored = [], []
    target = getattr(mod, "STYLE", None)
    if not isinstance(target, dict):
        return {"applied": applied, "ignored": list(st)}

    # styles.json 键 -> 脚本 STYLE 键（两套脚本命名不同，按存在性择一）
    alias = {
        "axis_title_pt": ("axis_title_pt", "title_pt"),
        "tick_pt": ("tick_pt",),
        "panel_pt": ("panel_pt",),
        "annot_pt": ("annot_pt",),
        "legend_pt": ("legend_pt",),
        "series_pt": ("series_pt",),
        "line_pt": ("line_pt",),
        "symbol_pt": ("symbol_pt",),
        "axis_thickness_pt": ("axis_thickness", "axis_th"),
        "tick_thickness_pt": ("tick_thickness", "tick_th"),
        "tick_length_pt": ("tick_length", "tick_len"),
        "export_dpi": ("export_dpi", "dpi"),
        "panel_pad_px": ("panel_pad_px",),
        "rotate_annot_min": ("rotate_annot_min",),
        "row_gap_cm": ("row_gap_cm",),
        "page_w_cm": ("page_w_cm",),
        "axis_title_bold": ("axis_title_bold",),
        "panel_labels": ("panel_labels",),
    }
    for src, dsts in alias.items():
        if src not in st:
            continue
        for d in dsts:
            if d in target:
                target[d] = st[src]
                applied.append({"key": d, "value": st[src]})
                break
        else:
            ignored.append({src: st[src]})

    if font:
        if "font" in target:
            target["font"] = font
            applied.append({"key": "font", "value": font})
    if "move_legend" in target:
        target["move_legend"] = not keep_legend_pos
        applied.append({"key": "move_legend", "value": not keep_legend_pos})

    # 版面表（thesis）：styles.json 用 page_cm/margins_cm，脚本用 page/margins（元组）
    lay = prof.get("layouts")
    if lay and isinstance(getattr(mod, "LAYOUTS", None), dict):
        for k, v in lay.items():
            n = int(k)
            entry = mod.LAYOUTS.setdefault(n, {})
            entry["rows"], entry["cols"] = v["rows"], v["cols"]
            entry["page"] = tuple(v["page_cm"])
            if "margins_cm" in v:
                entry["margins"] = dict(v["margins_cm"])
            applied.append({"key": f"LAYOUTS[{n}]",
                            "value": {"page": v["page_cm"], "grid": f"{v['rows']}x{v['cols']}"}})
    cm = prof.get("cell_margin_cm")
    if cm and isinstance(getattr(mod, "CELL_MARGIN", None), dict):
        mod.CELL_MARGIN.update(cm)
        applied.append({"key": "CELL_MARGIN", "value": cm})

    return {"applied": applied, "ignored": ignored}


def _snapshot_module(mod) -> dict:
    """记录脚本模块改前的 STYLE/LAYOUTS/CELL_MARGIN，便于本轮结束后还原。"""
    snap = {}
    for k in ("STYLE", "LAYOUTS", "CELL_MARGIN"):
        v = getattr(mod, k, None)
        if v is not None:
            snap[k] = json.loads(json.dumps(v, default=list))
    return snap


def _restore_module(mod, snap: dict) -> None:
    for k, v in snap.items():
        cur = getattr(mod, k, None)
        if isinstance(cur, dict):
            cur.clear()
            cur.update(v)
        else:
            setattr(mod, k, v)


# --------------------------------------------------------------------------
# 工具：离线（不碰 Origin）
# --------------------------------------------------------------------------
def thesis_styles_list() -> dict:
    """列出所有论文图格式配置档及其关键参数（离线秒回，不连接 Origin）。

    返回每个配置档的用途、来源脚本、页面尺寸/字号/线宽等关键值，便于选择
    与核对。完整原始值用 thesis_style_show 查看。
    """
    try:
        styles = load_styles()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "STYLES_NOT_FOUND"}
    out = []
    for name in styles["profiles"]:
        p = resolve_profile(name, styles)
        st = _flatten_style(p)
        out.append({
            "profile": name,
            "label": p.get("label"),
            "used_by": p.get("used_by"),
            "output_suffix": p.get("output_suffix"),
            "key_style": {
                k: st.get(k) for k in
                ("font", "tick_pt", "axis_title_pt", "title_pt", "legend_pt",
                 "annot_pt", "panel_pt", "line_pt", "symbol_pt",
                 "axis_thickness_pt", "export_dpi")
                if k in st
            },
            "layouts": {k: {"page_cm": v["page_cm"], "grid": f"{v['rows']}x{v['cols']}"}
                        for k, v in (p.get("layouts") or {}).items()},
        })
    return {"ok": True, "styles_path": _styles_path(), "batch_dir": _batch_dir(),
            "profiles": out,
            "note": "改 styles.json 即可调整格式，无需改 Python；加载时会即时生效。"}


def thesis_style_show(profile: str, section: str = "all") -> dict:
    """查看某个配置档的完整定义。

    Args:
        profile: 配置档名（thesis / composite / manuscript）。
        section: all | style | layouts | axis | invariants —— 只看某一部分。
    """
    try:
        styles = load_styles()
        p = resolve_profile(profile, styles)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "PROFILE_NOT_FOUND"}
    if section == "all":
        body = p
    else:
        body = {section: p.get(section)}
    return {"ok": True, "profile": profile, "section": section, "body": body,
            "invariants": styles.get("invariants"),
            "known_pitfalls": styles.get("known_pitfalls")}


def thesis_style_set(profile: str, changes: dict, dry_run: bool = True) -> dict:
    """微调配置档里的样式值并写回 styles.json（幂等；默认只预演不落盘）。

    Args:
        profile: 要改的配置档名。
        changes: 要改的键值，如 {"tick_pt": 8.5, "line_pt": 1.2}；
            支持点号路径改嵌套项，如 {"axis.title_gap_cm.x": 0.7}。
        dry_run: True 只返回将要发生的改动；False 才写盘（写前自动备份为 .bak）。
    """
    try:
        styles = load_styles()
        profs = styles["profiles"]
        if profile not in profs:
            return {"ok": False, "error": f"未知配置档 {profile!r}",
                    "error_code": "PROFILE_NOT_FOUND",
                    "available": list(profs)}
        target = profs[profile]
        pending = []
        for path, val in (changes or {}).items():
            node = target
            keys = path.split(".")
            for k in keys[:-1]:
                if k == "style" and "style" not in node:
                    node["style"] = {}
                node = node.setdefault(k, {})
                if not isinstance(node, dict):
                    break
            if isinstance(node, dict):
                old = node.get(keys[-1], "<unset>")
                node[keys[-1]] = val
                pending.append({"path": path, "old": old, "new": val})
            else:
                return {"ok": False, "error": f"路径不可写：{path}",
                        "error_code": "BAD_PATH"}
        if dry_run:
            return {"ok": True, "dry_run": True, "profile": profile,
                    "changes": pending,
                    "note": "预演。传 dry_run=false 才写入 styles.json。"}
        path = _styles_path()
        bak = path + ".bak"
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        with open(bak, "w", encoding="utf-8") as fh:
            fh.write(raw)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(styles, fh, ensure_ascii=False, indent=2)
        # 读回校验
        back = json.load(open(path, encoding="utf-8"))
        node = back["profiles"][profile]
        verified = []
        for item in pending:
            cur = node
            for k in item["path"].split("."):
                cur = cur.get(k) if isinstance(cur, dict) else None
            verified.append({"path": item["path"], "written": item["new"],
                             "readback": cur, "ok": cur == item["new"]})
        return {"ok": all(v["ok"] for v in verified), "dry_run": False,
                "profile": profile, "changes": pending, "verified": verified,
                "backup": bak, "styles_path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "STYLE_SET_FAILED",
                "traceback": traceback.format_exc()}


def thesis_batch_dir_info() -> dict:
    """报告服务器解析到的样式档与用户脚本目录（排障用，离线）。"""
    info = {"ok": True, "here": _HERE, "styles_path": None, "batch_dir": _batch_dir(),
            "env": {k: os.environ.get(k) for k in
                    ("DSH_THESIS_STYLES", "DSH_THESIS_BATCH_DIR", "DSH_THESIS_PYTHON")}}
    try:
        info["styles_path"] = _styles_path()
        info["profiles"] = list(load_styles()["profiles"])
    except Exception as exc:
        info["ok"] = False
        info["styles_error"] = str(exc)
    scripts = {}
    for stem in _SCRIPT_STEMS:
        p = os.path.join(_batch_dir() or "", f"{stem}.py")
        scripts[stem] = {"path": p, "exists": os.path.isfile(p)}
    info["scripts"] = scripts
    try:
        import originpro  # noqa: F401
        info["originpro"] = True
        info["python"] = sys.version.split()[0]
    except Exception as exc:
        info["originpro"] = False
        info["originpro_error"] = str(exc)
    return info


# --------------------------------------------------------------------------
# 工具：格式化 / 导出（需要 originpro 与 Origin）
# --------------------------------------------------------------------------
def _num(v, default=0):
    """把 ltf 的返回值安全转成数字。

    op.lt_float 失败时返回 float('nan')（不是 None），所以 `or 0` 拦不住 NaN，
    直接 int(nan) 会抛 ValueError。这里统一兜住 None / NaN / 非数值。
    """
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if f != f else f          # f != f 即 NaN


def _layer_count(mod, graph_name: str) -> int:
    """按被复用脚本自己的方式读图层数：先激活窗口，再单独读 page.nlayers。"""
    mod.lt(f"win -a {graph_name};")
    return int(_num(mod.ltf("page.nlayers"), 0))


def _expand_inputs(items, recursive: bool) -> list:
    """把文件/目录/通配符展开成 .opju 列表（不依赖被复用脚本的内部实现）。"""
    out = []
    for it in items or []:
        if os.path.isdir(it):
            pat = os.path.join(it, "**", "*.opj*") if recursive else os.path.join(it, "*.opj*")
            out += _glob.glob(pat, recursive=recursive)
        else:
            out += _glob.glob(it) or [it]
    seen, uniq = set(), []
    for p in out:
        ap = os.path.abspath(p)
        if os.path.isfile(ap) and ap.lower() not in seen:
            seen.add(ap.lower())
            uniq.append(ap)
    return uniq


def _patch_figure_dpi(paths: list, dpi: float) -> list:
    """把导出的图片 dpi 元数据改成真实 dpi（复用 export_figures.fix_dpi）。"""
    try:
        ef = _load_module("export_figures")
        fn = getattr(ef, "fix_dpi", None)
    except Exception as exc:
        return [{"ok": False, "error": f"无法加载 export_figures: {exc}"}]
    if not callable(fn):
        return [{"ok": False, "error": "export_figures.fix_dpi 不存在"}]
    res = []
    for p in paths:
        ext = os.path.splitext(p)[1].lstrip(".").lower()
        try:
            res.append({"file": p, "fixed": bool(fn(p, ext, dpi))})
        except Exception as exc:
            res.append({"file": p, "fixed": False, "error": str(exc)})
    return res


def _format_composite_impl(src: str, graph_name: str, out_dir: str, prof: dict,
                           dpi: int, regrid: bool, page_w: float,
                           row_gap: float, no_panel_labels: bool,
                           show_origin: bool) -> dict:
    """手工拼版大图的格式化：原样复用 format_composite.py 的编排。

    版面不动、整页等比缩到印刷宽度，再按角色统一字号/字体/线宽、补面板标签、
    两轮"渲染→收边→互推"。这些步骤依赖像素量测（PIL），**必须复用原脚本**。
    """
    import os as _os
    import shutil
    import tempfile

    try:
        import originpro as op
    except Exception as exc:
        return {"ok": False, "error": f"需要 originpro: {exc}", "error_code": "NO_ORIGINPRO"}
    try:
        cm = _load_module("format_composite")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED",
                "traceback": traceback.format_exc()}

    snap = _snapshot_module(cm)
    style_report = _apply_style_to_module(cm, prof)
    if page_w:
        cm.STYLE["page_w_cm"] = float(page_w)
    cm.STYLE["panel_labels"] = not no_panel_labels
    cm.STYLE["row_gap_cm"] = float(row_gap)
    cm.STYLE["dpi"] = int(dpi)

    stem = _os.path.splitext(_os.path.basename(src))[0]
    suffix = prof.get("output_suffix", "_pub")
    out_opju = _os.path.join(out_dir, f"{stem}{suffix}.opju")
    out_png = _os.path.join(out_dir, f"{stem}{suffix}.png")

    tmp = tempfile.mkdtemp(prefix="thesis_comp_")
    work = _os.path.join(tmp, "work.opju")
    steps, dpi_fix = [], []
    origin_before = _origin_was_running()
    try:
        shutil.copy2(src, work)
        op.set_show(bool(show_origin))
        if not op.open(work):
            return {"ok": False, "error": f"Origin 打开失败: {work}",
                    "error_code": "OPEN_FAILED"}
        graphs = op.graph_list("p")
        if not graphs:
            return {"ok": False, "error": "项目里没有图页", "error_code": "NO_GRAPH"}
        g = next((x for x in graphs if x.name == graph_name), graphs[0]) \
            if graph_name else graphs[0]
        # 在 Origin 还活着时把图名存成字符串：finally 里的 release 会断开 COM，
        # 之后再读 g.name 会报"对象没有连接到服务器"。
        graph_name_str = g.name
        cm.lt(f"win -a {graph_name_str};")
        nlayers = int(_num(cm.ltf("page.nlayers"), 0))
        fidx = cm.font_index(cm.STYLE["font"])
        infos = cm.read_layout(nlayers)

        if regrid:
            pw, ph = cm.regrid_page(infos, cm.STYLE["page_w_cm"],
                                    cm.STYLE["row_gap_cm"], cm.STYLE.get("bottom_cm"))
        else:
            pw, ph = cm.rescale_page(infos, cm.STYLE["page_w_cm"])

        layers_report = []
        for r in infos:
            cm.lt(f"page.active={r['i']};")
            cm.format_axes(r["kind"], fidx)
            thinned = None
            if r["kind"] == "main":
                cm.lt("layer.unit = 3;")
                thinned = cm.thin_x_labels(_num(cm.ltf("layer.width"), 0),
                                           cm.STYLE["tick_pt"])
            widths = [] if r["kind"] == "inset" else cm.format_plots(g[r["i"] - 1])
            texts, n_annot = cm.format_texts(g[r["i"] - 1], fidx)
            layers_report.append({"layer": r["i"], "kind": r["kind"],
                                  "n_plots": len(widths), "n_texts": len(texts),
                                  "x_labels_thinned": thinned,
                                  "annot_rotated": n_annot})

        dummy = _os.path.join(tempfile.gettempdir(), "_origin_comp_dummy.png")
        page_px = (_num(cm.ltf("page.width"), 0), _num(cm.ltf("page.height"), 0))
        labels = []
        if cm.STYLE["panel_labels"]:
            labels = cm.add_panel_labels(g, infos, page_px, fidx)

        for rnd in range(2):
            try:
                g.save_fig(dummy, type="png", width=900)
            except Exception as exc:
                steps.append({"round": rnd + 1, "render_warn": str(exc)})
            n_moved = 0
            resx = _num(cm.ltf("page.resx"), 600.0) or 600.0
            for r in infos:
                box = cm.frame_px(r, infos, page_px)
                if box is None:
                    continue
                cm.lt(f"page.active={r['i']};")
                moved = cm.clamp_texts(g[r["i"] - 1], box,
                                       pad_px=0.05 / 2.54 * resx,
                                       legend_pad_px=0.12 / 2.54 * resx)
                moved += cm.separate_texts(g[r["i"] - 1], box,
                                           gap_px=0.03 / 2.54 * resx)
                n_moved += len(moved)
            steps.append({"round": rnd + 1, "texts_moved": n_moved})
            if not n_moved:
                break
        try:
            _os.remove(dummy)
        except OSError:
            pass

        op.save(out_opju)
        px = int(round(pw / 2.54 * cm.STYLE["dpi"]))
        g.save_fig(out_png, type="png", width=px)
        dpi_fix = _patch_figure_dpi([out_png], cm.STYLE["dpi"]) \
            if load_styles().get("export", {}).get("fix_dpi_metadata", True) else []
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        release_note = _release_origin(op, started=True,
                                       origin_running_before=origin_before)
        _restore_module(cm, snap)

    return {"ok": True, "profile": prof.get("label"), "pipeline": "format_composite",
            "source": src, "graph": graph_name_str,
            "n_layers": len(infos), "regrid": regrid,
            "page_cm": [round(pw, 3), round(ph, 3)],
            "style_applied": style_report["applied"],
            "style_ignored": style_report["ignored"],
            "layers": layers_report, "panel_labels": labels,
            "settle_rounds": steps, "project_out": out_opju,
            "png": out_png, "px_width": px, "dpi": cm.STYLE["dpi"],
            "dpi_metadata_fixed": dpi_fix, "errors": [],
            "origin_release": release_note,
            "note": "原文件未改动；版面未重排（仅缩放+统一样式+收边）。"}


def thesis_format_composite(project: str, graph: str = "", out_dir: str = "",
                            dpi: int = 0, regrid: bool = False,
                            page_w: float = 0, row_gap: float = 0,
                            no_panel_labels: bool = False,
                            show_origin: bool = False) -> dict:
    """按 composite 配置档格式化手工拼好的多面板大图（另存 _pub.opju + PNG）。

    对应你原来的 `python format_composite.py --project ...`，编排逻辑原样复用
    format_composite.py。默认只处理项目里的第一张图（大图项目通常只有一张）。

    Args:
        project: 输入 .opju / .opj。
        graph: 图短名；留空用第一张。
        out_dir: 输出目录；留空与输入同目录。
        dpi: 导出 dpi；0 用配置档的 600。
        regrid: 把面板重排成行距均匀的网格并裁掉页面底部空白
            （页面按 3 行开好只放了 2 行时用）。
        page_w: 最终印刷宽度 cm；0 用配置档的 17.5。
        row_gap: --regrid 的行距（最终印刷 cm）；0 用配置档的 1.21。
        no_panel_labels: 不添加 (a)(b)(c) 面板标签。
        show_origin: 显示 Origin 界面。
    """
    src = os.path.abspath(project)
    if not os.path.isfile(src):
        return {"ok": False, "error": f"文件不存在: {src}", "error_code": "NOT_FOUND"}
    try:
        styles = load_styles()
        prof = resolve_profile("composite", styles)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED"}
    st = _flatten_style(prof)
    return _format_composite_impl(
        src=src, graph_name=graph,
        out_dir=os.path.abspath(out_dir) if out_dir else os.path.dirname(src),
        prof=prof, dpi=int(dpi or st.get("export_dpi", 600)),
        regrid=regrid, page_w=page_w or st.get("page_w_cm", 17.5),
        row_gap=row_gap or st.get("row_gap_cm", 1.21),
        no_panel_labels=no_panel_labels, show_origin=show_origin)


def _resolve_graph(op, graph_name: str):
    """按短名或长名在**当前已打开**的项目里找图；找不到返回 (None, 可用清单)。

    用途：让"只改样式"能与 origin_* 编辑工具在同一 Origin 会话里接力——
    只要那张图已经开着，就不必再从文件打开（也避免把用户手改的成果覆盖掉）。
    """
    try:
        graphs = list(op.graph_list("p"))
    except Exception:
        return None, []
    if not graph_name:
        return (graphs[0] if graphs else None), [g.name for g in graphs]
    for g in graphs:
        if g.name == graph_name or getattr(g, "lname", None) == graph_name:
            return g, [x.name for x in graphs]
    return None, [g.name for g in graphs]


def _open_project_preferring_session(op, graph_name: str, src: Optional[str],
                                     readonly: bool = False):
    """优先用当前已打开的图；否则从文件打开。返回 (gpage, 来源说明, 可用清单)。"""
    g, avail = _resolve_graph(op, graph_name)
    if g is not None:
        return g, "current_session", avail
    if not src:
        return None, "not_found", avail
    ok = op.open(src, readonly=readonly) if readonly else op.open(src)
    if not ok:
        return None, "open_failed", avail
    g, avail = _resolve_graph(op, graph_name)
    return g, "opened_file", avail


def _release_origin(op, started: bool, origin_running_before: bool,
                    keep_open: bool = False) -> Optional[str]:
    """释放自动化连接（对齐被复用脚本末尾的 op.exit()）。

    只在本轮**是自己拉起** Origin 时退出，避免把用户手动开着的 Origin 关掉：
    · 本来就有 Origin 在跑 → 只断开 COM，不动它；
    · 本轮新拉起的 → op.exit() 干净退出（否则每轮都会留僵尸进程，
      实测累积过 10 个 Origin64.exe）；
    · keep_open=True → 不退出。**接力场景必须用它**：op.exit() 会顺带关掉
      当前项目，"套样式 → 微调 → 导出"的链条就断了（实测 thesis_export_open
      随即找不到那张图）。代价是 Origin 会留在后台。
    """
    try:
        if keep_open or origin_running_before:
            return "left_running"
        if started:
            op.exit()
            return "exited"
        return "left_running"
    except Exception as exc:
        return f"release_failed: {exc}"


def _origin_was_running() -> bool:
    try:
        return bool(_origin_procs())
    except Exception:
        return False


def _origin_procs() -> list:
    """List live Origin64.exe pids without importing psutil."""
    import subprocess
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Origin64.exe", "/NH", "/FO", "CSV"],
        capture_output=True, text=True, timeout=20)
    pids = []
    for line in (out.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == "origin64.exe":
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def _format_graph_impl(op, g, mod, fidx: int, tweaks: dict,
                       export_png: bool, dpi: int, fig_dir: str,
                       save_to: str) -> dict:
    """把单张图跑一遍 format_graph + verify +（可选）导出/保存。

    这是 thesis_format_project 与 thesis_format_graph 共用的最小执行单元。
    """
    info = mod.format_graph(g, fidx)
    if info.get("name") in tweaks:
        tweaks[info["name"]](g)
        info["tweak"] = True

    issues = []
    try:
        issues = mod.verify_graph(g, fidx, info.get("small"))
    except Exception as exc:
        issues = [f"verify {info['name']} 失败: {exc}"]

    saved, exported, dpi_fix = None, None, []
    if save_to:
        op.save(save_to)
        saved = save_to if os.path.isfile(save_to) else None
    if export_png:
        try:
            px = int(round(info["page_cm"][0] / 2.54 * dpi))
            name = info["name"]
            png = os.path.join(fig_dir, f"{name}.png")
            op.find_graph(name).save_fig(png, type="png", width=px)
            exported = png
            if load_styles().get("export", {}).get("fix_dpi_metadata", True):
                dpi_fix = _patch_figure_dpi([png], dpi)
        except Exception as exc:
            issues.append(f"导出失败: {exc}")

    return {"graph": info["name"], "layers": info["nlayers"],
            "layout": info.get("layout"), "page_cm": info.get("page_cm"),
            "panels_removed": info.get("panels_removed"),
            "dual_y": info.get("dual_y"), "tweak": bool(info.get("tweak")),
            "verify_issues": issues, "saved": saved,
            "exported": exported, "dpi_metadata_fixed": dpi_fix}


def thesis_format_graph(project: str, graph: str, profile: str = "thesis",
                        out_dir: str = "", dpi: int = 0, save: bool = True,
                        export_png: bool = True, keep_legend_pos: bool = False,
                        no_tweaks: bool = False, use_open_session: bool = False,
                        keep_open: bool = False,
                        show_origin: bool = False) -> dict:
    """只格式化**指定的一张图**（原子操作，不遍历整个项目）。

    补上"项目里只想重排某一张图"的能力：整份项目里其余图完全不碰。

    Args:
        project: 输入 .opju / .opj（原文件不被修改）。
        graph: 图短名或长名（用 origin_list_pages 或 origin_list_graphs 查）。
        profile: 配置档（thesis / manuscript）。
        out_dir: 输出目录；留空与输入同目录。
        dpi: 导出 dpi；0 用配置档值。
        save: 是否把结果另存为 <名><后缀>.opju。
        export_png: 是否导出该图的 PNG。
        keep_legend_pos: 不把图例挪到框架右上角。
        no_tweaks: 不套用 PER_GRAPH_TWEAKS 逐图微调。
        use_open_session: True 时先在当前已打开的 Origin 项目里找这张图
            （与 origin_* 编辑工具接力的场景），找不到再回退到打开 project。
        keep_open: 结束后**不退出 Origin**，保住当前项目，供后续
            origin_edit_* / thesis_export_open 接力。接力场景请设 True，
            否则 op.exit() 会关掉项目，链条断掉。代价是 Origin 留在后台。
        show_origin: 显示 Origin 界面。
    """
    src = os.path.abspath(project) if project else ""
    if src and not os.path.isfile(src):
        return {"ok": False, "error": f"文件不存在: {src}", "error_code": "NOT_FOUND"}
    try:
        import originpro as op
        styles = load_styles()
        prof = resolve_profile(profile, styles)
        mod = _load_module("format_thesis_figures")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED",
                "traceback": traceback.format_exc()}

    dpi = int(dpi or _flatten_style(prof).get("export_dpi", 600))
    out_dir = os.path.abspath(out_dir) if out_dir else (
        os.path.dirname(src) or os.getcwd())
    stem = os.path.splitext(os.path.basename(src))[0] if src else "session"
    suffix = prof.get("output_suffix", "_thesis")
    # 避免后缀叠加：对已格式化的产物（<项目>_thesis.opju）再跑一次时不要变成
    # <项目>_thesis_thesis.opju。
    out_stem = stem if stem.endswith(suffix) else stem + suffix
    fig_dir = os.path.join(out_dir, f"{out_stem}_figures")

    snap = _snapshot_module(mod)
    style_report = _apply_style_to_module(mod, prof, keep_legend_pos=keep_legend_pos)
    tweaks = {} if no_tweaks else (getattr(mod, "PER_GRAPH_TWEAKS", {}) or {}).get(stem, {})
    origin_before = _origin_was_running()
    release = None
    body = None
    try:
        try:
            op.set_show(bool(show_origin))
            if use_open_session:
                g, origin_of, avail = _open_project_preferring_session(op, graph, src)
            else:
                if not src:
                    return {"ok": False, "error": "未给 project 路径",
                            "error_code": "BAD_ARGS"}
                if not op.open(src):
                    return {"ok": False, "error": f"Origin 打开失败: {src}",
                            "error_code": "OPEN_FAILED"}
                g, avail = _resolve_graph(op, graph)
                origin_of = "opened_file"
            if g is None:
                return {"ok": False, "error_code": "GRAPH_NOT_FOUND",
                        "error": f"项目里找不到图 {graph!r}",
                        "available_graphs": avail}
            if save:
                os.makedirs(out_dir, exist_ok=True)
            if export_png:
                os.makedirs(fig_dir, exist_ok=True)
            save_to = os.path.join(out_dir, f"{out_stem}.opju") if save else ""
            res = _format_graph_impl(op, g, mod, mod.font_index(mod.STYLE["font"]),
                                     tweaks, export_png, dpi, fig_dir, save_to)
            body = {"ok": not res["verify_issues"], "profile": profile,
                    "source": src, "graph_source": origin_of,
                    "style_applied": style_report["applied"],
                    "style_ignored": style_report["ignored"], **res,
                    "note": "只处理了这一张图；项目内其余图未改动。"
                            + ("" if save else " 本轮未保存 opju（save=false）。")}
        finally:
            # use_open_session 时借用的是已打开的会话，不能退出别人的 Origin。
            # 注意：释放必须发生在构建返回值**之前**（with 正常退出即 return 之前），
            # 否则 origin_release 永远回传旧值 None、且 release 后不能再读 COM 对象。
            release = None if use_open_session else _release_origin(
                op, started=True, origin_running_before=origin_before,
                keep_open=keep_open)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "FORMAT_FAILED",
                "traceback": traceback.format_exc(),
                "origin_release": release}
    finally:
        _restore_module(mod, snap)
    if body is not None:
        body["origin_release"] = release
    return body


def thesis_apply_style_only(project: str, graph: str, profile: str = "thesis",
                            dpi: int = 0, out_dir: str = "", save: bool = False,
                            keep_legend_pos: bool = False, no_tweaks: bool = False,
                            use_open_session: bool = False,
                            keep_open: bool = True,
                            show_origin: bool = False) -> dict:
    """只把样式/版式套到一张图上，**默认不保存、不导出**（原子操作）。

    等价于 `thesis_format_graph(..., save=False, export_png=False)`：把"改样式"
    与"出图/存盘"拆开，便于与 origin_edit_* 接力——先套统一样式，再用
    origin_edit_plot / origin_edit_axis / origin_edit_legend 逐条微调，
    最后用 thesis_export_project 或 thesis_export_open 出图。

    keep_open 默认 True（与本工具用途一致）：保住 Origin 会话与当前项目，
    否则下一步找不到那张图。要归还资源时可显式传 keep_open=false。

    代价提示：每次调用都要起一次 Origin COM + 跑像素量测闭环，约二三十秒。
    套完之后的 origin_edit_* 与 thesis_export_open 都是毫秒到秒级。
    """
    return thesis_format_graph(
        project=project, graph=graph, profile=profile, out_dir=out_dir, dpi=dpi,
        save=save, export_png=False, keep_legend_pos=keep_legend_pos,
        no_tweaks=no_tweaks, use_open_session=use_open_session,
        keep_open=keep_open, show_origin=show_origin)


def thesis_export_open(graph: str, out_path: str, fmt: str = "png",
                       width: int = 0, dpi: int = 600) -> dict:
    """导出**当前已打开**的某张图（不重新打开项目，配合接力微调后使用）。

    Args:
        graph: 图短名/长名；留空用活动图。
        out_path: 输出文件全路径（含扩展名）。
        fmt: png | svg | pdf | tif | emf 等；留空按 out_path 扩展名。
        width: PNG 像素宽；0 表示按页面 cm × dpi 自动算。
        dpi: width=0 时用于换算像素宽的 dpi。
    """
    try:
        import originpro as op
    except Exception as exc:
        return {"ok": False, "error": f"需要 originpro: {exc}",
                "error_code": "NO_ORIGINPRO"}
    fmt = (fmt or os.path.splitext(out_path)[1].lstrip(".") or "png").lower()
    g, avail = _resolve_graph(op, graph)
    if g is None:
        return {"ok": False, "error_code": "GRAPH_NOT_FOUND",
                "error": f"当前项目里找不到图 {graph!r}；可用：{avail}",
                "available_graphs": avail}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    try:
        if width:
            g.save_fig(out_path, type=fmt, width=int(width))
            px = int(width)
        else:
            resx = float(_num(op.lt_float("page.resx"), 600.0)) or 600.0
            w_cm = float(_num(op.lt_float("page.width"), 0)) / resx * 2.54
            px = int(round(w_cm / 2.54 * dpi)) if w_cm else 0
            if px:
                g.save_fig(out_path, type=fmt, width=px)
            else:
                g.save_fig(out_path, type=fmt)
        fixed = []
        if fmt in ("png", "tif", "jpg", "bmp") and \
                load_styles().get("export", {}).get("fix_dpi_metadata", True):
            fixed = _patch_figure_dpi([out_path], dpi)
        return {"ok": os.path.isfile(out_path), "graph": g.name, "file": out_path,
                "format": fmt, "px_width": px or None,
                "size": (os.path.getsize(out_path) if os.path.isfile(out_path) else 0),
                "dpi_metadata_fixed": fixed,
                "note": "从当前已打开的 Origin 项目导出，未重新打开文件。"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "EXPORT_FAILED",
                "traceback": traceback.format_exc()}


def thesis_format_project(project: str, profile: str = "thesis",
                          out_dir: str = "", dpi: int = 0,
                          skip_multilayer: bool = False,
                          keep_legend_pos: bool = False,
                          no_tweaks: bool = False,
                          export_png: bool = True,
                          save: bool = True,
                          show_origin: bool = False) -> dict:
    """按配置档格式化一个 Origin 项目里的所有图，另存新 opju 并导出 PNG。

    原文件绝不被修改（在临时副本上操作）。格式化与校验逻辑**原样复用**
    origin-batch-style/format_thesis_figures.py，本工具只负责编排与结果汇总。

    Args:
        project: 输入 .opju / .opj 路径。
        profile: 配置档（thesis / manuscript）。
        out_dir: 输出目录；留空则与输入同目录。
        dpi: 导出 PNG 的 dpi；0 表示用配置档里的 export_dpi。
        skip_multilayer: 跳过多 layer 复杂图（完全不动）。
        keep_legend_pos: 不把图例挪到框架右上角（图例已手工避开曲线时用）。
        no_tweaks: 不套用 PER_GRAPH_TWEAKS 逐图微调。
        export_png: 是否导出 PNG。
        show_origin: 是否显示 Origin 界面（排障用）。
    """
    import shutil
    import tempfile

    src = os.path.abspath(project)
    if not os.path.isfile(src):
        return {"ok": False, "error": f"文件不存在: {src}", "error_code": "NOT_FOUND"}

    try:
        import originpro as op
    except Exception as exc:
        return {"ok": False, "error": f"需要 originpro（请用 py3.9 origin 环境运行）: {exc}",
                "error_code": "NO_ORIGINPRO"}

    try:
        styles = load_styles()
        prof = resolve_profile(profile, styles)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED"}

    # 配置档决定走哪条已验证的管线：
    #   composite -> format_composite.py（拼版大图：缩放+按角色统一+收边）
    #   其余      -> format_thesis_figures.py（按 layer 数重排版面）
    if prof.get("used_by", "").endswith("format_composite.py"):
        return _format_composite_impl(
            src=src, graph_name="", out_dir=out_dir, prof=prof,
            dpi=int(dpi or _flatten_style(prof).get("export_dpi", 600)),
            regrid=False, page_w=_flatten_style(prof).get("page_w_cm", 17.5),
            row_gap=_flatten_style(prof).get("row_gap_cm", 1.21),
            no_panel_labels=False, show_origin=show_origin)

    try:
        mod = _load_module("format_thesis_figures")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED",
                "traceback": traceback.format_exc()}

    dpi = int(dpi or _flatten_style(prof).get("export_dpi", 600))
    out_dir = os.path.abspath(out_dir) if out_dir else os.path.dirname(src)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    suffix = prof.get("output_suffix", "_thesis")
    out_opju = os.path.join(out_dir, f"{stem}{suffix}.opju")
    fig_dir = os.path.join(out_dir, f"{stem}{suffix}_figures")
    if export_png:
        os.makedirs(fig_dir, exist_ok=True)

    snap = _snapshot_module(mod)
    style_report = _apply_style_to_module(mod, prof, keep_legend_pos=keep_legend_pos)
    tweaks = {} if no_tweaks else (getattr(mod, "PER_GRAPH_TWEAKS", {}) or {}).get(stem, {})

    tmp = tempfile.mkdtemp(prefix="thesis_fmt_")
    work = os.path.join(tmp, "work.opju")
    results, skipped, errors, exported = [], [], [], []
    origin_before = _origin_was_running()
    try:
        shutil.copy2(src, work)
        op.set_show(bool(show_origin))
        if not op.open(work):
            return {"ok": False, "error": f"Origin 打开失败: {work}",
                    "error_code": "OPEN_FAILED"}
        fidx = mod.font_index(mod.STYLE["font"])

        for g in op.graph_list("p"):
            if skip_multilayer:
                n = _layer_count(mod, g.name)
                if n > 1:
                    skipped.append({"graph": g.name, "lname": g.lname, "layers": n})
                    continue
            try:
                info = mod.format_graph(g, fidx)
                if info["name"] in tweaks:
                    tweaks[info["name"]](g)
                    info["tweak"] = True
                results.append(info)
            except Exception as exc:
                errors.append({"graph": getattr(g, "name", "?"), "error": str(exc),
                               "traceback": traceback.format_exc()})

        small_by_name = {i["name"]: i.get("small") for i in results}
        issues = []
        for g in op.graph_list("p"):
            if g.name in small_by_name:
                try:
                    issues += mod.verify_graph(g, fidx, small_by_name[g.name])
                except Exception as exc:
                    issues.append(f"verify {g.name} 失败: {exc}")

        opju_written = None
        if save:
            op.save(out_opju)
            opju_written = out_opju if os.path.isfile(out_opju) else None

        if export_png:
            for info in results:
                try:
                    g = op.find_graph(info["name"])
                    px = int(round(info["page_cm"][0] / 2.54 * dpi))
                    png = os.path.join(fig_dir, f"{info['name']}.png")
                    g.save_fig(png, type="png", width=px)
                    exported.append(png)
                except Exception as exc:
                    errors.append({"graph": info["name"], "stage": "export",
                                   "error": str(exc)})
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        release_note = _release_origin(op, started=True,
                                       origin_running_before=origin_before)
        _restore_module(mod, snap)

    dpi_fix = _patch_figure_dpi(exported, dpi) if styles.get("export", {}).get(
        "fix_dpi_metadata", True) else []

    return {
        "ok": not errors,
        "profile": profile,
        "source": src,
        "project_out": out_opju,
        "project_written": bool(opju_written),
        "saved": opju_written,
        "figures_dir": fig_dir,
        "dpi": dpi,
        "style_applied": style_report["applied"],
        "style_ignored": style_report["ignored"],
        "formatted": [{"graph": i["name"], "lname": i.get("lname"),
                       "layers": i["nlayers"], "layout": i.get("layout"),
                       "page_cm": i.get("page_cm"),
                       "panels_removed": i.get("panels_removed"),
                       "dual_y": i.get("dual_y")} for i in results],
        "n_formatted": len(results),
        "skipped": skipped,
        "per_graph_tweaks_applied": sorted(t for t in tweaks),
        "verify_issues": issues,
        "exported": exported,
        "dpi_metadata_fixed": dpi_fix,
        "errors": errors,
        "origin_release": release_note,
        "note": ("原文件未改动。" if save else "原文件未改动；本轮未保存 opju（save=false）。"),
    }


def thesis_export_project(project: str, out_dir: str = "", formats: str = "png",
                          dpi: float = 600, width_cm: float = 0,
                          margin: str = "", name_mode: str = "short",
                          overwrite: str = "replace", recursive: bool = False,
                          dry_run: bool = False) -> dict:
    """只导出、不改样式：把项目里所有图导成图片（复用 export_figures.py）。

    Args:
        project: 项目路径、目录或通配符（可多个，用分号分隔）。
        out_dir: 输出目录；留空则每项目同级的 <项目名>_figures。
        formats: 逗号分隔，如 "png,emf"；栅格 png/tif/jpg/bmp…，矢量 emf/pdf/eps。
        dpi: 栅格分辨率。
        width_cm: 统一印刷宽度（0=用每张图页面原宽）。
        margin: 留空=整页；tight=裁掉页面周围空白。
        name_mode: short | long | both | auto。
        overwrite: replace | skip。
        recursive: 目录输入时递归查找。
        dry_run: 只列清单不导出。
    """
    import types

    try:
        import originpro as op
    except Exception as exc:
        return {"ok": False, "error": f"需要 originpro: {exc}", "error_code": "NO_ORIGINPRO"}
    try:
        ef = _load_module("export_figures")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED"}

    items = [s for s in str(project).split(";") if s.strip()]
    projects = _expand_inputs(items, recursive)
    if not projects:
        return {"ok": False, "error": "没有可处理的项目文件", "error_code": "NO_INPUT"}

    fmt = ef.parse_types(formats)
    args = types.SimpleNamespace(
        out_dir=out_dir or None, type=fmt, dpi=float(dpi),
        width_cm=(float(width_cm) if width_cm else None), width_px=None,
        margin=(margin or None), name=name_mode, tree=False,
        pattern=[], exclude=[], graphs_only=False, embedded=False,
        overwrite=overwrite, fix_dpi=True, manifest=False, flat=False,
        recursive=recursive, dry_run=dry_run, show_origin=False)

    op.set_show(False)
    summary = []
    for proj in projects:
        try:
            summary.append(ef.export_project(proj, args, len(projects) > 1))
        except Exception as exc:
            summary.append({"project": proj, "error": str(exc),
                            "traceback": traceback.format_exc(), "figures": []})

    files = [f.get("file") for s in summary for f in (s.get("figures") or [])
             if f.get("file") and not dry_run]
    dpi_fix = _patch_figure_dpi(files, float(dpi)) if (files and ef.__dict__.get("FIX_DPI_TYPES")) else []
    return {"ok": all(not s.get("error") for s in summary),
            "n_projects": len(projects), "formats": fmt, "dpi": float(dpi),
            "summary": summary, "n_files": len(files),
            "dpi_metadata_fixed": dpi_fix,
            "note": "只读打开，项目本身未被修改。"}


def thesis_batch(projects: str, profile: str = "thesis", out_dir: str = "",
                 dpi: int = 0, recursive: bool = False,
                 skip_multilayer: bool = False, keep_legend_pos: bool = False,
                 no_tweaks: bool = False, export_png: bool = True) -> dict:
    """批量把多个项目按同一配置档格式化（一次处理一批，输出逐项目报告）。

    参数含义同 thesis_format_project；projects 支持分号分隔的多个路径、
    目录或通配符。目录输入时用 recursive=True 递归查找。
    """
    items = [s for s in str(projects).split(";") if s.strip()]
    files = _expand_inputs(items, recursive)
    if not files:
        return {"ok": False, "error": "没有可处理的 .opju 文件", "error_code": "NO_INPUT"}
    reports = []
    for f in files:
        reports.append(thesis_format_project(
            project=f, profile=profile, out_dir=out_dir, dpi=dpi,
            skip_multilayer=skip_multilayer, keep_legend_pos=keep_legend_pos,
            no_tweaks=no_tweaks, export_png=export_png))
    ok = sum(1 for r in reports if r.get("ok"))
    return {"ok": ok == len(reports), "profile": profile, "n_projects": len(files),
            "n_ok": ok, "n_failed": len(files) - ok,
            "total_figures": sum(r.get("n_formatted", 0) for r in reports),
            "reports": reports}


def thesis_verify_project(project: str, profile: str = "thesis") -> dict:
    """只读校验：打开项目，按配置档核验各文本对象的字体/字号/缺陷（不改文件）。

    Args:
        project: 要校验的 .opju（可以是已格式化的 _thesis 产物）。
        profile: 用于取期望字体与字号的配置档。
    """
    src = os.path.abspath(project)
    if not os.path.isfile(src):
        return {"ok": False, "error": f"文件不存在: {src}", "error_code": "NOT_FOUND"}
    try:
        import originpro as op
        styles = load_styles()
        prof = resolve_profile(profile, styles)
        mod = _load_module("format_thesis_figures")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_code": "SETUP_FAILED"}
    snap = _snapshot_module(mod)
    try:
        _apply_style_to_module(mod, prof)
        op.set_show(False)
        if not op.open(src, readonly=True):
            return {"ok": False, "error": f"打开失败（只读）: {src}",
                    "error_code": "OPEN_FAILED"}
        fidx = mod.font_index(mod.STYLE["font"])
        issues, graphs = [], []
        for g in op.graph_list("p"):
            n = _layer_count(mod, g.name)
            # 必须先做图层分类：插图层（inset / linked_inset，如 NMR 的放大谱）
            # 的字号是"只缩不放"的，比正文字号小属于预期。不把它标成 small 就
            # 会把预期的 7.5 pt 误报成问题（format_thesis_figures.verify_graph
            # 的 small_layers 参数正是为此存在；脚本自己的 main() 也是这么传的）。
            small = None
            try:
                infos = mod.analyze_layers(g, n)
                small = {x["i"] for x in infos
                         if x["kind"] in ("inset", "linked_inset")}
            except Exception as exc:
                issues.append(f"图层分类失败 {g.name}（按无插图处理）: {exc}")
            graphs.append({"graph": g.name, "lname": g.lname, "layers": n,
                           "small_layers": sorted(small) if small else []})
            try:
                issues += mod.verify_graph(g, fidx, small)
            except Exception as exc:
                issues.append(f"verify {g.name} 失败: {exc}")
        return {"ok": True, "project": src, "profile": profile,
                "n_graphs": len(graphs), "graphs": graphs,
                "issues": issues, "clean": not issues,
                "note": "只读打开，未修改文件。"}
    finally:
        _restore_module(mod, snap)


# --------------------------------------------------------------------------
# 协议层：纯同步 stdio JSON-RPC（与 origin_mcp_server._sync_stdio_server 同构）
# --------------------------------------------------------------------------
def _write_jsonrpc(resp) -> None:
    sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _infer_json_type(ann) -> str:
    if ann in (int,):
        return "integer"
    if ann in (float,):
        return "number"
    if ann in (bool,):
        return "boolean"
    if ann in (list, tuple):
        return "array"
    if ann in (dict,):
        return "object"
    origin = getattr(ann, "__origin__", None)
    if origin in (list, tuple):
        return "array"
    if origin is dict:
        return "object"
    return "string"


_SPECIAL_ARG_TYPES = {
    "changes": "object",
    "files": "array",
    "ops": "array",
    "formats": "array",
}


def _build_tool_registry() -> dict:
    import inspect
    registry = {}
    for name, fn in sorted(globals().items()):
        if not callable(fn) or not name.startswith("thesis_"):
            continue
        sig = inspect.signature(fn)
        props, required = {}, []
        for pname, param in sig.parameters.items():
            ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
            ptype = _SPECIAL_ARG_TYPES.get(pname, _infer_json_type(ann))
            props[pname] = {"type": ptype}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        registry[name] = {
            "name": name,
            "description": (fn.__doc__ or "").strip(),
            "inputSchema": {"type": "object", "properties": props, "required": required},
        }
    return registry


def _result_to_content_blocks(result):
    if isinstance(result, str):
        return [{"type": "text", "text": result}]
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]


def _sync_stdio_server() -> None:
    import inspect
    registry = _build_tool_registry()
    tool_fns = {n: globals()[n] for n in registry}

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(req, dict):
            continue
        msg_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}
        if msg_id is None:
            continue

        if method == "initialize":
            pv = (params.get("protocolVersion") if isinstance(params, dict)
                  else None) or _PROTO_FALLBACK
            _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": pv,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": _SERVER_NAME, "version": _SERVER_VERSION},
            }})
        elif method == "ping":
            _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif method == "tools/list":
            _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id,
                            "result": {"tools": list(registry.values())}})
        elif method == "tools/call":
            tname = params.get("name", "") if isinstance(params, dict) else ""
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            fn = tool_fns.get(tname)
            if fn is None:
                _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(
                        {"ok": False, "error": f"unknown tool: {tname}",
                         "error_code": "UNKNOWN_TOOL"}, ensure_ascii=False)}],
                    "isError": True}})
                continue
            try:
                valid = {k: v for k, v in args.items()
                         if k in inspect.signature(fn).parameters}
                _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": _result_to_content_blocks(fn(**valid)),
                    "isError": False}})
            except Exception as exc:
                _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": [{"type": "text", "text": json.dumps({
                        "ok": False, "error": str(exc),
                        "error_code": "TOOL_EXCEPTION",
                        "traceback": traceback.format_exc()}, ensure_ascii=False)}],
                    "isError": True}})
        else:
            _write_jsonrpc({"jsonrpc": "2.0", "id": msg_id, "error": {
                "code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    _write_boot_log()          # 设了 DSH_THESIS_BOOT_LOG 时才写
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--info":
        print(json.dumps(thesis_batch_dir_info(), ensure_ascii=False, indent=2))
    elif arg == "--list-tools":
        reg = _build_tool_registry()
        print(json.dumps({n: v["inputSchema"] for n, v in reg.items()},
                         ensure_ascii=False, indent=2))
    else:
        _sync_stdio_server()
