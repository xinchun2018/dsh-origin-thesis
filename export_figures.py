# -*- coding: utf-8 -*-
r"""把 Origin 项目（.opju/.opj）里的所有图批量导出成图片文件。

**不改动项目**：项目以只读方式打开，只做导出。

用法（必须用装了 originpro 的环境）：

  C:\Users\liuxc\miniconda3\envs\origin\python.exe export_figures.py "某项目.opju"

  # 600 dpi PNG + 矢量 EMF，输出到指定目录，按项目管理器文件夹分子目录
  ... export_figures.py "某项目.opju" --type png,emf --dpi 600 --tree

  # 一次处理多个项目 / 整个目录
  ... export_figures.py D:\papers\*.opju --out-dir D:\figs

默认输出：`<项目所在目录>\<项目名>_figures\<窗口名>.png`，尺寸 = 该图页面的
真实物理尺寸 × dpi（所见即所得），并把文件里的 dpi 元数据改成真实 dpi，
这样插进 Word / LaTeX 时物理尺寸就是 Origin 里的页面尺寸。

Origin 侧的坑（实测 Origin 2021 / 9.8）见文件末尾 NOTES。
"""
import argparse
import fnmatch
import glob
import json
import os
import struct
import sys
import traceback
import zlib

sys.stdout.reconfigure(encoding="utf-8")

import originpro as op
from originpro.config import po      # 无界面运行时是 OriginExt 应用包装对象

# ---------------------------------------------------------------- 常量 ------
# PyOrigin/OriginExt 的页面类型码
PAGE_KIND = {3: "graph", 4: "layout", 29: "image"}

RASTER = ("png", "tif", "jpg", "bmp", "gif", "pcx", "tga", "psd")
VECTOR = ("emf", "wmf", "pdf", "eps")
ALIAS = {"tiff": "tif", "jpeg": "jpg", "ps": "eps"}
FIX_DPI_TYPES = ("png", "tif", "jpg", "bmp")     # 能改 dpi 元数据的格式
MARGIN_CODE = {"page": 2, "tight": 1}            # tr.Margin 实测值

CM_PER_INCH = 2.54


# ---------------------------------------------------------------- LabTalk ---
def lt(cmd, page=None):
    """执行 LabTalk；给了 page 就在该页面的上下文里执行（不必先激活窗口）。"""
    try:
        if page is None:
            op.lt_exec(cmd)
        else:
            page.LT_execute(cmd)
        return None
    except Exception as exc:                     # pylint: disable=broad-except
        return str(exc)


def ltf(expr):
    try:
        v = op.lt_float(expr)
        return None if v != v else v             # NaN -> None
    except Exception:                            # pylint: disable=broad-except
        return None


# ------------------------------------------------------------ dpi 元数据 ----
def _png_set_dpi(path, dpi):
    """写/改 PNG 的 pHYs 块（Origin 导出的 dpi 元数据固定是 300，与像素宽无关）。"""
    ppm = int(round(dpi / 0.0254))
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    body = struct.pack(">IIB", ppm, ppm, 1)
    chunk = (struct.pack(">I", len(body)) + b"pHYs" + body +
             struct.pack(">I", zlib.crc32(b"pHYs" + body) & 0xFFFFFFFF))
    pos, out, done = 8, bytearray(data[:8]), False
    while pos + 12 <= len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        end = pos + 12 + ln
        if typ == b"pHYs":
            out += chunk
            done = True
        else:
            out += data[pos:end]
            if typ == b"IHDR" and not done:      # pHYs 必须在 IDAT 之前
                out += chunk
                done = True
        pos = end
    with open(path, "wb") as f:
        f.write(bytes(out))
    return done


def _tif_set_dpi(path, dpi):
    """改 TIFF 第 0 个 IFD 的 XResolution/YResolution（RATIONAL，值在偏移处）。"""
    with open(path, "r+b") as f:
        head = f.read(8)
        if head[:2] == b"II":
            bo = "<"
        elif head[:2] == b"MM":
            bo = ">"
        else:
            return False
        ifd = struct.unpack(bo + "I", head[4:8])[0]
        f.seek(ifd)
        n = struct.unpack(bo + "H", f.read(2))[0]
        entries = f.read(n * 12)
        hit = False
        for i in range(n):
            tag, typ, cnt = struct.unpack(bo + "HHI", entries[i * 12:i * 12 + 8])
            raw = entries[i * 12 + 8:i * 12 + 12]
            if tag in (282, 283) and typ == 5 and cnt == 1:
                off = struct.unpack(bo + "I", raw)[0]
                f.seek(off)
                f.write(struct.pack(bo + "II", int(round(dpi)), 1))
                hit = True
            elif tag == 296 and typ == 3:        # ResolutionUnit = inch
                f.seek(ifd + 2 + i * 12 + 8)     # SHORT 存在值域前 2 字节
                f.write(struct.pack(bo + "HH", 2, 0))
        return hit


def _jpg_set_dpi(path, dpi):
    """改 JPEG 的 JFIF(APP0) 密度字段。"""
    with open(path, "r+b") as f:
        data = f.read(4096)
        i = data.find(b"\xff\xe0")
        if i < 0 or data[i + 4:i + 9] != b"JFIF\x00":
            return False
        f.seek(i + 11)                            # units(1) + Xdensity(2) + Ydensity(2)
        f.write(struct.pack(">BHH", 1, int(round(dpi)), int(round(dpi))))
        return True


def _bmp_set_dpi(path, dpi):
    """改 BMP 的 biXPelsPerMeter / biYPelsPerMeter。"""
    ppm = int(round(dpi / 0.0254))
    with open(path, "r+b") as f:
        if f.read(2) != b"BM":
            return False
        f.seek(38)
        f.write(struct.pack("<ii", ppm, ppm))
        return True


def fix_dpi(path, ext, dpi):
    """把文件里声明的 dpi 改成真实 dpi；返回 True 表示改成功。"""
    try:
        if ext == "png":
            return _png_set_dpi(path, dpi)
        if ext == "tif":
            return _tif_set_dpi(path, dpi)
        if ext == "jpg":
            return _jpg_set_dpi(path, dpi)
        if ext == "bmp":
            return _bmp_set_dpi(path, dpi)
    except Exception:                            # pylint: disable=broad-except
        return False
    return False


# ------------------------------------------------------------- 名字处理 -----
_BAD_CHARS = set('<>:"/\\|?*%$`')                # 后三个是 LabTalk 字符串里的雷


def sanitize(stem, fallback="figure"):
    out = "".join("_" if (c in _BAD_CHARS or ord(c) < 32) else c for c in str(stem))
    out = " ".join(out.split()).strip().rstrip(".")
    return out[:120] if out else fallback


def stem_for(rec, mode):
    """按 --name 规则生成文件名主干。"""
    short, long_ = rec["name"], (rec["lname"] or "").strip()
    if mode == "short" or not long_:
        return sanitize(short)
    if mode == "long":
        return sanitize(long_, short)
    if mode == "both":
        return sanitize(f"{short}_{long_}", short)
    # auto: 长名有意义就用长名，否则用短名
    return sanitize(long_ if long_.lower() != short.lower() else short, short)


def dedupe(stems):
    """同名冲突时加 _2/_3…（长名可以重复，短名不会）。"""
    seen, out = {}, []
    for s in stems:
        key = s.lower()
        if key in seen:
            seen[key] += 1
            out.append(f"{s}_{seen[key]}")
        else:
            seen[key] = 1
            out.append(s)
    return out


# ------------------------------------------------------------- 页面枚举 -----
def collect_pages(kinds, include_embedded):
    """枚举项目里所有可导出的页面。

    以 po.GetPages() 为准（graph/layout/image 都能拿到），再用
    graph_list('p', True) 补上被嵌入到工作表里的图。
    """
    recs, seen = [], set()

    def add(obj, kind, embedded):
        name = obj.GetName()
        if name in seen:
            return
        seen.add(name)
        recs.append({"name": name, "kind": kind, "embedded": bool(embedded), "obj": obj})

    for p in po.GetPages():
        try:
            kind = PAGE_KIND.get(p.GetType())
        except Exception:                        # pylint: disable=broad-except
            kind = None
        if not kind or kind not in kinds:
            continue
        try:
            emb = bool(p.GetNumProp("isEmbedded"))
        except Exception:                        # pylint: disable=broad-except
            emb = False
        add(p, kind, emb)

    if "graph" in kinds:
        try:
            for g in op.graph_list('p', True):   # 'p' = 全项目，True = 含嵌入图
                add(g.obj, "graph", g.obj.GetNumProp("isEmbedded"))
        except Exception:                        # pylint: disable=broad-except
            pass

    for rec in recs:
        obj = rec["obj"]
        try:
            rec["lname"] = obj.GetLongName() or ""
        except Exception:                        # pylint: disable=broad-except
            rec["lname"] = ""
        # 页面几何：在页面自己的上下文里求值，免得依赖“当前激活窗口”
        lt("__efw=0; __efh=0; __efr=0; __efn=0;")
        lt("__efw=page.width; __efh=page.height; __efr=page.resx; __efn=page.nlayers;", obj)
        w, h, res, nl = ltf("__efw"), ltf("__efh"), ltf("__efr"), ltf("__efn")
        if w and h and res:
            rec["page_cm"] = (w / res * CM_PER_INCH, h / res * CM_PER_INCH)
        else:
            rec["page_cm"] = None
        rec["nlayers"] = int(nl or 0)
        try:
            rec["folder"] = op.pe.search(rec["name"], 0) or "/"
        except Exception:                        # pylint: disable=broad-except
            rec["folder"] = "/"
        if not include_embedded and rec["embedded"]:
            rec["skip"] = "嵌入图（--embedded 才导出）"
    return recs


def keep(rec, patterns, excludes):
    hay = [rec["name"].lower(), (rec["lname"] or "").lower()]
    if patterns and not any(fnmatch.fnmatch(h, p.lower()) for h in hay for p in patterns):
        return False
    if excludes and any(fnmatch.fnmatch(h, p.lower()) for h in hay for p in excludes):
        return False
    return True


# ---------------------------------------------------------------- 导出 ------
def size_args(ext, page_cm, dpi, width_cm, width_px):
    """返回 (LabTalk 尺寸参数, 目标像素宽或 None, 实际物理宽 cm 或 None)。

    tr1.Unit 实测：0=inch 1=cm 2=pixel 3=页面百分比（4 无效）。
    dpi 没有可用的树节点（tr1.DPI 之类会让 X-Function 静默失败），
    所以栅格格式一律用 unit=2 自己算像素。
    """
    if ext in VECTOR:
        if width_cm:
            return f"tr1.Unit:=1 tr1.Width:={width_cm:.6g}", None, width_cm
        return "", None, (page_cm[0] if page_cm else None)
    if width_px:
        px = int(width_px)
        cm = px / dpi * CM_PER_INCH
    else:
        cm = width_cm or (page_cm[0] if page_cm else None)
        if not cm:
            return "", None, None
        px = int(round(cm / CM_PER_INCH * dpi))
    return f"tr1.Unit:=2 tr1.Width:={px}", px, cm


def export_one(rec, out_dir, stem, ext, args):
    """导出一个页面为一种格式，返回结果 dict。"""
    path = os.path.join(out_dir, f"{stem}.{ext}")
    sargs, px, cm = size_args(ext, rec.get("page_cm"), args.dpi,
                              args.width_cm, args.width_px)
    res = {"file": path, "type": ext, "px_width": px, "cm_width": cm}

    before = os.stat(path) if os.path.exists(path) else None
    if before and args.overwrite == "skip":
        res.update(status="skipped", bytes=before.st_size)
        return res

    margin = ""
    if args.margin:
        margin = f" tr.Margin:={MARGIN_CODE[args.margin]}"
    # path 结尾不能留反斜杠：'…\"' 会把引号转义掉，X-Function 静默不执行
    clean_dir = out_dir.rstrip("\\/")
    base = (f'expgraph -sw type:={ext} path:="{clean_dir}" '
            f'filename:="{stem}" overwrite:=replace')

    def run(extra):
        err = lt(f"{base} {extra}{margin}", rec["obj"])
        after = os.stat(path) if os.path.exists(path) else None
        fresh = bool(after) and (before is None or
                                 after.st_mtime_ns != before.st_mtime_ns or
                                 after.st_size != before.st_size)
        return err, after, fresh

    err, after, fresh = run(sargs)
    if not fresh and sargs:                      # 尺寸参数不被接受时退回默认尺寸
        err2, after, fresh = run("")
        if fresh:
            res["note"] = "尺寸参数被 Origin 拒绝，按页面默认尺寸导出"
            res["px_width"] = None
            err = None
        else:
            err = err or err2
    if not fresh:
        res.update(status="failed", error=err or "expgraph 没有产出文件")
        return res

    res.update(status="ok", bytes=after.st_size)
    if args.fix_dpi and ext in FIX_DPI_TYPES and res.get("px_width"):
        res["dpi_written"] = fix_dpi(path, ext, args.dpi)
    return res


# ---------------------------------------------------------------- 项目 ------
def out_dir_for(project, args, multi):
    stem = os.path.splitext(os.path.basename(project))[0]
    if args.out_dir:
        base = os.path.abspath(args.out_dir)
        return base if (not multi or args.flat) else os.path.join(base, sanitize(stem))
    return os.path.join(os.path.dirname(os.path.abspath(project)), f"{stem}_figures")


def export_project(project, args, multi):
    print("=" * 72)
    print(f"项目: {project}")
    if not op.open(project, readonly=True):
        print("  [error] Origin 打开失败，跳过")
        return {"project": project, "error": "open failed", "figures": []}

    kinds = {"graph"} if args.graphs_only else set(PAGE_KIND.values())
    recs = collect_pages(kinds, args.embedded)
    if not recs:
        print("  项目里没有可导出的图")
        return {"project": project, "figures": []}

    todo = []
    for r in recs:
        if r.get("skip"):
            continue
        if keep(r, args.pattern, args.exclude):
            todo.append(r)
        else:
            r["skip"] = "被 --pattern/--exclude 过滤"

    stems = dedupe([stem_for(r, args.name) for r in todo])
    out_root = out_dir_for(project, args, multi)
    print(f"  输出目录: {out_root}")
    print(f"  {len(recs)} 个页面，导出 {len(todo)} 个"
          + (f"（跳过 {len(recs) - len(todo)} 个）" if len(recs) != len(todo) else ""))

    figures, n_ok, n_fail = [], 0, 0
    for rec, stem in zip(todo, stems):
        sub = out_root
        if args.tree:
            rel = sanitize_folder(rec["folder"])
            sub = os.path.join(out_root, rel) if rel else out_root
        cm = rec.get("page_cm")
        head = (f"  {rec['name']:<14s} {rec['kind']:<6s} "
                f"{('%.2f×%.2f cm' % cm) if cm else '尺寸未知':>18s} "
                f"{rec['nlayers']}层")
        if args.dry_run:
            print(head + f"  -> {os.path.join(sub, stem)}.{{{','.join(args.type)}}}")
            figures.append({**{k: v for k, v in rec.items() if k != "obj"},
                            "stem": stem, "dir": sub, "results": []})
            continue
        os.makedirs(sub, exist_ok=True)          # 目录不存在时 expgraph 静默失败
        results = [export_one(rec, sub, stem, ext, args) for ext in args.type]
        figures.append({**{k: v for k, v in rec.items() if k != "obj"},
                        "stem": stem, "dir": sub, "results": results})
        bits = []
        for r in results:
            if r["status"] == "ok":
                n_ok += 1
                px = f"{r['px_width']}px " if r.get("px_width") else ""
                bits.append(f"{os.path.basename(r['file'])} ({px}{r['bytes'] / 1024:.0f} KB)")
            elif r["status"] == "skipped":
                bits.append(f"{os.path.basename(r['file'])} [已存在，跳过]")
            else:
                n_fail += 1
                bits.append(f"{os.path.basename(r['file'])} [失败: {r.get('error')}]")
        print(head + "  -> " + ", ".join(bits))

    for r in recs:
        if r.get("skip"):
            print(f"  - 跳过 {r['name']} ({r['kind']}): {r['skip']}")
    if args.dry_run:
        print(f"  --dry-run：以上 {len(todo)} 个页面 × {len(args.type)} 种格式未真正导出")
    else:
        print(f"  完成: {n_ok} 个文件" + (f"，失败 {n_fail} 个" if n_fail else ""))

    out = {"project": os.path.abspath(project), "out_dir": out_root,
           "dpi": args.dpi, "types": args.type, "n_ok": n_ok, "n_failed": n_fail,
           "figures": figures}
    if not args.dry_run and not args.no_manifest:
        os.makedirs(out_root, exist_ok=True)
        man = os.path.join(out_root, "export_manifest.json")
        with open(man, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"  清单: {man}")
    return out


def sanitize_folder(pe_path):
    """项目管理器路径 '/Folder1/Sub/' -> 相对目录 'Folder1\\Sub'。"""
    parts = [sanitize(p) for p in str(pe_path).strip("/").split("/") if p.strip()]
    return os.path.join(*parts) if parts else ""


# ---------------------------------------------------------------- CLI -------
def expand_inputs(items, recursive):
    files = []
    for item in items:
        hits = glob.glob(item) if any(c in item for c in "*?[") else [item]
        if not hits:
            print(f"[warn] 找不到: {item}")
        for h in hits:
            if os.path.isdir(h):
                pat = "**/*.opj*" if recursive else "*.opj*"
                found = sorted(glob.glob(os.path.join(h, pat), recursive=recursive))
                if not found:
                    print(f"[warn] 目录里没有 .opju/.opj: {h}")
                files.extend(found)
            elif os.path.isfile(h):
                files.append(h)
            else:
                print(f"[warn] 找不到: {h}")
    keep_, seen = [], set()
    for f in files:
        ap = os.path.abspath(f)
        if os.path.splitext(ap)[1].lower() not in (".opju", ".opj"):
            print(f"[warn] 不是 Origin 项目，跳过: {f}")
            continue
        if ap not in seen:
            seen.add(ap)
            keep_.append(ap)
    return keep_


def parse_types(raw):
    out = []
    for t in raw.replace(",", " ").split():
        t = ALIAS.get(t.lower().lstrip("."), t.lower().lstrip("."))
        if t not in RASTER + VECTOR:
            raise SystemExit(f"不支持的格式 {t!r}；可选: {', '.join(RASTER + VECTOR)}")
        if t not in out:
            out.append(t)
    return out or ["png"]


def main():
    ap = argparse.ArgumentParser(
        description="导出 Origin 项目里的所有图（不改动项目本身）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("projects", nargs="+", help=".opju/.opj 文件、目录或通配符")
    ap.add_argument("--out-dir", help="输出目录（默认 <项目名>_figures，与项目同目录）")
    ap.add_argument("--type", default="png",
                    help="导出格式，逗号分隔。栅格: " + ",".join(RASTER) +
                         "；矢量: " + ",".join(VECTOR))
    ap.add_argument("--dpi", type=float, default=600, help="栅格分辨率")
    ap.add_argument("--width-cm", type=float,
                    help="统一按这个印刷宽度导出（默认用每张图页面自己的宽度）")
    ap.add_argument("--width-px", type=int, help="统一按这个像素宽度导出（覆盖 --dpi 换算）")
    ap.add_argument("--margin", choices=sorted(MARGIN_CODE),
                    help="page=整页（Origin 默认）；tight=裁掉页面周围空白")
    ap.add_argument("--name", choices=["short", "long", "both", "auto"], default="short",
                    help="文件名用窗口短名(Graph1)/长名/两者；auto=有长名就用长名。"
                         "从 Word 抠出来的项目长名往往是垃圾（'1 - 复制'），所以默认短名")
    ap.add_argument("--tree", action="store_true", help="按项目管理器文件夹分子目录")
    ap.add_argument("--pattern", action="append", default=[],
                    help="只导出匹配的窗口（短名或长名，通配符，可多次）")
    ap.add_argument("--exclude", action="append", default=[], help="排除匹配的窗口（可多次）")
    ap.add_argument("--graphs-only", action="store_true",
                    help="只导出 Graph 窗口（默认也导 Layout/Image 窗口）")
    ap.add_argument("--embedded", action="store_true", help="连嵌入工作表里的图一起导出")
    ap.add_argument("--overwrite", choices=["replace", "skip"], default="replace",
                    help="目标文件已存在时覆盖还是跳过")
    ap.add_argument("--no-fix-dpi", dest="fix_dpi", action="store_false",
                    help="不修正 dpi 元数据（默认修正：Origin 无论多少像素都写 300 dpi）")
    ap.add_argument("--no-manifest", action="store_true", help="不写 export_manifest.json")
    ap.add_argument("--flat", action="store_true",
                    help="多个项目共用一个 --out-dir，不分子目录")
    ap.add_argument("--recursive", action="store_true", help="目录输入时递归查找项目")
    ap.add_argument("--dry-run", action="store_true", help="只列出会导出什么，不真的导")
    ap.add_argument("--show-origin", action="store_true", help="显示 Origin 界面")
    args = ap.parse_args()

    args.type = parse_types(args.type)
    if args.width_px and args.width_cm:
        raise SystemExit("--width-px 与 --width-cm 只能给一个")
    projects = expand_inputs(args.projects, args.recursive)
    if not projects:
        raise SystemExit("没有可处理的项目文件")

    if args.width_px:
        width_desc = f"{args.width_px} px"
    elif args.width_cm:
        width_desc = f"{args.width_cm:g} cm"
    else:
        width_desc = "各图页面原尺寸"
    print(f"格式={','.join(args.type)} dpi={args.dpi:g} 宽度={width_desc}"
          + (f" 边距={args.margin}" if args.margin else ""))
    if args.margin == "tight" and args.fix_dpi:
        print("[note] --margin tight 会裁掉页面空白后再缩放到目标宽度，"
              "图里的字相对会变大")

    op.set_show(bool(args.show_origin))
    summary = []
    for proj in projects:
        try:
            summary.append(export_project(proj, args, len(projects) > 1))
        except Exception:                        # pylint: disable=broad-except
            print(f"[error] 处理 {proj} 出错:")
            traceback.print_exc()
            summary.append({"project": proj, "error": "exception", "figures": []})

    if len(projects) > 1:
        print("=" * 72)
        tot_ok = sum(s.get("n_ok", 0) for s in summary)
        tot_bad = sum(s.get("n_failed", 0) for s in summary)
        print(f"共 {len(projects)} 个项目，导出 {tot_ok} 个文件"
              + (f"，失败 {tot_bad} 个" if tot_bad else ""))
        for s in summary:
            print(f"  {os.path.basename(s['project'])}: "
                  + (s["error"] if s.get("error") else
                     f"{len(s['figures'])} 张图 -> {s.get('out_dir')}"))


if __name__ == "__main__":
    try:
        main()
    finally:
        op.exit()

# ---------------------------------------------------------------- NOTES -----
# Origin 2021 (9.8) 实测，改脚本前值得知道：
# * expgraph 的 path:= 结尾不能留反斜杠——LabTalk 里 '\"' 把引号转义掉，
#   整条命令静默不执行（一个字符的错，表现是“没有报错也没有文件”）。
#   输出目录也必须先建好，否则同样静默失败。
# * tr1.Unit: 0=inch 1=cm 2=pixel 3=页面百分比；4 及以上无效。
# * 没有 dpi 树节点：tr1.DPI / tr1.Res / tr.dpi 之类会让 X-Function 静默失败，
#   tr.Advanced.* 任何叶子都“接受”但对栅格没作用（Advanced 分支不校验名字）。
#   所以栅格分辨率只能用 unit=2 自己算像素：px = cm / 2.54 * dpi。
# * 导出文件里写的 dpi 恒为 300（与像素宽无关），Word 会按 300 dpi 摆放，
#   物理尺寸就成了 2 倍。fix_dpi() 直接改 PNG pHYs / TIFF 282,283 /
#   JPEG JFIF / BMP PelsPerMeter，无损、不重编码。
# * tr.Margin: 2=整页（默认），1/3=裁到墨迹（实测边框剩 2~3 px），
#   0=裁到墨迹再留均匀空白。裁切后的图仍被缩放到请求的像素宽，
#   也就是“裁掉的空白不占印刷宽度”，字看起来会相对变大。
# * 支持的 type:= 只有 png tif jpg bmp gif pcx tga psd emf wmf pdf eps，
#   tiff/jpeg/ps/svg/webp 都会失败（本脚本把 tiff→tif、jpeg→jpg、ps→eps）。
# * page:= 参数不可靠（实测被忽略、导出的是当前激活窗口）。要指定页面
#   就用该页面对象的 LT_execute()，不必也别依赖 win -a。
# * 判断成功不能只看返回值：expgraph 出错时既不抛异常也不返回错误，
#   只能比对目标文件的 mtime/size 是否变化。
# * 页面几何：page.width/height 的单位是 page.resx(dpi) 像素，
#   除以 resx 才是英寸。
# * originpro 没有 op.lt_str，字符串读取是 op.get_lt_str（写错了会静默
#   走 except 分支）。
