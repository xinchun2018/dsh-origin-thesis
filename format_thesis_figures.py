# -*- coding: utf-8 -*-
r"""Batch-format Origin graphs to a uniform PhD-thesis figure style.

按博士论文插图规范统一 Origin 项目中所有 Graph 的页面尺寸、排版、字体与字号：

- 单图 (1 layer)  : 页面 9.0 x 7.0 cm
- 双图 (2 layers) : 页面 16.0 x 7.0 cm，1x2 排列，自动加 (a)(b) 标签
- 四图 (4 layers) : 页面 16.0 x 12.4 cm，2x2 排列，自动加 (a)-(d) 标签
- 其他数量的 layer 按通用规则排网格

字体统一为 Times New Roman：刻度 9 pt、轴标题 10.5 pt 粗体、
面板标签 12 pt 粗体、峰位/晶面指标 8 pt、图内文字 9 pt、图例 9 pt。
轴线与主/次刻度线粗细统一 1.0 pt，显示的主/次刻度一律朝内。
数据、坐标轴范围、插图(TEM 等图片对象)一律不动。

原文件不会被修改：结果另存为 <原名>_thesis.opju，并按 600 dpi 实际尺寸导出 PNG。

用法:
  C:\Users\liuxc\miniconda3\envs\origin\python.exe format_thesis_figures.py ^
      --project "C:\path\to\UNTITLED.opju" [--out-dir DIR] [--dpi 600] [--font "Times New Roman"]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import traceback

sys.stdout.reconfigure(encoding="utf-8")

import originpro as op

try:                                  # 版面自检（量测渲染图裁切）用
    import numpy as np
    from PIL import Image
except Exception:                     # 没装就跳过自检，其余功能不受影响
    np = None
    Image = None

# ----------------------------- 样式配置 ---------------------------------- #
STYLE = {
    "font": "Times New Roman",   # 全图统一字体（西文）
    "tick_pt": 9,                # 坐标刻度数字
    "axis_title_pt": 10.5,       # 轴标题（五号）
    "axis_title_bold": True,
    "panel_pt": 12,              # (a)(b)(c)(d) 面板标签，粗体
    "annot_pt": 8,               # 图内标注：晶面指标、Experiment/Simulation 等
    "legend_pt": 9,              # 图例
    "axis_thickness": 1.0,       # 轴线与主/次刻度线粗细 (pt)
    "tick_length": 3.6,          # 主刻度线长度 (pt)
    "line_pt": 1.0,              # 曲线线宽 (pt)
    "symbol_pt": 4,              # 数据点符号大小 (pt)，无符号的图为空操作
    "move_legend": True,         # 图例是否移到框架右上角（原位手工摆好的图关掉）
    "export_dpi": 600,
}

# 每种 layer 数量对应的页面尺寸(cm)与网格。
# 页面高度按保持绘图区宽高比 ~1.257（与原图一致）取值，
# 使贴在坐标系上的标注与贴在图层框架上的插图保持原有相对位置。
# 单图为 4:3 规格（审稿回复用）：页面 98.594x73.999 mm、
# 图层框架 (1.499, 0.5503, 7.59, 5.698) cm，由 margins 精确给出。
LAYOUTS = {
    1: {"rows": 1, "cols": 1, "page": (9.8594, 7.3999),
        "margins": {"left": 1.499, "right": 0.7704,
                    "top": 0.5503, "bottom": 1.1516}},
    2: {"rows": 1, "cols": 2, "page": (16.0, 7.4)},
    3: {"rows": 2, "cols": 2, "page": (16.0, 13.2)},
    4: {"rows": 2, "cols": 2, "page": (16.0, 13.2)},
    6: {"rows": 2, "cols": 3, "page": (16.0, 10.4)},
    8: {"rows": 2, "cols": 4, "page": (16.0, 8.6)},
}

# 每个网格单元内部的边距(cm)：给轴标题/刻度留位置
CELL_MARGIN = {"left": 1.50, "right": 0.32, "top": 0.55, "bottom": 1.15}

# 名字以这些前缀开头的图形对象视为插入的图片（TEM 照片、结构式等）：
# 图片对象不随 layer 缩放，需按新旧 layer 尺寸比例手动缩放。
# `__OLECnt*` 是从 Word 里粘进来的 OLE 对象（ChemDraw 结构式等），同样不缩放。
IMAGE_PREFIXES = ("EMF", "DIB", "IMG", "IMAGE", "PIC", "__OLECNT")

# 轴标题与系统对象：不参与"页面锚定重映射"（轴标题由脚本单独定位）
SKIP_OBJ_NAMES = {"XB", "YL", "XT", "YR", "3D", "OR", "OT", "FL", "X1T"}

# 图形对象的 attach 取值：0=图层框架、1=页面、2=图层与坐标轴
ATTACH_PAGE = 1

PANEL_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# 个别图的收尾微调（该图格式化完成后调用，传入 GPage；LabTalk 表达式里
# 内嵌属性求值不可靠，数值一律在 Python 里读出算好再写常量）
def _tweak_figS27(gpage) -> None:
    """分类刻度标签过挤：旋转 30°，压缩 layer 高度，轴标题下移让位。

    rotate 会让轴标题在下一次渲染时自动重排（覆盖手工位置），必须先
    强制渲染一次消耗掉这次重排，再写标题位置。"""
    lt("page.active = 1;")
    lt("layer.unit = 3;")
    lt("layer.height = 4.50;")
    lt("layer.x.label.rotate = 30;")
    yf, yt, h = ltf("layer.y.from"), ltf("layer.y.to"), ltf("layer.height")
    if None in (yf, yt, h) or not h or yt == yf:
        return
    target = yf - 1.90 / h * (yt - yf)
    tmp = os.path.join(tempfile.gettempdir(), "_origin_fmt_dummy.png")
    # rotate 后的第一次渲染会自动重排轴标题、覆盖手工位置——
    # 写入→渲染→读回校验，直到位置保住为止。
    for _ in range(4):
        lt(f"xb.y = {target:.8g};")
        try:
            gpage.save_fig(tmp, type="png", width=300)
        except Exception as exc:
            print(f"  [warn] FigS27 dummy render failed: {exc}")
        got = ltf("xb.y")
        if got is not None and abs(got - target) < abs(yt - yf) * 0.02:
            break
    else:
        print(f"  [warn] FigS27 xb.y unstable: want {target:.4g} got {ltf('xb.y')}")
    try:
        os.remove(tmp)
    except OSError:
        pass


def _tweak_figS16(gpage) -> None:
    """图例默认位置（右上）与曲线平台期重叠，挪到右下空白区。"""
    lt("page.active = 1;")
    xf, xt_, yf, yt = (ltf("layer.x.from"), ltf("layer.x.to"),
                       ltf("layer.y.from"), ltf("layer.y.to"))
    if None not in (xf, xt_, yf, yt):
        lt(f"legend.x = {xf + 0.72 * (xt_ - xf):.8g}; "
           f"legend.y = {yf + 0.30 * (yt - yf):.8g};")


def _tweak_graph8(gpage) -> None:
    """分类轴刻度标签是很长的催化剂名（10%MIL-101(Cr)-TiO2 等）：改 45°
    旋转并压低框架高度，否则标签会越过页面下边缘被裁掉。45° 比 30° 的
    水平伸展短 1/3，最左那条也就不会顶出页面左边缘。"""
    lt("page.active = 1;")
    lt("layer.x.label.rotate = 45;")
    lt("layer.unit = 3;")
    lt("layer.height = 4.05;")


def _tweak_graph12(gpage) -> None:
    """FTIR 谱标注密集：框架缩窄后（字号是绝对 pt，文字相对面板变大）
    官能团标签 C-N 与 Ti-O-C 挤到一起连成 "C-NTi-O-C"，把 C-N 下移
    一行错开（不动 Ti-O-C：它上面紧挨着乙酸结构式图片）。只在**纵向**
    挪——横坐标指着具体峰位，左右挪会指错峰。"""
    lt("page.active = 1;")
    lt("layer.unit = 3;")
    yf, yt, h = ltf("layer.y.from"), ltf("layer.y.to"), ltf("layer.height")
    cur = ltf("Text13.y")
    if None in (yf, yt, h, cur) or not h or yt == yf:
        print("  [warn] Graph12 tweak: 读不到 Text13.y / 轴范围")
        return
    target = cur - 0.36 / h * (yt - yf)
    lt(f"Text13.y = {target:.8g};")
    got = ltf("Text13.y")
    if got is None or abs(got - target) > abs(yt - yf) * 0.02:
        print(f"  [warn] Graph12 C-N 下移未生效: want {target:.4g} got {got}")


def _tweak_graph16(gpage) -> None:
    """XPS Ti 2p：顶面板右上角的谱线标签 "Ti 2p" 与结合能标注
    "459.02 eV" 挤成一串，把 Ti 2p 下移错开（该处曲线是平基线，空的）。"""
    lt("page.active = 1;")
    lt("layer.unit = 3;")
    yf, yt, h = ltf("layer.y.from"), ltf("layer.y.to"), ltf("layer.height")
    cur = ltf("Text14.y")
    if None in (yf, yt, h, cur) or not h or yt == yf:
        print("  [warn] Graph16 tweak: 读不到 Text14.y / 轴范围")
        return
    target = cur - 0.25 / h * (yt - yf)
    lt(f"Text14.y = {target:.8g};")
    got = ltf("Text14.y")
    if got is None or abs(got - target) > abs(yt - yf) * 0.02:
        print(f"  [warn] Graph16 Ti 2p 下移未生效: want {target:.4g} got {got}")


# 微调按**项目**分组：短名 Graph8/Graph12/… 在不同项目里是完全不同的图，
# 只按图名匹配会张冠李戴（把 45° 旋转刻度标签套到别的项目的动力学曲线上）。
# 外层 key 是输入 .opju 的文件名主干。
PER_GRAPH_TWEAKS = {
    "Revised SupportingInformation_graphs": {
        "FigS27": _tweak_figS27,
        "FigS16": _tweak_figS16,
    },
    "Revised manuscript_graphs": {
        "Graph8": _tweak_graph8,
        "Graph12": _tweak_graph12,
        "Graph16": _tweak_graph16,
    },
}


# ------------------------- LabTalk 小工具 -------------------------------- #

def lt(cmd: str) -> None:
    try:
        op.lt_exec(cmd)
    except Exception as exc:
        print(f"  [warn] lt_exec failed: {cmd!r} -> {exc}")


def ltf(expr: str):
    try:
        return op.lt_float(expr)
    except Exception:
        return None


# --------------------- Origin 文本转义串处理 ------------------------------ #
# 轴标题/标注常见形如 \b(\f:Arial(\p126(2θ (degree))))
# 统一字体字号时需剥掉 \f:字体(...) 与 \pNN(...) 包装，仅保留内容本身，
# 粗体统一用外层 \b(...) 表达。\ab() 上划线等内部转义原样保留。
_WRAP_RE = re.compile(r"^\\(b|f:[^()\\]+|p\d+)\(")


def _balanced_inner(text: str, start: int) -> str | None:
    """text[start:] 应以内容开头且整体以 ')' 收尾构成配平括号，返回内层内容。"""
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2  # 跳过转义对，如 \( \)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i] if i == len(text) - 1 else None
        i += 1
    return None


def unwrap_escapes(text: str) -> tuple[str, bool]:
    """剥掉最外层的 \b / \f:xxx / \pNN 包装，返回 (内容, 是否有粗体)。"""
    bold = False
    changed = True
    while changed:
        changed = False
        m = _WRAP_RE.match(text)
        if not m:
            break
        inner = _balanced_inner(text, m.end())
        if inner is None:
            break
        if m.group(1) == "b":
            bold = True
        text = inner
        changed = True
    return text.strip(), bold


_PANEL_RE = re.compile(r"^\(\s*[a-zA-Z]\s*\)$")
_INDEX_RE = re.compile(r"^[\\()\d\s.\-]*\d[\\()\d\s.\-]*$")  # 纯数字/括号/空格 → 晶面指标类

_OPEN_RE = re.compile(r"\\(b|f:[^()\\]+|p\d+)\(")
_LITERAL_RE = re.compile(r"\\\(\d+\)")   # \(40) \(41) 等字面括号转义


def _match_paren(text: str, start: int) -> int:
    """返回与 start 前一个 '(' 配对的 ')' 下标（处理 \(40) 字面括号与转义对）。"""
    depth = 1
    i = start
    while i < len(text):
        m = _LITERAL_RE.match(text, i)
        if m:
            i = m.end()
            continue
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def strip_font_escapes(text: str) -> tuple[str, bool]:
    """删除文本中任意位置的 \b / \f:字体 / \pNN 包装（unwrap_escapes 只能
    剥整串包装，标题内部的局部 \pNN(...) 仍会覆盖字号），保留内容与
    其他转义（\+ \- \i \g \ab 及 \(40) 字面括号）。

    \g(...) 区域整体原样保留：其内容按 Symbol 字体渲染，内部常有
    \f:Times(...) 把个别字符切回正常字体（如 `130\g(°\f:Times New Roman(C))`），
    剥掉这层内部包装会让 C 变成希腊字母 Chi。

    返回 (内容, 是否有粗体)。"""
    out: list[str] = []
    stack: list[bool] = []   # True = 该层右括号来自被剥除的包装
    bold = False
    i = 0
    while i < len(text):
        if text.startswith("\\g(", i):
            j = _match_paren(text, i + 3)
            if j != -1:
                out.append(text[i:j + 1])
                i = j + 1
                continue
        m = _LITERAL_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        m = _OPEN_RE.match(text, i)
        if m:
            if m.group(1) == "b":
                bold = True
            stack.append(True)
            i = m.end()
            continue
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == "(":
            out.append(ch)
            stack.append(False)
            i += 1
            continue
        if ch == ")":
            if not (stack and stack.pop()):
                out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out).strip(), bold


def classify_annotation(payload: str) -> str:
    if _PANEL_RE.match(payload):
        return "panel"
    core = payload.replace("\\(40)", "(").replace("\\(41)", ")")
    core = re.sub(r"\\ab\(([^)]*)\)", r"\1", core)  # 上划线转义只看内容
    core = core.strip("() ")
    if core and _INDEX_RE.match(core):
        return "index"
    return "text"


def is_legend_like(name: str, raw: str) -> bool:
    """图例（或用 Text 对象手搓的图例）——文本绝对不能改写。

    图例串按 `|`/换行切条目后**逐条**解析转义，整串外包 `\\b()` 会让第 1 条
    变粗体、最后一条尾巴多一个 `)`。对象名不一定是 Legend：作者常复制一个
    文本对象当第二个图例（本项目 Fig8 的 `Text`、Graph4 的 `Text`），判据是
    含曲线标识转义 `\\l(n)`。"""
    if name.upper().startswith("LEGEND"):
        return True
    return "\\l(" in raw


# ----------------------------- 主逻辑 ------------------------------------ #

def grid_for(nlayers: int) -> dict:
    if nlayers in LAYOUTS:
        return dict(LAYOUTS[nlayers])
    cols = 1 if nlayers == 1 else (2 if nlayers <= 4 else 3)
    rows = (nlayers + cols - 1) // cols
    width = 9.0 if cols == 1 else 16.0
    height = rows * (7.0 if rows == 1 else 6.2)
    return {"rows": rows, "cols": cols, "page": (width, height)}


def set_page_size_cm(width_cm: float, height_cm: float) -> None:
    """page.width/height 单位是 resx/resy dpi 像素。LabTalk 表达式赋值
    会把小数截断（9.8594 cm 算出 2328.99 存成 2328，读回 98.552 mm），
    像素数在 Python 里 round 好写整数常量。"""
    resx = ltf("page.resx") or 600.0
    resy = ltf("page.resy") or 600.0
    lt(f"page.width = {int(round(width_cm / 2.54 * resx))};")
    lt(f"page.height = {int(round(height_cm / 2.54 * resy))};")


def cell_rect(layout: dict, idx0: int,
              margins: dict | None = None) -> tuple[float, float, float, float]:
    """第 idx0 个(0 起) layer 的绘图区 (left, top, width, height)，单位 cm。"""
    rows, cols = layout["rows"], layout["cols"]
    page_w, page_h = layout["page"]
    cell_w, cell_h = page_w / cols, page_h / rows
    r, c = divmod(idx0, cols)
    m = margins or CELL_MARGIN
    left = c * cell_w + m["left"]
    top = r * cell_h + m["top"]
    width = cell_w - m["left"] - m["right"]
    height = cell_h - m["top"] - m["bottom"]
    return left, top, width, height


def font_index(name: str) -> int:
    lt(f"double __fidx = font({name});")
    v = ltf("__fidx")
    return int(v) if v and v == v else 1


def iter_text_objects(glayer):
    """yield (pyorigin_obj, name, raw_text)，仅文本类对象。"""
    try:
        objs = list(glayer.obj.GraphObjects)
    except Exception:
        return
    for o in objs:
        try:
            name = o.GetName()
            text = o.Text or ""
        except Exception:
            continue
        if text:
            yield o, name, text


def set_obj_num(obj, prop: str, value) -> bool:
    """通过 PyOrigin 句柄设置数值属性，避开 LabTalk 名字路径的
    保留字冲突（如对象名恰为 'Text' 时 `Text.fsize=` 会静默失败）。"""
    try:
        obj.SetNumProp(prop, value)
        return True
    except Exception as exc:
        print(f"  [warn] SetNumProp({prop}) failed on "
              f"{getattr(obj, 'GetName', lambda: '?')()}: {exc}")
        return False


def format_plots(glayer) -> None:
    """统一本 layer 所有曲线的线宽与符号大小。

    LabTalk `set -w` 的单位是 1/500 pt（实测 -w 500 在 600dpi 下渲染
    8px ≈ 1pt）；`set -z` 直接是 pt。柱状图 -w 设的是边框宽度，
    无符号的图 -z 是无害空操作。plot 句柄跨渲染会失效，须单趟使用。"""
    s = STYLE
    try:
        plots = glayer.plot_list()
    except Exception:
        return
    for dp in plots:
        try:
            dp.set_cmd(f"-w {int(round(s['line_pt'] * 500))}",
                       f"-z {s['symbol_pt']}")
        except Exception as exc:
            print(f"  [warn] set plot style failed: {exc}")


def format_layer_axes(font_idx: int, keep_size: bool = False) -> None:
    s = STYLE
    # 对四条轴统一刻度标签、线宽与刻度样式（x2/y2 是顶轴/右轴：
    # 双 Y 轴图的右轴刻度标签属于 y2，不能只设 x/y）
    for ax in ("x", "x2", "y", "y2"):
        # keep_size：插图层的刻度数字不放大（插图框只有几毫米宽，放大到
        # 正文字号会把相邻标签压成一团），只统一字体，字号取原值与正文
        # 字号的较小者。
        pt = s["tick_pt"]
        if keep_size:
            cur = ltf(f"layer.{ax}.label.pt")
            if cur is not None and cur == cur and cur > 0:
                pt = min(pt, cur)
        lt(f"layer.{ax}.label.pt = {pt};")
        lt(f"layer.{ax}.label.font = {font_idx};")
        lt(f"layer.{ax}.thickness = {s['axis_thickness']};")
        lt(f"layer.{ax}.tickThickness = {s['axis_thickness']};")   # 主刻度线粗细
        lt(f"layer.{ax}.mtickThickness = {s['axis_thickness']};")  # 次刻度线粗细
        lt(f"layer.{ax}.tickLength = {s['tick_length']};")
        # layer.axis.ticks 是位掩码：1=主刻度朝内 2=主刻度朝外
        # 4=次刻度朝内 8=次刻度朝外。凡显示的刻度一律改为朝内，
        # 未显示的（对应位为 0）保持隐藏。
        ticks = ltf(f"layer.{ax}.ticks")
        if ticks is not None and ticks == ticks:
            t = int(ticks)
            inward = (1 if t & 3 else 0) | (4 if t & 12 else 0)
            if inward != t:
                lt(f"layer.{ax}.ticks = {inward};")


def format_text_objects(glayer, font_idx: int,
                        remove_panels: bool = True,
                        keep_size: bool = False) -> tuple[int, list[str], bool, bool, bool]:
    """统一本 layer 所有文本对象；返回
    (删除的面板标签数, 其字母, 是否有可见 YR, 是否有可见 XB, 是否有可见 YL)。

    remove_panels=False 时（保持原排版的特殊图）面板标签不删除，
    只统一为面板字号/粗体。
    keep_size=True 时（插图层）字号只缩不放：插图框只有几毫米宽，
    把里面的标注放大到正文字号会互相压成一团。
    """
    s = STYLE

    def size(o, target: float) -> float:
        if not keep_size:
            return target
        try:
            cur = o.GetNumProp("fsize")
        except Exception:
            return target
        return min(target, cur) if cur and cur == cur else target

    removed = 0
    letters: list[str] = []
    yr_real = False
    xb_real = False
    yl_real = False
    for o, name, raw in iter_text_objects(glayer):
        upper = name.upper()
        if upper == "3D":
            continue
        if upper in ("XB", "YL", "XT", "YR"):
            # XT/YR 多为占位符（空白或 %(?X)），但双 Y 轴图的右轴标题、
            # 以及"X 轴反向 + 标题挂在右轴"的图（本项目 FTIR/XPS/NMR）
            # 的可见 Y 标题就是 YR 对象，需与 XB/YL 同样处理。
            # 含 %( 替换串的标题（如 %(?X) 占位符）不能改写文本，
            # 包进 \b() 会破坏替换导致标题消失；只统一字体字号。
            if "%(" not in raw and raw.strip():
                if upper == "YR":
                    yr_real = True
                elif upper == "XB":
                    xb_real = True
                elif upper == "YL":
                    yl_real = True
                payload, _ = strip_font_escapes(raw)
                new_text = f"\\b({payload})" if s["axis_title_bold"] else payload
                if new_text != raw:
                    try:
                        o.Text = new_text
                    except Exception:
                        pass
            set_obj_num(o, "fsize", size(o, s["axis_title_pt"]))
            set_obj_num(o, "font", font_idx)
            continue
        if is_legend_like(name, raw):
            set_obj_num(o, "fsize", size(o, s["legend_pt"]))
            set_obj_num(o, "font", font_idx)
            continue
        payload, bold = strip_font_escapes(raw)
        kind = classify_annotation(payload)
        if kind == "panel":
            if remove_panels:
                try:
                    o.Destroy()
                    removed += 1
                    letters.append(re.sub(r"[^a-zA-Z]", "", payload))
                except Exception:
                    lt(f"label -r {name};")
                continue
            set_obj_num(o, "fsize", size(o, s["panel_pt"]))
            set_obj_num(o, "font", font_idx)
            continue
        new_text = f"\\b({payload})" if bold else payload
        if new_text != raw:
            try:
                o.Text = new_text
            except Exception:
                pass
        set_obj_num(o, "fsize", size(o, s["annot_pt"]))
        set_obj_num(o, "font", font_idx)
    return removed, letters, yr_real, xb_real, yl_real


def add_panel_label(gpage, layer_i: int, letter: str, font_idx: int) -> None:
    """在 layer 框架左上角外侧放置 (a)(b)... 标签。

    先用 `label -p`（框架内百分比）创建并命名，再通过对象的 .x/.y
    属性（轴坐标，锚点为文本中心）移到框架外的页边距区域。
    仅适用于线性轴；读不到轴范围时标签留在框架内左上角。
    """
    m = CELL_MARGIN
    lt(f"page.active={layer_i};")
    xf, xt = ltf("layer.x.from"), ltf("layer.x.to")
    yf, yt = ltf("layer.y.from"), ltf("layer.y.to")
    w, h = ltf("layer.width"), ltf("layer.height")  # layer.unit=3 → cm
    name = f"ThPanel{letter}"
    lt(f'label -p 2 3 -n {name} "\\b(({letter}))";')
    for o, oname, _ in iter_text_objects(gpage[layer_i - 1]):
        if oname == name:
            set_obj_num(o, "fsize", STYLE["panel_pt"])
            set_obj_num(o, "font", font_idx)
            break
    vals = [xf, xt, yf, yt, w, h]
    if all(v is not None and v == v for v in vals) and w > 0 and h > 0 and xt != xf and yt != yf:
        # 目标：标签中心位于框架左缘外 0.98 cm、上缘外 0.24 cm
        x_ax = xf - 0.98 / w * (xt - xf)
        y_ax = yt + 0.24 / h * (yt - yf)
        lt(f"{name}.x = {x_ax:.8g}; {name}.y = {y_ax:.8g};")
        rx, ry = ltf(f"{name}.x"), ltf(f"{name}.y")
        if rx is None or abs(rx - x_ax) > abs(xt - xf) * 0.05:
            print(f"  [warn] panel label {name} position readback: "
                  f"want ({x_ax:.4g},{y_ax:.4g}) got ({rx},{ry})")


def verify_graph(gpage, font_idx: int, small_layers: set[int] | None = None) -> list[str]:
    """检查所有文本对象字号/字体是否为预期值，返回异常描述。

    small_layers 里的 layer 号是插图层：其字号只缩不放（见
    format_text_objects 的 keep_size），比正文字号小属于预期。
    """
    s = STYLE
    expected = {float(s["annot_pt"]), float(s["legend_pt"]),
                float(s["axis_title_pt"]), float(s["panel_pt"])}
    small = small_layers or set()
    issues = []
    for li in range(len(gpage)):
        for o, name, _ in iter_text_objects(gpage[li]):
            if name.upper() == "3D":
                continue
            try:
                fs = float(o.GetNumProp("fsize"))
                fo = int(o.GetNumProp("font"))
            except Exception:
                continue
            if fs not in expected and not (li + 1 in small and fs <= max(expected)):
                issues.append(f"{gpage.name} L{li+1} {name}: fsize={fs}")
            elif fo != font_idx:
                issues.append(f"{gpage.name} L{li+1} {name}: font={fo}")
    return issues


def snapshot_objects(glayer) -> list:
    """记录本 layer 所有可移动对象的句柄与设计矩形(600dpi 页面像素)。

    三种锚定各有不同的修正需求：
    - 图片(EMF/DIB/__OLECnt…)：物理尺寸固定、不随 layer 缩放，要按比例改宽高；
    - 页面锚定：存储坐标是**实时值**（改页面尺寸后按页面比例跟着变），
      layer 换位置后会跑到别处，必须按框架比例重新映射；
    - 框架/坐标轴锚定：存储坐标是**陈旧缓存**，渲染自动跟随 layer，不能动。
    区分靠"写完几何后存储坐标是否变化"。
    """
    out = []
    try:
        objs = list(glayer.obj.GraphObjects)
    except Exception:
        return out
    for o in objs:
        try:
            name = str(o.GetName())
            up = name.upper()
            is_img = up.startswith(IMAGE_PREFIXES)
            if is_img and o.Text:
                is_img = False
            if not is_img and (up in SKIP_OBJ_NAMES or up.startswith("_")):
                continue   # 轴标题/系统对象（脚本另行处理或不该动）
            l, t, w, h = o.GetLeft(), o.GetTop(), o.GetWidth(), o.GetHeight()
            try:
                attach = int(o.GetNumProp("attach"))
            except Exception:
                attach = -1
            out.append({"o": o, "name": name,
                        "img": bool(is_img and w > 0 and h > 0),
                        "page": attach == ATTACH_PAGE,
                        "rect": (l, t, w, h)})
        except Exception:
            continue
    return out


def fix_objects(objs: list, old_rect, new_rect, px_per_cm: float) -> list:
    """layer 从 old_rect 移到 new_rect(cm) 后修正对象：图片等比缩放；
    页面锚定的对象按框架比例重新映射位置。见 snapshot_objects 的说明。

    图片宽高统一用 min(sx, sy) 等比缩放——新旧 layer 宽高比不同时按轴
    分别缩放会拉变形。

    返回 [(对象, 目标left_px, 目标top_px)]：位置的第一次写入会被 Origin
    用旧页面几何换算歪掉，须由 settle_objects() 渲染一次后重写。
    """
    ol, ot, ow, oh = old_rect
    nl, nt, nw, nh = new_rect
    if ow <= 0 or oh <= 0:
        return []
    s = min(nw / ow, nh / oh)
    pending = []
    for rec in objs:
        o = rec["o"]
        l0, t0, w0, h0 = rec["rect"]
        try:
            if rec["img"]:
                o.SetWidth(max(1, int(round(w0 * s))))
                o.SetHeight(max(1, int(round(h0 * s))))
            # 页面锚定判据以 attach 属性为准：存储坐标的"实时值"其实是
            # 惰性刷新的——没对对象做过写操作时（纯文本对象）读回的还是
            # 改页面尺寸前的旧像素，光靠"坐标是否变化"会漏判。
            if not rec["page"] and (o.GetLeft(), o.GetTop()) == (l0, t0):
                continue   # 框架/轴锚定：存储坐标是陈旧缓存，渲染自动跟随
            rel_x = (l0 / px_per_cm - ol) / ow
            rel_y = (t0 / px_per_cm - ot) / oh
            lpx = int(round((nl + rel_x * nw) * px_per_cm))
            tpx = int(round((nt + rel_y * nh) * px_per_cm))
            o.SetLeft(lpx)
            o.SetTop(tpx)
            pending.append((o, lpx, tpx))
        except Exception as exc:
            print(f"  [warn] fix object {rec['name']} failed: {exc}")
    return pending


def settle_objects(gpage, pending: list, rounds: int = 3) -> None:
    """页面锚定对象位置的"写入→渲染→重写"闭环。

    实测：改完页面尺寸后第一次 SetLeft 会被按旧页面几何换算，读回值与
    写入值不符（写 1812 读回 518）；渲染一次刷新内部几何后重写才生效。
    """
    if not pending:
        return
    tmp = os.path.join(tempfile.gettempdir(), "_origin_settle.png")
    for _ in range(rounds):
        try:
            gpage.save_fig(tmp, type="png", width=300)
        except Exception as exc:
            print(f"  [warn] settle render failed: {exc}")
            return
        bad = []
        for o, lpx, tpx in pending:
            try:
                if (o.GetLeft(), o.GetTop()) != (lpx, tpx):
                    o.SetLeft(lpx)
                    o.SetTop(tpx)
                    bad.append((o, lpx, tpx))
            except Exception:
                continue
        if not bad:
            break
        pending = bad
    else:
        print("  [warn] 有页面锚定对象位置未写稳: " +
              ", ".join(str(o.GetName()) for o, _, _ in pending))
    try:
        os.remove(tmp)
    except OSError:
        pass


def reposition_axis_titles(w_cm: float | None = None, h_cm: float | None = None,
                           yr_real: bool = False) -> None:
    """把轴标题移到与坐标轴的标准距离处（统一版式）。

    XB/YL 的 .x/.y 是轴坐标（锚点为文本中心），据当前 layer 的
    cm 尺寸与轴范围换算出目标位置。仅线性轴适用。

    w_cm/h_cm：显式给出框架 cm 尺寸——unit=7 的链接层不能切 unit 去读
    （切 unit 是转换存储值，会破坏相对坐标），几何由调用方算好传入。

    yr_real：本 layer 的 YR 是可见的 Y 轴标题（双 Y 轴的右标题，或
    X 轴反向图里挂在右轴上、实际显示在左边的标题）。只归一化它到
    框架外的统一距离（写 .x），**不动 .y**：堆叠图的 YR 竖跨整个
    堆叠，重置 y 会把它塌到单个面板中心。`yr.text$` 在部分项目里读不到，
    可见性由 format_text_objects 从对象文本判定后传进来。
    """
    xf, xt = ltf("layer.x.from"), ltf("layer.x.to")
    yf, yt = ltf("layer.y.from"), ltf("layer.y.to")
    if w_cm is None or h_cm is None:
        w, h = ltf("layer.width"), ltf("layer.height")  # layer.unit=3 → cm
    else:
        w, h = w_cm, h_cm
    vals = [xf, xt, yf, yt, w, h]
    if not all(v is not None and v == v for v in vals) or not w or not h \
            or xt == xf or yt == yf:
        return
    xspan, yspan = xt - xf, yt - yf
    x_labels = (ltf("layer.x.showLabels") or 0) > 0
    y_labels = (ltf("layer.y.showLabels") or 0) > 0
    dy_cm = 0.80 if x_labels else 0.55   # X 轴标题中心距框架下缘
    dx_cm = 0.95 if y_labels else 0.55   # Y 轴标题中心距框架左缘
    if ltf("xb.fsize") is not None and (ltf("xb.fsize") == ltf("xb.fsize")):
        lt(f"xb.x = {(xf + xt) / 2:.8g}; xb.y = {yf - dy_cm / h * yspan:.8g};")
    if ltf("yl.fsize") is not None and (ltf("yl.fsize") == ltf("yl.fsize")):
        lt(f"yl.x = {xf - dx_cm / w * xspan:.8g}; yl.y = {(yf + yt) / 2:.8g};")
    # 可见的右轴标题（YR）：只归一化横向距离。X 轴反向时 xt 端渲染在
    # 左边，同一个公式给出的就是视觉左侧的统一距离。
    yr_show = (ltf("layer.y2.showLabels") or 0) > 0
    dr_cm = 0.95 if yr_show else 0.55
    try:
        yr_text = op.lt_str("yr.text$") or ""
    except Exception:
        yr_text = ""
    visible_yr = yr_real or (yr_text.strip() and "%(" not in yr_text)
    if visible_yr and ltf("yr.fsize") is not None and \
            (ltf("yr.fsize") == ltf("yr.fsize")):
        lt(f"yr.x = {xt + dr_cm / w * xspan:.8g};")


def reposition_legend() -> None:
    """图例移入框架右上角（存在图例时）。"""
    if not STYLE.get("move_legend", True):
        return
    fs = ltf("legend.fsize")
    if fs is None or fs != fs:
        return
    xf, xt = ltf("layer.x.from"), ltf("layer.x.to")
    yf, yt = ltf("layer.y.from"), ltf("layer.y.to")
    if None in (xf, xt, yf, yt) or xt == xf or yt == yf:
        return
    lt(f"legend.x = {xf + 0.80 * (xt - xf):.8g}; "
       f"legend.y = {yf + 0.88 * (yt - yf):.8g};")


def _runs(flags) -> list[tuple[int, int]]:
    """把布尔序列切成连续 True 的区间 [(起, 止), ...]。"""
    runs, b0, inb = [], 0, False
    for i, v in enumerate(flags):
        if v and not inb:
            b0, inb = i, True
        elif not v and inb:
            runs.append((b0, i))
            inb = False
    if inb:
        runs.append((b0, len(flags)))
    return runs


def _zone_bands(png: str, page_cm, frame_cm, side: str) -> tuple[list, float]:
    """量测框架某一侧的墨迹条带，返回 ([(近端, 远端) cm], 可用空白 cm)。

    距离一律以"离框架该侧边缘多远"计（越大越远离框架）。
    - side='below'：只看框架横向范围内的列（避开 Y 轴标签/标题）；
    - side='left'/'right'：只看框架纵向范围内的行（避开 X 轴标签/标题）。
    """
    ink = np.array(Image.open(png).convert("L")) < 250
    H, W = ink.shape
    fl, ft, fw, fh = frame_cm
    ppx, ppy = W / page_cm[0], H / page_cm[1]
    c0, c1 = max(0, int(fl * ppx)), min(W, int(round((fl + fw) * ppx)))
    r0, r1 = max(0, int(ft * ppy)), min(H, int(round((ft + fh) * ppy)))
    if side == "below":
        edge = int(round((ft + fh) * ppy)) + 2       # 跳过框架线本身
        if edge >= H or c1 <= c0:
            return [], 0.0
        bands = [(a / ppy, b / ppy) for a, b in _runs(ink[edge:, c0:c1].any(1))]
        return bands, (H - edge) / ppy
    if r1 <= r0:
        return [], 0.0
    if side == "left":
        edge = max(0, int(fl * ppx) - 2)
        if edge <= 0:
            return [], 0.0
        cols = _runs(ink[r0:r1, :edge].any(0))
        # 绝对列 → 离框架左缘的距离（近端在前）
        bands = sorted(((edge - b) / ppx, (edge - a) / ppx) for a, b in cols)
        return bands, edge / ppx
    edge = min(W, int(round((fl + fw) * ppx)) + 2)
    if edge >= W:
        return [], 0.0
    cols = _runs(ink[r0:r1, edge:].any(0))
    return [(a / ppx, b / ppx) for a, b in cols], (W - edge) / ppx


def _fit_title(gpage, layer_i: int, page_cm, frame_cm, side: str,
               write, name: str, gap: float = 0.12,
               min_near: float = 0.16, quiet: bool = False) -> bool:
    """把一个轴标题放到"刻度标签之外 gap cm"处——按渲染结果标定。

    `xb.y`/`yl.x` 的锚点语义因图而异（同为 10.5 pt 标题，实测同一个写入值
    在不同图上渲染位置差 0.3 cm 上下），照固定 cm 距离写会有一批图的标题
    压在刻度数字上。这里不猜锚点：

    1. 先把标题写到页面外（渲染时被裁掉），量出刻度标签的外缘 `tb`；
    2. 写一个探测值 d0，量出标题墨迹的近端，得到锚点偏移 k = d0 - 近端
       与标题厚度（写入值与渲染位置是 1:1 平移，实测斜率为 1）；
    3. 目标近端 = max(tb + gap, min_near)，越界则往回收，写入 d = 近端 + k。

    `write(d)` 负责把"离框架边缘 d cm"换算成轴坐标写进对象。
    量测/标定失败返回 False（此时对象停在探测位置，调用方须写回原值）。
    """
    if Image is None:
        return False
    tmp = os.path.join(tempfile.gettempdir(), f"_origin_fit_{side}.png")
    px = max(400, int(round(page_cm[0] / 2.54 * 300)))

    def render() -> bool:
        try:
            gpage.save_fig(tmp, type="png", width=px)
            return True
        except Exception as exc:
            print(f"  [warn] {name} fit render failed: {exc}")
            return False

    def bands():
        try:
            return _zone_bands(tmp, page_cm, frame_cm, side)
        except Exception as exc:
            print(f"  [warn] {name} fit measure failed: {exc}")
            return None, None

    lt(f"page.active={layer_i};")
    avail = (page_cm[1] - (frame_cm[1] + frame_cm[3])) if side == "below" else (
        frame_cm[0] if side == "left"
        else page_cm[0] - (frame_cm[0] + frame_cm[2]))
    if avail <= 0.2:
        return False

    write(avail + 1.5)                       # 标题挪出页面
    if not render():
        return False
    bs, avail_px = bands()
    if bs is None:
        return False
    tick_far = max((f for _, f in bs), default=0.0)

    # 探测：只要能把标题的**近端**从刻度标签里分出来就够标定锚点偏移
    # （近端不会被页面边缘裁掉，远端裁掉也无妨——厚度由后面的校正环处理）。
    # 锚点偏移 k 实测在 0～0.6 cm 之间因图而异：k 小时 tick_far+0.8 就能分开，
    # k 大时标题会缩回刻度标签里，得写到页面边缘外（avail+0.2）才分得开。
    k = None
    for d0 in (tick_far + 0.8, avail_px + 0.2, tick_far + 1.1,
               tick_far + 0.5, tick_far + 0.3):
        write(d0)
        if not render():
            return False
        bs, _ = bands()
        cand = [(n, f) for n, f in (bs or []) if n > tick_far + 0.04]
        if not cand:
            continue
        k = d0 - cand[-1][0]
        break
    if k is None:
        if not quiet:
            print(f"  [warn] {name} {side} 标题标定失败，保持原位")
        return False

    # 定位 + 校正环：写→量→按残差修正锚点偏移，越出页面边缘就往回收
    near = max(tick_far + gap, min_near)
    ok = False
    for _ in range(4):
        write(near + k)
        if not render():
            return False
        bs, _ = bands()
        cand = [(n, f) for n, f in (bs or []) if n > tick_far + 0.02]
        if not cand:
            break
        n1, f1 = cand[-1]
        k += near - n1                       # 锚点残差校正（写入与渲染 1:1）
        over = f1 - (avail_px - 0.06)
        if over <= 0:
            ok = abs(n1 - near) <= 0.03
            if ok:
                break
            continue
        floor = tick_far + 0.04
        if near - over < floor:              # 页面装不下：贴着刻度标签放
            if not quiet:
                print(f"  [warn] {name} {side} 标题与刻度标签间距不足 "
                      f"({max(floor, near - over) - tick_far:.2f} cm)")
            near = floor
        else:
            near -= over
    if not ok and not quiet:
        print(f"  [warn] {name} {side} 标题定位未收敛（目标 {near:.2f} cm）")
    try:
        os.remove(tmp)
    except OSError:
        pass
    return True


def fit_axis_titles(gpage, layer_i: int, page_cm, frame_cm,
                    do_x: bool = True, do_y: bool = True,
                    do_yr: bool = False, name: str = "") -> None:
    """按渲染结果把本 layer 的 X/Y(/右 Y) 轴标题摆到刻度标签之外。

    仅适用于"整页只有这一个面板"的版面：量测按框架某一侧的整条带做，
    多面板页上邻居面板的墨迹会混进来。
    """
    if Image is None:
        return
    lt(f"page.active={layer_i};")
    xf, xt = ltf("layer.x.from"), ltf("layer.x.to")
    yf, yt = ltf("layer.y.from"), ltf("layer.y.to")
    fw, fh = frame_cm[2], frame_cm[3]
    if None in (xf, xt, yf, yt) or xt == xf or yt == yf or not fw or not fh:
        return
    xspan, yspan = xt - xf, yt - yf

    def w_x(d: float) -> None:
        lt(f"page.active={layer_i}; xb.y = {yf - d / fh * yspan:.8g};")

    def w_y(d: float) -> None:
        lt(f"page.active={layer_i}; yl.x = {xf - d / fw * xspan:.8g};")

    def w_yr(d: float) -> None:
        lt(f"page.active={layer_i}; yr.x = {xt + d / fw * xspan:.8g};")

    def try_fit(prop: str, side: str, writer, alt_side: str | None = None) -> None:
        """标定失败要把对象写回原值——失败时它还停在探测位置（页面外）。"""
        orig = ltf(prop)
        if _fit_title(gpage, layer_i, page_cm, frame_cm, side, writer, name,
                      quiet=alt_side is not None):
            return
        if alt_side and orig is not None:
            lt(f"page.active={layer_i}; {prop} = {orig:.10g};")
            if _fit_title(gpage, layer_i, page_cm, frame_cm, alt_side,
                          writer, name):
                return
        if orig is not None:
            lt(f"page.active={layer_i}; {prop} = {orig:.10g};")

    if do_x:
        try_fit("xb.y", "below", w_x)
    if do_y:
        try_fit("yl.x", "left", w_y)
    if do_yr:
        # X 轴反向的图里 YR 渲染在视觉左侧（本项目 FTIR/XPS/NMR）：先按
        # xt 端所在侧量测，量不到再试另一侧；左侧被可见 YL 占用时不试左侧。
        first = "right" if xt > xf else "left"
        alt = None if (first == "right" and do_y) else \
            ("left" if first == "right" else "right")
        try_fit("yr.x", first, w_yr, alt)


def _read_rect(unit: int) -> tuple[float, float, float, float]:
    lt(f"layer.unit = {unit};")
    return (ltf("layer.left") or 0, ltf("layer.top") or 0,
            ltf("layer.width") or 0, ltf("layer.height") or 0)


def analyze_layers(gpage, nlayers: int) -> list[dict]:
    """读取各 layer 几何并分类: main / overlay / linked_ext / linked_inset / inset。

    unit=7（链接层百分比坐标）的 layer 随父层自动移动，不写几何：
    覆盖全父层的视为 overlay（双 Y 轴等）；整层偏移到父层之外的
    （如 -100% 的堆叠谱图）视为 linked_ext；框架落在父层范围内的小层
    视为 linked_inset（画在面板内的参比谱等），缩放时跟着父层走，
    因此不妨碍面板按标准版式重排。非链接层中，框架中心落在另一非链接
    层内部且明显更小的视为 inset（放大插图）。其余为 main（面板）。
    """
    infos = []
    for i in range(1, nlayers + 1):
        lt(f"page.active={i};")
        unit = int(ltf("layer.unit") or 1)
        if unit == 7:
            l, t, w, h = (ltf("layer.left") or 0, ltf("layer.top") or 0,
                          ltf("layer.width") or 0, ltf("layer.height") or 0)
            if abs(l) < 5 and abs(t) < 5 and w > 90:
                kind = "overlay"
            elif -15 <= l and l + w <= 115 and -15 <= t and t + h <= 115:
                kind = "linked_inset"
            else:
                kind = "linked_ext"
            # rel 是相对父层框架的百分比（不能切 unit 去读 cm：切 unit 是
            # 转换存储值，会破坏相对坐标），堆叠判定用它
            infos.append({"i": i, "kind": kind, "rel": (l, t, w, h),
                          "objs": snapshot_objects(gpage[i - 1])})
            continue
        pct = _read_rect(1)   # % of page
        cm = _read_rect(3)
        infos.append({"i": i, "kind": "main", "pct": pct, "cm": cm,
                      "objs": snapshot_objects(gpage[i - 1])})
    plain = [x for x in infos if x["kind"] == "main"]
    for a in plain:
        al, at, aw, ah = a["pct"]
        cx, cy = al + aw / 2, at + ah / 2
        for b in plain:
            if a is b:
                continue
            bl, bt, bw, bh = b["pct"]
            if (bl <= cx <= bl + bw and bt <= cy <= bt + bh
                    and aw < 0.8 * bw and ah < 0.8 * bh):
                a["kind"] = "inset"
                break
    return infos


def vertical_stack(infos: list[dict]) -> list[int] | None:
    """竖向堆叠谱图（XPS 多组分等）识别：唯一一个普通层 + 若干链接层，
    每个链接层与父层同宽同高、只在纵向整层偏移（rel top = k*100）。

    返回按页面自上而下的 layer 序号列表；不是这种结构则 None。
    这种图整叠一起缩放，视觉上算**一个面板**，按单图版式排：框架高度
    等分给各层，只写父层几何，链接层自动跟随（实测跟随正确）。
    """
    mains = [x for x in infos if x["kind"] == "main"]
    links = [x for x in infos if x["kind"] == "linked_ext"]
    if len(mains) != 1 or not links or len(mains) + len(links) != len(infos):
        return None
    order = {mains[0]["i"]: 0.0}
    for x in links:
        l, t, w, h = x["rel"]
        if abs(l) > 2 or abs(w - 100) > 2 or abs(h - 100) > 2:
            return None
        if t is None or abs(t / 100.0 - round(t / 100.0)) > 0.05 or t < 50:
            return None
        order[x["i"]] = t / 100.0
    return [i for i, _ in sorted(order.items(), key=lambda kv: kv[1])]


def plain_vertical_stack(infos: list[dict]) -> list[int] | None:
    """未链接的竖向堆叠谱图（XPS 全谱、质谱对比等）：若干普通层左边界与
    宽度相同、等高、纵向依次紧邻排列（相邻间隙 < 层高的 25%）。

    与 `vertical_stack` 的区别：这些层彼此独立（unit 不是 7），几何要逐层
    写。返回自上而下的 layer 序号；不是这种结构则 None。
    """
    mains = [x for x in infos if x["kind"] == "main"]
    if len(mains) < 2 or len(mains) != len(infos):
        return None
    order = sorted(mains, key=lambda x: x["pct"][1])
    l0, _, w0, h0 = order[0]["pct"]
    if h0 <= 0:
        return None
    for x in order:
        l, t, w, h = x["pct"]
        if abs(l - l0) > 1.0 or abs(w - w0) > 1.0 or abs(h - h0) > 1.0:
            return None
    for a, b in zip(order, order[1:]):
        gap = b["pct"][1] - (a["pct"][1] + a["pct"][3])
        if gap < -1.0 or gap > 0.25 * h0:
            return None
    return [x["i"] for x in order]


def has_right_axis(infos: list[dict]) -> bool:
    """overlay 层（双 Y 轴的载体）渲染右轴刻度标签，或任一 layer 有
    真实的右轴标题（非占位符），才算有右轴。

    单层图的 y2 只能是左轴的镜像标签，Origin 真双 Y 轴必然是 overlay
    层结构。layer.y2.showLabels 是休眠开关（默认模板四条轴全 1），
    showAxes 位 2 在带框线的图上恒真（框的右边线就是 y2 轴线），
    两者联判仍会把普通带框单层图误判成双 Y 轴（FigS7/S14/S16/S27
    案例：右边距被加宽、图层 7.59 变 6.86）——刻度标签条件只对
    overlay 层生效。"""
    for x in infos:
        lt(f"page.active={x['i']};")
        if x["kind"] == "overlay" and \
                (ltf("layer.y2.showLabels") or 0) > 0 and \
                int(ltf("layer.y2.showAxes") or 0) & 2:
            return True
        try:
            t = op.lt_str("yr.text$") or ""
        except Exception:
            t = ""
        if t.strip() and "%(" not in t:
            return True
    return False


def format_graph(gpage, font_idx: int) -> dict:
    name = gpage.name
    lt(f"win -a {name};")
    nlayers = int(ltf("page.nlayers") or 0)
    px_per_cm = (ltf("page.resx") or 600.0) / 2.54
    page_w0 = (ltf("page.width") or 0) / px_per_cm
    page_h0 = (ltf("page.height") or 0) / ((ltf("page.resy") or 600.0) / 2.54)

    infos = analyze_layers(gpage, nlayers)
    mains = [x for x in infos if x["kind"] == "main"]
    stack = vertical_stack(infos)
    pstack = plain_vertical_stack(infos) if not stack else None
    preserve = (not stack) and (not pstack) and \
        any(x["kind"] in ("inset", "linked_ext") for x in infos)
    info = {"name": name, "nlayers": nlayers, "panels_removed": 0,
            "small": {x["i"] for x in infos
                      if x["kind"] in ("inset", "linked_inset")}}

    if pstack:
        # 未链接的竖向堆叠谱图：整叠算一个面板，用单图版式的宽度，
        # 页面高度按"保持各层原有宽高比"算出来，几何逐层写。
        base = dict(LAYOUTS[1])
        margins = dict(base.get("margins", CELL_MARGIN))
        width = base["page"][0] - margins["left"] - margins["right"]
        by_index = {x["i"]: x for x in infos}
        ow, oh = by_index[pstack[0]]["cm"][2], by_index[pstack[0]]["cm"][3]
        h_each = width / (ow / oh) if ow > 0 and oh > 0 else 1.7
        page = (base["page"][0],
                round(margins["top"] + margins["bottom"]
                      + h_each * len(pstack), 4))
        info.update({"layout": f"vstack{len(pstack)}", "page_cm": page})
        set_page_size_cm(*page)
        left, top = margins["left"], margins["top"]
        pending: list = []
        for k, li in enumerate(pstack):
            x = by_index[li]
            new_rect = (left, top + k * h_each, width, h_each)
            lt(f"page.active={li};")
            lt("layer.unit = 3;")
            lt(f"layer.left = {new_rect[0]:.4f}; layer.top = {new_rect[1]:.4f}; "
               f"layer.width = {new_rect[2]:.4f}; layer.height = {new_rect[3]:.4f};")
            pending += fix_objects(x["objs"], x["cm"], new_rect, px_per_cm)
        fits: list[tuple] = []
        for k, li in enumerate(pstack):
            lt(f"page.active={li};")
            format_layer_axes(font_idx)
            format_plots(gpage[li - 1])
            _, _, yr_real, xb_real, yl_real = format_text_objects(
                gpage[li - 1], font_idx, remove_panels=False)
            reposition_axis_titles(w_cm=width, h_cm=h_each, yr_real=yr_real)
            reposition_legend()
            rect = (left, top + k * h_each, width, h_each)
            fits.append((li, rect, xb_real, yl_real, yr_real))
        settle_objects(gpage, pending)
        for li, rect, xb_real, yl_real, yr_real in fits:
            fit_axis_titles(gpage, li, page, rect, do_x=xb_real,
                            do_y=yl_real, do_yr=yr_real, name=name)
        return info

    if stack:
        # 竖向堆叠谱图：整叠算一个面板，按单图版式排，框架高度等分给各层。
        layout = dict(LAYOUTS[1])
        margins = dict(layout.get("margins", CELL_MARGIN))
        info.update({"layout": f"stack{len(stack)}", "page_cm": layout["page"]})
        set_page_size_cm(*layout["page"])
        left, top, width, height = cell_rect(layout, 0, margins)
        h_each = height / len(stack)
        x0 = mains[0]
        lt(f"page.active={x0['i']};")
        lt("layer.unit = 3;")
        lt(f"layer.left = {left:.3f}; layer.top = {top:.3f}; "
           f"layer.width = {width:.3f}; layer.height = {h_each:.4f};")
        pending = fix_objects(x0["objs"], x0["cm"],
                              (left, top, width, h_each), px_per_cm)
        # 链接层跟随父层（实测：写完父层几何后读回的 cm 正好是等间距堆叠），
        # 这里只校验，不写几何——写几何要先解链接，会丢掉共享 X 轴。
        by_index = {x["i"]: x for x in infos}
        for k, li in enumerate(stack):
            if li == x0["i"]:
                continue
            lt(f"page.active={li};")
            lt("layer.unit = 3;")
            got_t, got_h = ltf("layer.top"), ltf("layer.height")
            want_t = top + k * h_each
            if got_t is None or abs(got_t - want_t) > 0.05 or \
                    got_h is None or abs(got_h - h_each) > 0.05:
                print(f"  [warn] {name} L{li} 堆叠位置未跟随: "
                      f"top {got_t} (want {want_t:.3f}) h {got_h}")
            # 链接层的对象也要修：老框架 = 父层老框架 + rel 偏移
            rec = by_index.get(li, {})
            rl, rt, rw, rh = rec.get("rel", (0, k * 100.0, 100.0, 100.0))
            pl, pt_, pw, ph = x0["cm"]
            old_frame = (pl + rl / 100.0 * pw, pt_ + rt / 100.0 * ph,
                         rw / 100.0 * pw, rh / 100.0 * ph)
            pending += fix_objects(rec.get("objs", []), old_frame,
                                   (left, top + k * h_each, width, h_each),
                                   px_per_cm)
        fits: list[tuple] = []
        for k, li in enumerate(stack):
            lt(f"page.active={li};")
            format_layer_axes(font_idx)
            format_plots(gpage[li - 1])
            _, _, yr_real, xb_real, yl_real = format_text_objects(
                gpage[li - 1], font_idx, remove_panels=False)
            reposition_axis_titles(w_cm=width, h_cm=h_each, yr_real=yr_real)
            reposition_legend()
            fits.append((li, (left, top + k * h_each, width, h_each),
                         xb_real, yl_real, yr_real))
        settle_objects(gpage, pending)
        for li, rect, xb_real, yl_real, yr_real in fits:
            # 堆叠图的 YR 竖跨整叠，不按单层量测（见 reposition_axis_titles）
            fit_axis_titles(gpage, li, layout["page"], rect, do_x=xb_real,
                            do_y=yl_real, do_yr=False, name=name)
        return info

    if preserve:
        # 含放大插图/链接堆叠层的特殊结构：不重排面板，
        # 整页等比缩放到 16 cm 宽，只统一字体与轴样式。
        scale = 16.0 / page_w0 if page_w0 else 1.0
        page = (16.0, round(page_h0 * scale, 2))
        info.update({"layout": "preserve", "page_cm": page})
        set_page_size_cm(*page)
        pending = []
        for x in infos:
            if x["kind"] not in ("main", "inset"):
                continue  # 链接层自动跟随父层
            l, t, w, h = x["pct"]
            lt(f"page.active={x['i']};")
            lt("layer.unit = 1;")  # 按页面百分比原样写回（页面纵横比未变）
            lt(f"layer.left = {l:.4f}; layer.top = {t:.4f}; "
               f"layer.width = {w:.4f}; layer.height = {h:.4f};")
            new_cm = _read_rect(3)
            pending += fix_objects(x["objs"], x["cm"], new_cm, px_per_cm)
        settle_objects(gpage, pending)
        for x in infos:
            lt(f"page.active={x['i']};")
            small = x["kind"] in ("inset", "linked_inset")
            format_layer_axes(font_idx, keep_size=small)
            format_plots(gpage[x["i"] - 1])
            _, _, yr_real, xb_real, yl_real = format_text_objects(
                gpage[x["i"] - 1], font_idx, remove_panels=False,
                keep_size=small)
            if x["kind"] == "main":
                reposition_axis_titles(yr_real=yr_real)
                reposition_legend()
                # 插图层在主框架内部，框架外侧的量测带里只有主层的刻度与标题
                fit_axis_titles(gpage, x["i"], page, _read_rect(3),
                                do_x=xb_real, do_y=yl_real, do_yr=yr_real,
                                name=name)
        return info

    layout = grid_for(len(mains))
    info.update({"layout": f"{layout['rows']}x{layout['cols']}",
                 "page_cm": layout["page"]})
    set_page_size_cm(*layout["page"])
    margins = dict(layout.get("margins", CELL_MARGIN))
    if has_right_axis(infos):
        margins["right"] = margins["left"]   # 双 Y 轴：右侧留出刻度+标题位置
        info["dual_y"] = True
    rects: dict[int, tuple[float, float, float, float]] = {}
    pending: list = []
    for k, x in enumerate(mains):   # 仅 main 层排入网格；overlay 跟随父层
        lt(f"page.active={x['i']};")
        left, top, width, height = cell_rect(layout, k, margins)
        # 层内有图片对象（TEM/结构式）时保持原框架宽高比：图片只能等比缩放，
        # 而挂在坐标轴上的标注是按框架各方向拉伸的——宽高比一变，标注就
        # 对不上图片上的位置（本项目 Fig1 的 NMR 结构式化学位移标注）。
        ow, oh = x["cm"][2], x["cm"][3]
        if any(o["img"] for o in x["objs"]) and ow > 0 and oh > 0:
            old_a, new_a = ow / oh, width / height
            if abs(old_a / new_a - 1) > 0.05:
                if old_a > new_a:               # 原来更扁 → 按宽定高
                    nh = width / old_a
                    top += (height - nh) / 2    # 在单元格里垂直居中
                    height = nh
                else:                           # 原来更高 → 按高定宽
                    width = height * old_a
        lt("layer.unit = 3;")
        lt(f"layer.left = {left:.3f}; layer.top = {top:.3f}; "
           f"layer.width = {width:.3f}; layer.height = {height:.3f};")
        rects[x["i"]] = (left, top, width, height)
        pending += fix_objects(x["objs"], x["cm"],
                               (left, top, width, height), px_per_cm)

    # unit=7 链接层的框架渲染用的是陈旧缓存，父层大幅移动后不会自动
    # 刷新（读回值看似正确但渲染错位），且链接状态下写几何被忽略——
    # 必须先解除链接再显式写成与主层一致的框架。
    if len(mains) == 1:
        left, top, width, height = cell_rect(layout, 0, margins)
        for x in infos:
            if x["kind"] == "overlay":
                lt(f"page.active={x['i']};")
                lt("layer.link = 0;")
                lt("layer.unit = 3;")
                lt(f"layer.left = {left:.3f}; layer.top = {top:.3f}; "
                   f"layer.width = {width:.3f}; layer.height = {height:.3f};")

    orig_letters: list[str] = []
    title_fits: list[tuple] = []
    for x in infos:
        lt(f"page.active={x['i']};")
        # 插图层（含跟随父层的链接插图）的文字不放大，见 format_text_objects
        small = x["kind"] in ("inset", "linked_inset")
        format_layer_axes(font_idx, keep_size=small)
        format_plots(gpage[x["i"] - 1])
        removed, lets, yr_real, xb_real, yl_real = format_text_objects(
            gpage[x["i"] - 1], font_idx, keep_size=small)
        info["panels_removed"] += removed
        orig_letters.extend(le for le in lets if le)
        if x["kind"] in ("main", "overlay"):
            r = rects.get(x["i"])
            reposition_axis_titles(w_cm=r[2] if r else None,
                                   h_cm=r[3] if r else None, yr_real=yr_real)
            reposition_legend()
            if r and len(mains) == 1:
                # 量测的是框架某一侧的整条带，只有单面板页才对得上
                title_fits.append((x["i"], r, xb_real, yl_real, yr_real))

    if len(mains) > 1:
        # 原图有完整的一组面板字母（如 FigS33 的 c/d，a/b 是 Word 里的
        # SEM 照片；可能都挂在同一 layer 上）则按字母序沿用，否则从 a 重编。
        use_orig = len(orig_letters) == len(mains) and \
            all(len(v) == 1 for v in orig_letters)
        letters = sorted(orig_letters) if use_orig else PANEL_LETTERS
        for k, x in enumerate(mains):
            add_panel_label(gpage, x["i"], letters[k], font_idx)

    # 版面自检放最后：面板标签等都到位后再按渲染结果摆轴标题
    settle_objects(gpage, pending)
    for li, r, xb_real, yl_real, yr_real in title_fits:
        fit_axis_titles(gpage, li, layout["page"], r, do_x=xb_real,
                        do_y=yl_real, do_yr=yr_real, name=name)

    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True, help="输入 .opju 路径（不会被修改）")
    ap.add_argument("--out-dir", default=None,
                    help="输出目录（默认与输入同目录）")
    ap.add_argument("--dpi", type=int, default=STYLE["export_dpi"],
                    help="导出 PNG 分辨率 (默认 600)")
    ap.add_argument("--font", default=STYLE["font"], help="统一字体名")
    ap.add_argument("--suffix", default="_thesis", help="输出 opju 文件名后缀")
    ap.add_argument("--skip-multilayer", action="store_true",
                    help="跳过多 layer 的复杂图（完全不动，留给用户手动调整）")
    ap.add_argument("--keep-legend-pos", action="store_true",
                    help="不把图例挪到框架右上角（图例已手工摆在避开曲线的位置时用）")
    ap.add_argument("--no-tweaks", action="store_true",
                    help="不套用本项目的逐图微调（PER_GRAPH_TWEAKS）")
    ap.add_argument("--show-origin", action="store_true", help="显示 Origin 界面")
    args = ap.parse_args()

    STYLE["font"] = args.font
    STYLE["move_legend"] = not args.keep_legend_pos

    src = os.path.abspath(args.project)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.dirname(src)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    tweaks = {} if args.no_tweaks else PER_GRAPH_TWEAKS.get(stem, {})
    if tweaks:
        print(f"per-graph tweaks for {stem!r}: {', '.join(sorted(tweaks))}")
    out_opju = os.path.join(out_dir, f"{stem}{args.suffix}.opju")
    fig_dir = os.path.join(out_dir, f"{stem}{args.suffix}_figures")
    os.makedirs(fig_dir, exist_ok=True)

    # 在临时副本上操作，绝不写回原文件
    tmp = tempfile.mkdtemp(prefix="origin_fmt_")
    work = os.path.join(tmp, "work.opju")
    shutil.copy2(src, work)

    op.set_show(bool(args.show_origin))
    if not op.open(work):
        raise RuntimeError(f"Origin 打开失败: {work}")

    fidx = font_index(STYLE["font"])
    print(f"font={STYLE['font']} (index {fidx})")

    results = []
    skipped = []
    for g in op.graph_list('p'):
        if args.skip_multilayer:
            lt(f"win -a {g.name};")
            n = int(ltf("page.nlayers") or 0)
            if n > 1:
                skipped.append((g.name, g.lname, n))
                print(f"skipped {g.name} ({g.lname!r}): {n} layers -> 手动调整")
                continue
        try:
            info = format_graph(g, fidx)
            tweak = tweaks.get(info["name"])
            if tweak:
                tweak(g)
            results.append(info)
            print(f"formatted {info['name']}: {info['nlayers']} layer(s) -> "
                  f"{info['layout']}, page {info['page_cm'][0]}x{info['page_cm'][1]} cm, "
                  f"removed {info['panels_removed']} old panel label(s)"
                  + (" [双Y轴:右边距加宽]" if info.get("dual_y") else ""))
        except Exception:
            print(f"[error] formatting {g.name} failed:")
            traceback.print_exc()

    small_by_name = {info["name"]: info.get("small") for info in results}
    all_issues = []
    for g in op.graph_list('p'):
        if g.name in small_by_name:   # 跳过的图保持原样，不参与校验
            all_issues.extend(verify_graph(g, fidx, small_by_name[g.name]))
    if all_issues:
        print("[verify] 以下文本对象属性与预期不符：")
        for line in all_issues:
            print("  " + line)
    else:
        print("[verify] 所有文本对象字体/字号符合预期")

    op.save(out_opju)
    print(f"origin_project={out_opju}")

    # 按各自页面实际宽度导出
    for info in results:
        try:
            g = op.find_graph(info["name"])
            px = int(round(info["page_cm"][0] / 2.54 * args.dpi))
            png = os.path.join(fig_dir, f"{info['name']}.png")
            g.save_fig(png, type="png", width=px)
            print(f"exported={png}")
        except Exception:
            print(f"[error] export {info['name']} failed:")
            traceback.print_exc()

    if skipped:
        print("需要手动调整的图: " +
              ", ".join(f"{n} ({ln!r}, {k} layers)" for n, ln, k in skipped))

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        op.exit()
