# dsh-origin-thesis — DSH 论文插图格式工具

把 `origin-batch-style/` 里**已经验证过的**论文绘图格式逻辑，作为**原生 DSH 工具**暴露
出来，在聊天里直接调用；样式集中在 `styles.json`，**改 JSON 就能改格式，不必动 Python**。

## 设计原则：不重写

| 你的资产 | 本插件如何处理 |
|---|---|
| `format_thesis_figures.py` | **原样 import 调用** `format_graph` / `verify_graph` / `font_index` / `PER_GRAPH_TWEAKS` |
| `format_composite.py` | **原样 import 调用** `rescale_page` / `regrid_page` / `format_axes` / `clamp_texts` / `separate_texts` / `add_panel_labels` |
| `export_figures.py` | **原样 import 调用** `export_project` / `parse_types` / `fix_dpi` |
| 三个脚本文件本身 | **一个字节都没改** |
| 页面尺寸/字号/线宽等常量 | 从脚本常量**原值转录**到 `styles.json`；该文件成为真源 |

已做的等价性回归（与你的权威产物逐项比对）：

| 对比项 | 我的产物 | 你的权威产物 | 差异 |
|---|---|---|---|
| `图3_pub` 页面 | 17.5 × 9.762 cm | 17.5 × 9.762 cm | **0** |
| `图3_pub` 图层框架 | 12.19 × 5.063 cm，ratio 1.3716 | 同 | **0** |
| `图4_pub` 页面 | 175.006 × 121.200 mm | 175.006 × 121.285 mm | 高度 0.085 mm※ |
| PNG 像素（图3） | 4134 × 2306 | 4134 × 2306 | **0** |
| PNG dpi 元数据 | **600 dpi**（物理宽 17.501 cm） | 300 dpi（物理宽 35.001 cm） | **本插件已修正** |

※ 来自 `--regrid` 的 `round(...,4)` 在 cm/页面像素之间的一次取整，属设计内。

## 为什么能在 DSH 里跑

- **py3.10 没有 originpro**（只发 ≤3.9 的 wheel），所以服务器必须用你 conda 的
  **`origin` 环境（py3.9）** 启动，`command` 指向它的 `python.exe`。
- 服务器**不需要 `mcp` 包**：它自己实现 MCP stdio JSON-RPC 循环（与
  `dsh-origin-plugin` 的 `_sync_stdio_server` 同构），因此 py3.9/3.10 都能跑，
  也避开事件循环/回环 socket 导致的 60s boot 挂起。
- MCP 客户端复用已装的 `@deepseek-ai/dsh-mcp-client`，不新增依赖。

工具名形如 `mcp__origin_thesis__thesis_*`。

## 十二个工具

| 工具 | 作用 | 需要 Origin |
|---|---|---|
| `thesis_styles_list` | 列出三个配置档与关键参数 | 否（秒回） |
| `thesis_style_show` | 看某配置档完整定义（含继承解析后的值） | 否 |
| `thesis_style_set` | 改 `styles.json`（默认只预演；写前自动 `.bak`） | 否 |
| `thesis_batch_dir_info` | 报告解析到的样式档/脚本/解释器（排障） | 否 |
| `thesis_format_project` | 按 `thesis`/`manuscript` 档格式化**项目内所有图** | 是 |
| `thesis_format_graph` | **只格式化指定的一张图**（原子操作） | 是 |
| `thesis_apply_style_only` | **只套样式，默认不存不导**（原子操作） | 是 |
| `thesis_export_open` | 从**当前已打开**的会话导出（不重开文件） | 是 |
| `thesis_format_composite` | 按 `composite` 档格式化**手工拼版大图**（含 `regrid`） | 是 |
| `thesis_batch` | 多个项目/目录批量格式化，出逐项目报告 | 是 |
| `thesis_export_project` | 只导出不改样式（多格式、统一宽度、裁边） | 是 |
| `thesis_verify_project` | 只读校验字体/字号/缺陷 | 是 |

### 自由组合：原子工具怎么用

后三个原子工具是为**组合**准备的，把"套样式""逐条微调""出图"拆成可单独调用的步骤：

```
① thesis_apply_style_only(project="...\项目.opju", graph="Graph20")   # 只套样式，不落盘
        ↓  同一 Origin 会话里那张图还开着（实测导出只需 0.3 s，而非 20+ s）
② origin_edit_plot(graph="Graph20", edits=[{"plot":1,"color":"#D55E00"}])
   origin_edit_axis(graph="Graph20", axis="y", from_value=0, to_value=90)
   origin_edit_legend(graph="Graph20", options={"position":"tr"})
        ↓
③ thesis_export_open(graph="Graph20", out_path="D:\fig\Graph20.png", dpi=600)
```

| 参数 | 工具 | 说明 |
|---|---|---|
| `graph` | `thesis_format_graph` / `_apply_style_only` / `_export_open` | 图短名或长名（`origin_list_pages` 可查） |
| `save` | `thesis_format_graph` / `thesis_format_project` | false = 不写 opju |
| `export_png` | `thesis_format_graph` / `thesis_format_project` | false = 不出图 |
| `use_open_session` | `thesis_format_graph` / `_apply_style_only` | true = 先在**当前已打开**的项目里找这张图，找不到才回退到打开 `project` |
| `keep_open` | `thesis_format_graph` / `_apply_style_only` | **接力场景必须为 true**（`_apply_style_only` 默认就是 true）。`op.exit()` 会顺带关掉当前项目，设 false 则下一步 `thesis_export_open` 找不到那张图；代价是 Origin 留在后台 |

> **两个已修的坑（都是实测踩出来的）**
>
> **1. 释放不能早于构建返回值。** `origin_release` 一开始永远是 `None`：我在 `finally`
> 里赋值，而返回字典在 finally **之前**就构建完了，改了个寂寞。`finally` 里也不能再读
> `g.name` —— COM 一断就报"对象没有连接到服务器"。现在改为"先释放、再构建返回值"，
> 且图名在 Origin 还活着时先存成字符串。
>
> **2. `op.exit()` 会关掉项目，接力链条会断。** 实测 `thesis_apply_style_only`
> （当时默认释放）跑完就退出了 Origin，紧跟的 `thesis_export_open` 立刻 `ok=false`。
> 所以接力场景要用 `keep_open=true`。


> **代价提示**：`thesis_apply_style_only` 每次仍要起一次 Origin COM 并跑像素量测闭环
> （约 20 秒），这一步做不到毫秒级；但套完之后用 `origin_edit_*` 连续微调都是毫秒级，
> `thesis_export_open` 也是（0.3 秒实测）。


**原文件永不被修改**：格式化在 `%TEMP%` 的副本上做，产出 `<名>_thesis.opju` /
`<名>_pub.opju` + `<名>_..._figures/*.png`（600 dpi，dpi 元数据已修正）。

## 三个配置档

| 配置档 | 用于 | 页面 | 刻度 / 轴标题 / 图例字号 | 线宽 |
|---|---|---|---|---|
| `thesis` | 博士论文插图（按 layer 数重排版面） | 单图 9.8594×7.3999 cm；2 图 16×7.4；3–4 图 16×13.2；6 图 16×10.4；8 图 16×8.6 | 9 / 10.5 粗 / 9 pt | 1.0 pt |
| `composite` | 手工拼好的多面板大图 | 宽 17.5 cm，高按原比例（`regrid` 时重排） | 6.5 / 7.5 / 6.5 pt | 0.75 pt |
| `manuscript` | 期刊投稿单图（保留作者手摆图例） | 同 thesis | 同 thesis | 同 thesis |

`manuscript` 通过 `inherits: thesis` + `overrides`（只改 `move_legend: false`）实现，
改 thesis 会同时影响它。

## 常用调用

```
# 单项目按论文版式（保留作者手摆的图例）
thesis_format_project(project="...\MIL-101-S_graphs.opju", profile="thesis",
                      keep_legend_pos=true, out_dir="...\out")

# 手工拼版大图 + 重排行距（页面按 3 行开好只放了 2 行时）
thesis_format_composite(project="...\图3.opju", regrid=true, out_dir="...\out")

# 批量：整个目录，递归
thesis_batch(projects="D:\papers\thesis", recursive=true, out_dir="D:\figs")

# 只导出（PNG + 矢量 EMF，统一 8.5 cm 宽，裁掉页面空白）
thesis_export_project(project="...\某项目.opju", formats="png,emf",
                      width_cm=8.5, margin="tight")

# 改格式并复核
thesis_style_set(profile="thesis", changes={"tick_pt": 8.5})           # 预演
thesis_style_set(profile="thesis", changes={"tick_pt": 8.5}, dry_run=false)  # 落盘
```

## 排障

- `thesis_batch_dir_info` 先看：`styles_path` 是否指向你要的那份、`batch_dir` 是否
  找到你的三个脚本、`originpro` 是否为 true。
- 找不到脚本/样式档：用环境变量覆盖（在 profile 的 `cordis.patch.yml` 里给同 id 的
  **config-only** 覆盖，见 `cordis.patch.yml` 顶部示例）：
  `DSH_THESIS_BATCH_DIR`、`DSH_THESIS_STYLES`。
- 单张图慢是正常的：要起 Origin COM + 做像素量测闭环，单图约 18–25 秒，23 张约 6–10 分钟。
  工具超时已设 30 分钟。
- 中文文件名：**不要**经 PowerShell 管道传参数——它会把 UTF-8 变成乱码
  （实测 `图3` → `鍥?`）。在 DSH 里调用不受影响（JSON 直传）。
- `thesis_verify_project` 报某层字号偏小（如 `fsize=7.5`）：先看返回里的
  `small_layers`。插图层（`inset` / `linked_inset`，如 NMR 的放大谱）的字号是
  "只缩不放"的，比正文小属于**预期**；校验器已自动把这些层标记为 small 并放行
  （与 `format_thesis_figures.verify_graph` 的 `small_layers` 参数口径一致）。
  若某层不在 `small_layers` 里却字号偏小，那才是真问题。

## 能力边界（如实说明）

服务器只做事编排与样式注入，**版面、锚点标定、标注互推等全部由你的脚本执行**，
所以 `fit_axis_titles` 的渲染标定、`clamp_texts`/`separate_texts` 的像素量测闭环
都**原样保留**，没有退化。

真正没接过来的是 `format_composite.py` 末尾那步：它会把报告写到
`origin-batch-style/work/format_composite_report.json`；本插件改为把报告**随工具返回**
（`layers` / `settle_rounds` / `panel_labels` 字段），不落盘到你的脚本目录。

### 一个已修的坑（值得记下）

`verify_graph` 的 `small_layers` 参数不能省。早期版本我传了 `None`，导致插图层
（如 `图拆` 的 `Graph18` L2，`linked_inset`，刻意用 7.5 pt）被误报成字号不符——
**而同一 bug 让批量那轮的"零问题"变成假绿**。现在校验器会先跑
`analyze_layers` 算出 small 集合再校验，口径与脚本自己的 `main()` 一致。


## 安装态

- 插件包：`C:\Users\liuxc\dsh-vendor\dsh-origin-thesis\`
- 挂载：web profile 的 `package.json`（`dsh-origin-thesis` bundle + link 依赖），
  junction 到 `node_modules\dsh-origin-thesis`
- 条目：profile 的 `cordis.patch.yml` 里 `mcp-origin-thesis`
  （`serverName: origin_thesis`，超时 1800000 ms，`failOnStartupError: false`）
- 卸载：从 `dsh.profile.bundles` 与 `dependencies` 移除 `dsh-origin-thesis`
  → `pnpm install` → 重启 Harness；再删掉 profile 补丁里的 `mcp-origin-thesis` 段。
  你的脚本与 `origin-batch-style/` 完全不受影响。
