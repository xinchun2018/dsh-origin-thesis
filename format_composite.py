# -*- coding: utf-8 -*-
r"""Unify typography / line weights of ONE hand-assembled composite Origin graph.

针对"已经手工拼好的多面板大图"（本例 UNTITLED.opju 的 Graph111：3x3 网格，
8 个面板 + 3 个双 Y 叠加层 + 1 个放大插图，右下角缺一张图）：

- **不重排版面**：面板位置/大小、标注锚点、插图、叠加层关系全部保持原样。
  只把页面整体等比缩放到最终印刷宽度，图层是 unit=1(页面百分比)/unit=7(父层
  百分比)，自动跟随。
- **按角色统一字号**：轴标题 / 刻度数字 / 曲线标识 / 图内标注 / 图例各一个值，
  9 个面板一致。
- **统一字体**为 Times New Roman（原图混用 Times(353)/Arial(74)/默认(1)）。
- **统一线宽**：曲线、轴线、刻度线各一个值（原图曲线 0.43~1.0 pt 混用）。

关键坑（详见 origin-batch-style/README.md）:
- 文本里的 `\pNN(...)` 是**百分比字号倍数**且会覆盖对象 fsize（本图 FTIR 标题
  `\p117` → 7x1.17≈8.2pt，峰位标注 `\p72` → 6.5x0.72≈4.7pt）。想让
  SetNumProp('fsize') 生效必须先剥掉这层包装 → 复用
  format_thesis_figures.strip_font_escapes。
- 剥掉 `\f:字体(...)` 后必须把对象 font 设为 Times 索引，否则回落到 Arial。
- 含 `%(` 替换串的文本（占位标题 `%(?X)`、图例 `%(1)`）**不能改写文本**，
  只设 font/fsize。
- `page.width/height` 单位是 resx 像素，且赋值别用 LabTalk 表达式（会截断）。

原文件不会被修改；结果另存。

用法:
  C:\Users\liuxc\miniconda3\envs\origin\python.exe format_composite.py ^
      --project "C:\Users\liuxc\tu\UNTITLED.opju" [--page-w 17.5] [--dpi 600]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import traceback

sys.stdout.reconfigure(encoding="utf-8")

import originpro as op

# 复用已验证的转义串解析器（\g() Symbol 区保护、\(40) 字面括号、\pNN 剥离等）
from format_thesis_figures import strip_font_escapes, set_obj_num

# ------------------------------ 样式配置 --------------------------------- #
# 字号按**最终印刷尺寸**的绝对 pt 给出：页面已缩到 page_w_cm，导出 600 dpi 后
# 按 100% 插入文档即为这些 pt。
STYLE = {
    "page_w_cm": 17.5,      # 最终印刷宽度（期刊整页宽）；高度按原图宽高比
    "font": "Times New Roman",
    "title_pt": 7.5,        # 轴标题（含双 Y 的右轴标题）
    "tick_pt": 6.5,         # 刻度数字（四条轴）
    "series_pt": 6.5,       # 曲线标识 Ti-BDC-80 / N 1s 等
    "annot_pt": 5.5,        # 图内标注：峰位数字、失重百分数
    "legend_pt": 6.5,       # 图例
    # 放大插图（本图 NMR 的 1.9 mm 微缩视图）整体保持原样：统一样式会把它
    # 糊成黑块。只统一字体。
    "panel_pt": 8.0,        # (a)(b)(c)… 面板标签，粗体
    "panel_pad_px": 12,     # 面板标签与框架左/上缘的间隙（页面像素 @600dpi）
    "panel_labels": True,   # 是否添加面板标签
    "inset_tick_pt": None,  # 保留位：插图不改字号（见 format_axes 说明）
    "axis_th": 0.75,        # 轴线粗细 (pt)
    "tick_th": 0.75,        # 主/次刻度线粗细 (pt)
    "tick_len": 2.6,        # 主刻度线长度
    "line_pt": 0.75,        # 曲线线宽 (pt)
    "symbol_pt": 3.0,       # 数据点符号大小 (pt)
    # 面板窄、峰位标注多时（如 FTIR 9 个四位数标注挤在 3.7 cm 宽的面板里），
    # 横排必然重叠 —— 该层的数字类标注整体转 90°（IR/Raman 谱图的常规做法）。
    "rotate_annot_min": 6,
    # --regrid 时的行距与底边距（**最终印刷 cm**）：字号是绝对 pt，X 轴刻度
    # 数字+轴标题所需留白与缩放无关。1.21 cm 取自已验收的 3x3 参考图
    # (Graph112: 行距 2.006 层坐标 cm x 0.6044 缩放)。
    "row_gap_cm": 1.21,
    "bottom_cm": None,      # None -> 与 row_gap_cm 相同（末行 X 轴标题占位）
    "dpi": 600,
}

# 非文本装饰对象（无 Text 内容）与内部对象，一律跳过。
# Panel[A-Z] 是本脚本加的面板标签，刻意放在框架外，不能参与收边。
_SKIP_OBJ = re.compile(
    r"^(3D|__|_\d+$|Line|Arrow|Rect|Circle|Polygon|OR$|OT$|X\d+$|Panel[A-Z]$)")

# 纯数字/百分数 → 图内标注；否则视为曲线标识
_NUMERIC_RE = re.compile(r"^[\d.,\s+\-]*\d[\d.,\s%+\-]*$")

AXIS_TITLE_OBJS = ("XB", "YL", "XT", "YR")

# 需要收回框架内的角色。图例框会随字号自动变大（本例 图3/图4 每个面板都有
# 图例），原先贴着右框线的会溢出，所以和标注一起收边；轴标题在框架外，不收。
CLAMP_ROLES = ("series", "annot", "legend")


def lt(cmd: str) -> None:
    try:
        op.lt_exec(cmd)
    except Exception as exc:
        print(f"  [warn] lt_exec {cmd!r} -> {exc}")


def ltf(expr: str):
    try:
        v = op.lt_float(expr)
        return None if v != v else v       # NaN -> None
    except Exception:
        return None


def font_index(name: str) -> int:
    lt(f"double __fidx = font({name});")
    v = ltf("__fidx")
    return int(v) if v else 1


# ---------------------------- 页面缩放 ----------------------------------- #

def read_layout(nlayers: int) -> list[dict]:
    """读取各 layer 的类别与几何。

    unit=7 是链接层（百分比 of 父层）：铺满父层的是 overlay（双 Y 轴载体），
    带偏移且明显更小的是 inset（放大插图）。其余 unit!=7 为 main（面板）。
    """
    infos = []
    for i in range(1, nlayers + 1):
        lt(f"page.active={i};")
        unit = int(ltf("layer.unit") or 1)
        rec = {"i": i, "unit": unit, "link": ltf("layer.link")}
        if unit == 7:
            l = ltf("layer.left") or 0
            t = ltf("layer.top") or 0
            w = ltf("layer.width") or 0
            h = ltf("layer.height") or 0
            rec["pct_of_parent"] = [l, t, w, h]
            rec["kind"] = "overlay" if (abs(l) < 5 and abs(t) < 5 and w > 90) \
                else "inset"
        else:
            lt("layer.unit = 1;")          # 页面百分比
            rec["pct"] = [ltf("layer.left") or 0, ltf("layer.top") or 0,
                          ltf("layer.width") or 0, ltf("layer.height") or 0]
            lt("layer.unit = 3;")          # cm，仅用于报告
            rec["cm"] = [round(ltf("layer.left") or 0, 4),
                         round(ltf("layer.top") or 0, 4),
                         round(ltf("layer.width") or 0, 4),
                         round(ltf("layer.height") or 0, 4)]
            rec["kind"] = "main"
        infos.append(rec)
    return infos


def rescale_page(infos: list[dict], target_w_cm: float) -> tuple[float, float]:
    """把页面等比缩到 target_w_cm 宽。

    图层是页面百分比坐标，等比缩放后百分比不变；但仍显式写回一遍，防止
    Origin 内部以绝对单位存储导致版面走形。链接层(unit=7)按父层百分比
    自动跟随，不写。
    """
    resx = ltf("page.resx") or 600.0
    resy = ltf("page.resy") or 600.0
    w0_cm = (ltf("page.width") or 0) / resx * 2.54
    h0_cm = (ltf("page.height") or 0) / resy * 2.54
    if w0_cm <= 0:
        raise RuntimeError("page width unreadable")
    scale = target_w_cm / w0_cm
    new_h_cm = h0_cm * scale
    # 像素数在 Python 里 round 成整数常量写入（LabTalk 表达式会截断小数）
    lt(f"page.width = {int(round(target_w_cm / 2.54 * resx))};")
    lt(f"page.height = {int(round(new_h_cm / 2.54 * resy))};")
    # 面板宽高对齐到众数值：手工拼图常有个别面板差零点几毫米（本图 L13 宽
    # 6.164 vs 其余 6.147 cm），网格严格等宽才经得起排版检查。left/top 本就
    # 严格成列成行，保留各自原值。
    mains = [r for r in infos if r["kind"] == "main"]
    ws = sorted(round(r["pct"][2], 4) for r in mains)
    hs = sorted(round(r["pct"][3], 4) for r in mains)
    uw, uh = (ws[len(ws) // 2], hs[len(hs) // 2]) if mains else (None, None)
    for rec in mains:
        l, t, w, h = rec["pct"]
        if uw is not None and (abs(w - uw) > 1e-6 or abs(h - uh) > 1e-6):
            print(f"  L{rec['i']}: panel size {w:.4f}x{h:.4f}% -> {uw:.4f}x{uh:.4f}% (snap)")
            w, h = uw, uh
        lt(f"page.active={rec['i']};")
        lt("layer.unit = 1;")
        lt(f"layer.left = {l:.6f}; layer.top = {t:.6f}; "
           f"layer.width = {w:.6f}; layer.height = {h:.6f};")
        rec["pct"] = [l, t, w, h]      # 收边/面板标签要用最终百分比
    print(f"page {w0_cm:.3f}x{h0_cm:.3f} cm -> {target_w_cm:.3f}x{new_h_cm:.3f} cm "
          f"(scale {scale:.4f})")
    return target_w_cm, new_h_cm


def _cluster(vals, tol: float) -> list[float]:
    """把一维坐标聚成组（组内差 <= tol），返回各组均值（升序）。"""
    out: list[list[float]] = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def regrid_page(infos: list[dict], target_w_cm: float, row_gap_cm: float,
                bottom_cm: float | None) -> tuple[float, float]:
    """缩到 target_w_cm 宽的同时把面板重排成**行距均匀**的网格并裁掉页面空白。

    手工拼图的常见毛病：页面按 3 行开好但只放了 2 行 —— 本例 图3 六个面板
    行距 3.96 cm（是所需留白的两倍）、底部还空 3.96 cm。列方向原样保留
    （左边距与列间距本来就等于 Y 轴标题/刻度数字所需宽度），只重算行位置、
    页高，顺带把面板尺寸对齐到众数值。

    行距/底边距按**最终印刷 cm** 给出：字号是绝对 pt，X 轴刻度数字+轴标题
    需要的那条留白与页面缩放比无关。

    直接用 `layer.unit=3`（cm）写最终几何——比换算页面百分比少一层间接，
    写完再切回 unit=1 让 Origin 自己折算成百分比（切换 unit 会转换存储值，
    不是重新解释数字）。
    """
    resx = ltf("page.resx") or 600.0
    resy = ltf("page.resy") or 600.0
    w0_cm = (ltf("page.width") or 0) / resx * 2.54
    h0_cm = (ltf("page.height") or 0) / resy * 2.54
    if w0_cm <= 0:
        raise RuntimeError("page width unreadable")
    mains = [r for r in infos if r["kind"] == "main"]
    if not mains:
        raise RuntimeError("no main layer to regrid")
    scale = target_w_cm / w0_cm
    ws = sorted(round(r["cm"][2], 4) for r in mains)
    hs = sorted(round(r["cm"][3], 4) for r in mains)
    uw, uh = ws[len(ws) // 2], hs[len(hs) // 2]
    tol = 0.25                                     # 同行/同列的坐标容差 (cm)
    rows = _cluster([r["cm"][1] for r in mains], tol)
    cols = _cluster([r["cm"][0] for r in mains], tol)
    gap = row_gap_cm / scale                       # 最终 cm -> 原页面 cm
    bot = (row_gap_cm if bottom_cm is None else bottom_cm) / scale
    new_h0 = rows[0] + len(rows) * uh + (len(rows) - 1) * gap + bot
    new_h_cm = new_h0 * scale
    lt(f"page.width = {int(round(target_w_cm / 2.54 * resx))};")
    lt(f"page.height = {int(round(new_h_cm / 2.54 * resy))};")
    for rec in mains:
        l0, t0, w0, h0 = rec["cm"]
        ri = min(range(len(rows)), key=lambda k: abs(rows[k] - t0))
        ci = min(range(len(cols)), key=lambda k: abs(cols[k] - l0))
        l = cols[ci] * scale
        t = (rows[0] + ri * (uh + gap)) * scale
        w, h = uw * scale, uh * scale
        lt(f"page.active={rec['i']};")
        lt("layer.unit = 3;")
        lt(f"layer.left = {l:.6f}; layer.top = {t:.6f}; "
           f"layer.width = {w:.6f}; layer.height = {h:.6f};")
        lt("layer.unit = 1;")                      # 恢复页面百分比存储
        rec["pct"] = [l / target_w_cm * 100, t / new_h_cm * 100,
                      w / target_w_cm * 100, h / new_h_cm * 100]
        rec["grid"] = (ri, ci)
        print(f"  L{rec['i']}: r{ri}c{ci} {t0:.3f}->{t / scale:.3f} cm(top) "
              f"{w0:.3f}x{h0:.3f}->{uw:.3f}x{uh:.3f} cm")
    print(f"page {w0_cm:.3f}x{h0_cm:.3f} cm -> {target_w_cm:.3f}x{new_h_cm:.3f} cm "
          f"({len(rows)}x{len(cols)} grid, scale {scale:.4f}, "
          f"row gap {row_gap_cm:.2f} cm final)")
    return target_w_cm, new_h_cm


# ---------------------------- 逐层统一样式 -------------------------------- #

def format_axes(kind: str, font_idx: int) -> None:
    """四条轴的刻度数字字号/字体、轴线与刻度线粗细、刻度朝向。

    x2/y2 是顶轴/右轴：双 Y 轴图的右轴刻度数字属于叠加层的 y/y2，必须一并设。

    **放大插图整个跳过**（只统一字体）：本图的 NMR 插图只有 1.9 mm 宽，
    统一的 2.6 pt 刻度长 + 0.75 pt 轴线会把整个插图糊成一个黑块，
    4.5 pt 的刻度数字也比框架本身还宽。它是手工做的局部放大视图而不是
    面板，原有的极小样式是刻意的，保持原样。
    """
    s = STYLE
    if kind == "inset":
        for ax in ("x", "x2", "y", "y2"):
            lt(f"layer.{ax}.label.font = {font_idx};")
        return
    for ax in ("x", "x2", "y", "y2"):
        lt(f"layer.{ax}.label.pt = {s['tick_pt']};")
        lt(f"layer.{ax}.label.font = {font_idx};")
        lt(f"layer.{ax}.thickness = {s['axis_th']};")
        lt(f"layer.{ax}.tickThickness = {s['tick_th']};")
        lt(f"layer.{ax}.mtickThickness = {s['tick_th']};")
        lt(f"layer.{ax}.tickLength = {s['tick_len']};")
        # layer.axis.ticks 位掩码: 1=主朝内 2=主朝外 4=次朝内 8=次朝外。
        # 显示的刻度一律改朝内，本来隐藏的(位为0)保持隐藏。
        ticks = ltf(f"layer.{ax}.ticks")
        if ticks is not None:
            t = int(ticks)
            inward = (1 if t & 3 else 0) | (4 if t & 12 else 0)
            if inward != t:
                lt(f"layer.{ax}.ticks = {inward};")


_NICE_STEPS = (1.0, 2.0, 2.5, 5.0)


def _nice_step(x: float) -> float:
    """>= x 的最小"整齿"步长（1/2/2.5/5 x 10^k）。"""
    import math
    if x <= 0:
        return 1.0
    k = math.floor(math.log10(x))
    for m in _NICE_STEPS:
        v = m * 10 ** k
        if v >= x - 1e-12:
            return v
    return 10.0 ** (k + 1)


def thin_x_labels(width_cm: float, tick_pt: float) -> str | None:
    """X 轴刻度数字排不开时加大刻度间隔（只会变少，不会变多）。

    面板缩到 3.7 cm 宽后，原本 200 cm-1 一格的 Raman 轴要画 10 个四位数标签
    （间距 0.38 cm < 标签宽 0.46 cm）→ 糊成一团。按字符数估算标签宽度，
    把间隔提到最近的整齿值。

    分类轴（label.type=2，柱状图的 Ti-BDC-80/120/150 文字标签）必须跳过，
    改 inc 会打乱文字标签与柱子的对应。
    """
    if int(ltf("layer.x.label.type") or 1) != 1:
        return None                      # 文字/分类刻度标签
    xf, xt, inc = ltf("layer.x.from"), ltf("layer.x.to"), ltf("layer.x.inc")
    if None in (xf, xt, inc) or not inc or xt == xf or width_cm <= 0:
        return None
    span = abs(xt - xf)
    # 标签最宽的那个（含负号/小数点）决定所需间距
    chars = max(len(f"{v:g}") for v in (xf, xt))
    need_cm = chars * 0.5 * tick_pt * 2.54 / 72.0 + 0.08     # 0.5em/字符 + 间隙
    new_inc = inc
    for _ in range(8):
        if width_cm * new_inc / span >= need_cm:
            break
        new_inc = _nice_step(new_inc * 1.05)
    if new_inc > inc:
        lt(f"layer.x.inc = {new_inc:.10g};")
        return (f"x.inc {inc:g}->{new_inc:g} "
                f"({int(span / inc) + 1}->{int(span / new_inc) + 1} labels)")
    return None


PANEL_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def add_panel_labels(g, infos: list[dict], page_px, font_idx: int) -> list[str]:
    """在每个面板框架**上方**、与框架左缘对齐处加 (a)(b)(c)… 标签，行优先。

    先用 `label -p`（框架内百分比，不接受负值）创建，再用页面像素
    SetLeft/SetTop 挪到框架外——已验证像素坐标可写且跨渲染保持。

    放框架**左侧**会压住旋转 90° 的 Y 轴标题（本图 L10 的
    "Normalized intensity (a.u.)" 就在那个位置）；放框架**上方**用的是
    页边距/上一行 X 轴标题下方的空白，三行都够（首行上方 0.36 cm，
    8 pt 标签高约 0.28 cm）。
    """
    s = STYLE
    PW, PH = page_px
    mains = [r for r in infos if r["kind"] == "main"]
    # 行优先：先按 top 分行（容差 ~2% 页高），行内按 left 排
    mains.sort(key=lambda r: (round(r["pct"][1] / 2), r["pct"][0]))
    out = []
    for k, r in enumerate(mains):
        if k >= len(PANEL_LETTERS):
            break
        letter = PANEL_LETTERS[k]
        name = f"Panel{letter.upper()}"
        lt(f"page.active={r['i']};")
        lt(f'label -p 3 92 -n {name} "\\b(({letter}))";')
        obj = None
        try:
            for o in list(g[r["i"] - 1].obj.GraphObjects):
                if o.GetName() == name:
                    obj = o
                    break
        except Exception:
            pass
        if obj is None:
            print(f"  [warn] panel label {name} not created on L{r['i']}")
            continue
        set_obj_num(obj, "fsize", s["panel_pt"])
        set_obj_num(obj, "font", font_idx)
        fl, ft = r["pct"][0] / 100 * PW, r["pct"][1] / 100 * PH
        try:
            H = obj.GetHeight()
            obj.SetLeft(int(round(fl)))
            obj.SetTop(int(round(max(0, ft - H - s["panel_pad_px"]))))
            out.append(f"L{r['i']}=({letter})")
        except Exception as exc:
            print(f"  [warn] place panel label {name}: {exc}")
    return out


def frame_px(rec: dict, infos: list[dict], page_px: tuple[float, float]):
    """图层框架的页面像素矩形 (left, top, w, h)。

    overlay 层是父层的 0,0,100,100%，框架与父层重合（失重百分数标注就挂在
    这些叠加层上）；inset 刻意做得极小，不参与收边。
    """
    PW, PH = page_px
    if rec["kind"] == "main":
        l, t, w, h = rec["pct"]
    elif rec["kind"] == "overlay":
        parent = next((x for x in infos
                       if x["i"] == int(rec.get("link") or 0)), None)
        if parent is None or parent["kind"] != "main":
            return None
        l, t, w, h = parent["pct"]
    else:
        return None
    return (l / 100 * PW, t / 100 * PH, w / 100 * PW, h / 100 * PH)


def clamp_texts(glayer, box, pad_px: float, legend_pad_px: float = None) -> list[str]:
    """把图内标注/曲线标识/图例收回图层框架内。

    面板缩小后字号按绝对 pt 给，文字相对面板变大了约 1.6 倍，原先手工摆放
    刚好贴边的标注就会溢出框架（本图 FTIR/Raman 的 Ti-BDC-xxx 越过右边框，
    转 90° 的峰位标注探出下边框压住刻度数字）。

    对象的 GetLeft/GetWidth 是页面像素且 SetLeft/SetTop 可写（已验证写入后
    .x 会同步更新并能跨渲染保持），所以直接按框架做几何收边最稳，
    不必处理轴反向/锚点语义。

    图例用更大的 pad：图例框长高后常被顶到贴着框线，正好压在贴边的那条
    曲线上（图4 面板 a 的 Ti-BDC-180 平线就在下框线上方 0.05 cm）。
    """
    fl, ft, fw, fh = box
    moved = []
    try:
        objs = list(glayer.obj.GraphObjects)
    except Exception:
        return moved
    for o in objs:
        try:
            name = o.GetName()
            raw = o.Text or ""
        except Exception:
            continue
        role = classify_text(name, raw) if raw else None
        if role not in CLAMP_ROLES:
            continue
        pad = legend_pad_px if (role == "legend" and legend_pad_px) else pad_px
        try:
            L, T, W, H = o.GetLeft(), o.GetTop(), o.GetWidth(), o.GetHeight()
        except Exception:
            continue
        if W <= 0 or H <= 0:
            continue
        # 比框架还宽/高的标注居中，否则夹到 [框架内缘+pad] 区间
        nl = (fl + (fw - W) / 2) if W > fw - 2 * pad else \
            min(max(L, fl + pad), fl + fw - W - pad)
        nt = (ft + (fh - H) / 2) if H > fh - 2 * pad else \
            min(max(T, ft + pad), ft + fh - H - pad)
        if abs(nl - L) >= 1 or abs(nt - T) >= 1:
            try:
                if abs(nl - L) >= 1:
                    o.SetLeft(int(round(nl)))
                if abs(nt - T) >= 1:
                    o.SetTop(int(round(nt)))
                moved.append(f"{name} ({L},{T})->({int(nl)},{int(nt)})")
            except Exception as exc:
                print(f"  [warn] clamp {name} failed: {exc}")
    return moved


def separate_texts(glayer, box, gap_px: float) -> list[str]:
    """把互相重叠的图内标注/曲线标识分开（只在**垂直**方向推）。

    字号按最终印刷 pt 给出，页面缩小后文字相对面板变大约 1.35 倍，原先手工
    留的间隙就吃光了（图3 面板 d 的 "Ti-BDC-150" 与峰位标注 "C=O" 原本水平
    相邻 0.05 cm，缩放后直接叠在一起）。

    只推垂直方向：这些标注的横坐标指向具体峰位/谱线，左右挪会指错峰；上下
    挪仍在同一条谱线附近，语义不变。按当前 top 排序自上而下扫，重叠就把
    下面那个压到上面那个的下沿 + gap，并夹在框架内。
    """
    fl, ft, fw, fh = box
    items = []
    try:
        objs = list(glayer.obj.GraphObjects)
    except Exception:
        return []
    for o in objs:
        try:
            name, raw = o.GetName(), o.Text or ""
        except Exception:
            continue
        # 图例是整块矩形，已被 clamp 放到角上，不参与互推
        if not raw or classify_text(name, raw) not in ("series", "annot"):
            continue
        try:
            L, T, W, H = o.GetLeft(), o.GetTop(), o.GetWidth(), o.GetHeight()
        except Exception:
            continue
        if W > 0 and H > 0:
            items.append([o, name, L, T, W, H])
    items.sort(key=lambda r: r[3])
    moved = []
    for k, cur in enumerate(items):
        for prev in items[:k]:
            # 水平有交叠才算冲突
            if cur[2] >= prev[2] + prev[4] or cur[2] + cur[4] <= prev[2]:
                continue
            need = prev[3] + prev[5] + gap_px
            if cur[3] < need:
                new_t = min(need, ft + fh - cur[5])      # 别推出框架下沿
                if new_t - cur[3] >= 1:
                    try:
                        cur[0].SetTop(int(round(new_t)))
                        moved.append(f"{cur[1]} y {int(cur[3])}->{int(new_t)} "
                                     f"(clear of {prev[1]})")
                        cur[3] = new_t
                    except Exception as exc:
                        print(f"  [warn] separate {cur[1]} failed: {exc}")
    return moved


def format_plots(glayer) -> list[tuple[str, float, float]]:
    """统一曲线线宽与符号大小。返回 (range, 原线宽, 新线宽) 便于报告。

    line.width 直接就是 pt（GPlot.set_float），比 LabTalk `set -w`(1/500 pt)
    直观。柱状图的 line.width 是柱子边框宽度。
    """
    s = STYLE
    out = []
    try:
        plots = glayer.plot_list()
    except Exception as exc:
        print(f"  [warn] plot_list failed: {exc}")
        return out
    for dp in plots:
        try:
            w0 = dp.get_float("line.width")
            dp.set_float("line.width", s["line_pt"])
            dp.set_float("symbol.size", s["symbol_pt"])
            out.append((dp.lt_range(), w0, s["line_pt"]))
        except Exception as exc:
            print(f"  [warn] set plot style failed on {dp.name}: {exc}")
    return out


def classify_text(name: str, raw: str) -> str | None:
    """返回 'title' / 'legend' / 'series' / 'annot' / None(跳过)。"""
    upper = name.upper()
    if upper in AXIS_TITLE_OBJS:
        return "title"
    if upper == "LEGEND":
        return "legend"
    if _SKIP_OBJ.match(name):
        return None
    payload, _ = strip_font_escapes(raw)
    if not payload:
        return None
    # 峰位数字 (1714)、失重百分数 (14.3%) → 图内标注；带字母的 → 曲线标识
    return "annot" if _NUMERIC_RE.match(payload) else "series"


def format_texts(glayer, font_idx: int) -> tuple[list[str], int]:
    """统一本层所有文本对象的字体与字号。返回 (变更记录, 数字类标注个数)。

    含 `%(` 替换串的文本（`%(?X)` 占位标题、`%(1)` 图例）只设 font/fsize，
    绝不改写文本——包 \b() 会破坏替换导致内容消失。
    **图例一律不改写文本**：图例串是"每条 `|` / 换行分隔一个条目"的独立语法，
    Origin 先切条目再逐条解析转义，整串外包一层 \b() 会让第 1 条粗体、
    最后一条多出一个 `)`（图4 六个面板的图例都栽在这上面）。
    其余文本剥掉 \pNN/\f:/\b 包装（\pNN 会覆盖对象 fsize），bold 用外层
    \b() 重新表达，这样对象 fsize 才真正生效。

    数字类标注个数 >= rotate_annot_min 时，把它们整体转 90°（IR/Raman
    谱图窄面板里横排数字必然重叠）。转 90° 只改 rotate，不动锚点。
    """
    s = STYLE
    pt_of = {"title": s["title_pt"], "legend": s["legend_pt"],
             "series": s["series_pt"], "annot": s["annot_pt"]}
    log = []
    annots = []          # (obj, name) —— 数字类标注，可能需要转 90°
    try:
        objs = list(glayer.obj.GraphObjects)
    except Exception:
        return log, 0
    for o in objs:
        try:
            name = o.GetName()
            raw = o.Text or ""
        except Exception:
            continue
        if not raw:
            continue
        role = classify_text(name, raw)
        if role is None:
            continue
        pt = pt_of[role]
        if role != "legend" and "%(" not in raw:
            payload, bold = strip_font_escapes(raw)
            new_text = f"\\b({payload})" if bold else payload
            if new_text != raw:
                try:
                    o.Text = new_text
                except Exception as exc:
                    print(f"  [warn] rewrite {name} failed: {exc}")
        try:
            old = o.GetNumProp("fsize")
        except Exception:
            old = None
        set_obj_num(o, "fsize", pt)
        set_obj_num(o, "font", font_idx)
        log.append(f"{name}[{role}] {old}->{pt}")
        if role == "annot":
            annots.append((o, name))
    if len(annots) >= s["rotate_annot_min"]:
        for o, name in annots:
            set_obj_num(o, "rotate", 90)
        log.append(f"rotated {len(annots)} annot(s) 90deg")
    return log, len(annots)


# ------------------------------ 主流程 ----------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--graph", default=None, help="图名（默认第一张）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--suffix", default="_pub")
    ap.add_argument("--page-w", type=float, default=STYLE["page_w_cm"])
    ap.add_argument("--dpi", type=int, default=STYLE["dpi"])
    ap.add_argument("--font", default=STYLE["font"])
    ap.add_argument("--no-rescale", action="store_true",
                    help="不缩放页面，只统一字体/字号/线宽")
    ap.add_argument("--regrid", action="store_true",
                    help="把面板重排成行距均匀的网格并裁掉页面底部空白"
                         "（页面按 3 行开好只放了 2 行时用）")
    ap.add_argument("--row-gap", type=float, default=STYLE["row_gap_cm"],
                    help="--regrid 的行距，最终印刷 cm（默认 1.21）")
    ap.add_argument("--bottom", type=float, default=None,
                    help="--regrid 的底边距，最终印刷 cm（默认同 --row-gap）")
    ap.add_argument("--no-panel-labels", action="store_true",
                    help="不添加 (a)(b)(c)… 面板标签")
    ap.add_argument("--show-origin", action="store_true")
    args = ap.parse_args()

    STYLE["page_w_cm"] = args.page_w
    STYLE["dpi"] = args.dpi
    STYLE["font"] = args.font
    STYLE["panel_labels"] = not args.no_panel_labels
    STYLE["row_gap_cm"] = args.row_gap
    STYLE["bottom_cm"] = args.bottom

    src = os.path.abspath(args.project)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.dirname(src)
    os.makedirs(out_dir, exist_ok=True)   # op.save/save_fig 对不存在的目录静默失败
    stem = os.path.splitext(os.path.basename(src))[0]
    out_opju = os.path.join(out_dir, f"{stem}{args.suffix}.opju")
    out_png = os.path.join(out_dir, f"{stem}{args.suffix}.png")

    tmp = tempfile.mkdtemp(prefix="origin_comp_")
    work = os.path.join(tmp, "work.opju")
    shutil.copy2(src, work)        # 绝不改原文件

    op.set_show(bool(args.show_origin))
    if not op.open(work):
        raise RuntimeError(f"Origin 打开失败: {work}")

    graphs = op.graph_list('p')     # 'p' = 全项目（图可能在 PE 子文件夹）
    g = next((x for x in graphs if x.name == args.graph), graphs[0]) \
        if args.graph else graphs[0]
    lt(f"win -a {g.name};")
    nlayers = int(ltf("page.nlayers") or 0)
    fidx = font_index(STYLE["font"])
    print(f"graph={g.name} nlayers={nlayers} font={STYLE['font']}(idx {fidx})")

    infos = read_layout(nlayers)
    for r in infos:
        print(f"  L{r['i']:<2} {r['kind']:<7} unit={r['unit']} "
              f"{r.get('cm') or r.get('pct_of_parent')}")

    if args.no_rescale:
        resx = ltf("page.resx") or 600.0
        pw = (ltf("page.width") or 0) / resx * 2.54
        ph = (ltf("page.height") or 0) / (ltf("page.resy") or 600.0) * 2.54
    elif args.regrid:
        pw, ph = regrid_page(infos, STYLE["page_w_cm"], STYLE["row_gap_cm"],
                             STYLE["bottom_cm"])
    else:
        pw, ph = rescale_page(infos, STYLE["page_w_cm"])

    report = {"graph": g.name, "page_cm": [round(pw, 3), round(ph, 3)],
              "style": dict(STYLE), "layers": []}
    for r in infos:
        i = r["i"]
        lt(f"page.active={i};")
        format_axes(r["kind"], fidx)
        thinned = None
        if r["kind"] == "main":
            # 叠加层与父层共用 X 轴（改它会和父层打架）；插图整体保持原样。
            lt("layer.unit = 3;")
            thinned = thin_x_labels(ltf("layer.width") or 0, STYLE["tick_pt"])
        # 插图的曲线是 1.9 mm 内的微缩视图，0.4 pt 是刻意的，不统一
        widths = [] if r["kind"] == "inset" else format_plots(g[i - 1])
        texts, n_annot = format_texts(g[i - 1], fidx)
        report["layers"].append({"i": i, "kind": r["kind"], "thinned": thinned,
                                 "plots": [[a, b, c] for a, b, c in widths],
                                 "texts": texts})
        print(f"  L{i} ({r['kind']}): {len(widths)} plot(s) "
              f"{[round(b or 0, 2) for _, b, _ in widths]} -> {STYLE['line_pt']}, "
              f"{len(texts)} text obj(s)"
              + (f", rotated {n_annot} annot 90deg" if n_annot >= STYLE['rotate_annot_min'] else "")
              + (f", {thinned}" if thinned else ""))

    # 字号定完后先强制渲染一次，让各文本对象的包围盒刷新到最终字号，
    # 再按框架收边（否则读到的还是旧字号的盒子）。收边可能触发重排，
    # 所以渲染->收边跑两轮。
    dummy = os.path.join(tempfile.gettempdir(), "_origin_comp_dummy.png")
    page_px = (ltf("page.width") or 0, ltf("page.height") or 0)
    if STYLE["panel_labels"]:
        labels = add_panel_labels(g, infos, page_px, fidx)
        print(f"  panel labels: {' '.join(labels)}")
    for rnd in range(2):
        try:
            g.save_fig(dummy, type="png", width=900)
        except Exception as exc:
            print(f"  [warn] dummy render failed: {exc}")
        n_moved = 0
        resx = ltf("page.resx") or 600.0
        for r in infos:
            box = frame_px(r, infos, page_px)
            if box is None:
                continue
            lt(f"page.active={r['i']};")
            moved = clamp_texts(g[r["i"] - 1], box,
                                pad_px=0.05 / 2.54 * resx,
                                legend_pad_px=0.12 / 2.54 * resx)
            # 先收边再互推：收边可能把两个标注挤到一起，反过来则会把刚推开的
            # 又压回边界。互推只动垂直方向，不会破坏收边的左右结果。
            moved += separate_texts(g[r["i"] - 1], box, gap_px=0.03 / 2.54 * resx)
            if moved:
                n_moved += len(moved)
                for m in moved:
                    print(f"  [fix r{rnd + 1}] L{r['i']} {m}")
        if not n_moved:
            break
    try:
        os.remove(dummy)
    except OSError:
        pass

    op.save(out_opju)
    print(f"origin_project={out_opju}")
    px = int(round(pw / 2.54 * STYLE["dpi"]))
    try:
        g.save_fig(out_png, type="png", width=px)
        print(f"png={out_png} ({px}px wide = {STYLE['dpi']} dpi at {pw:.2f} cm)")
    except Exception:
        traceback.print_exc()

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "work", "format_composite_report.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        op.exit()
