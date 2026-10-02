# Origin 批量论文插图格式化

把 Origin 项目（.opju）里所有 Graph 统一成博士论文插图格式：按 layer 数量自动
区分单图/双图/四图排版、统一页面物理尺寸、统一字体字号、统一坐标轴样式，
并按 600 dpi 导出 PNG。**原文件不会被修改**，结果另存为 `<原名>_thesis.opju`。

## 用法

```powershell
C:\Users\liuxc\miniconda3\envs\origin\python.exe format_thesis_figures.py `
    --project "C:\path\to\某项目.opju"
```

可选参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--out-dir` | 输入文件所在目录 | 输出目录 |
| `--suffix` | `_thesis` | 输出文件名后缀 |
| `--dpi` | 600 | PNG 导出分辨率 |
| `--font` | Times New Roman | 统一字体 |
| `--skip-multilayer` | 关 | 跳过多 layer 复杂图（完全不动，留给用户手动调） |
| `--keep-legend-pos` | 关 | 不把图例挪到框架右上角（图例已手工避开曲线时用） |
| `--no-tweaks` | 关 | 不套用本项目的逐图微调（`PER_GRAPH_TWEAKS`，按输入文件名主干分组） |
| `--show-origin` | 关 | 运行时显示 Origin 界面 |

输出：`<名>_thesis.opju`（格式化后的项目）＋ `<名>_thesis_figures\*.png`（按页面
实际厘米尺寸 × dpi 导出，可直接插入论文）。

## 统一的样式（脚本顶部 STYLE / LAYOUTS / CELL_MARGIN 可改）

- **排版**：1 layer → 4:3 规格（2026-08 审稿回复需求）：页面 98.594×73.999 mm，
  图层框架 (left 1.499, top 0.5503, 宽 7.59, 高 5.698) cm，由 `LAYOUTS[1]["margins"]`
  精确给出（页面与图层宽高比均 ≈4:3）；2 layers → 16×7.4 cm (1×2)；3–4 layers →
  16×13.2 cm (2×2)；6 layers → 2×3。多图自动删除旧的 (a)(b)(c)(d) 标签并在每个
  面板左上角外侧重建（12 pt 粗体）。**竖向堆叠谱图**（XPS 分峰、质谱对比等，
  各层同宽同左、纵向紧邻）整叠算一个面板，不拆成网格：宽度用单图版式的
  7.59 cm，页面高度按保持各层原宽高比算出。链接层堆叠走 `vertical_stack`，
  普通独立层堆叠走 `plain_vertical_stack`（几何逐层写）。
- **字体**：全部 Times New Roman。刻度 9 pt；轴标题 10.5 pt 粗体；面板标签
  12 pt 粗体；图内标注（晶面指标、Experiment 等）8 pt；图例 9 pt。
- **坐标轴**：轴线与主/次刻度线粗细 1.0 pt（`thickness`/`tickThickness`/
  `mtickThickness`）；主刻度线长 3.6 pt；显示的主/次刻度一律朝内；
  轴标题重定位到统一距离（X 轴下方 0.80 cm、Y 轴左侧 0.95 cm，无刻度数字的
  轴 0.55 cm）；图例移入框架右上角。
- **曲线**：线宽统一 1.0 pt；数据点符号大小统一 4 pt（无符号的图不受影响；
  柱状图对应边框宽 1 pt）。
- **不动的东西**：数据、坐标轴范围、曲线颜色线型、插图图片内容、标注的
  锚定位置（跟随数据坐标）。

## 实现要点（改脚本前值得知道的坑）

- 页面尺寸：`page.width/height` 单位是 `page.resx`(dpi) 像素；layer 用
  `layer.unit=3`（cm）后设 left/top/width/height。
- 文本对象一律通过 PyOrigin 句柄 `SetNumProp('fsize'/'font', …)` 设置——
  LabTalk 名字路径遇到叫 `Text` 的对象会撞保留字静默失败。
- 轴标题里的 `\f:Arial(...)`、`\pNN(...)` 转义会覆盖对象字体字号，必须改写
  文本剥掉包装；但含 `%(` 替换串（如 `%(?X)` 占位标题）不能包 `\b()`，否则
  替换失效标题消失。
- 插入的图片对象（EMF/DIB…）不随 layer 缩放（物理尺寸固定），且分两种锚定：
  框架锚定的存储坐标是陈旧缓存（渲染自动跟随，别动位置），页面锚定的存储
  坐标是实时值（layer 移动后须显式写回等比映射位置）——脚本用"存储坐标是否
  变化"区分两者。
- `label -p X Y` 的坐标是相对当前激活 layer 框架的百分比，不接受负值；
  框架外定位要先创建再写对象 `.x/.y`（轴坐标，锚点为文本中心）。
- `layer.x.ticks` 不是"标签偏移"而是刻度样式位掩码：1=主刻度朝内、2=主刻度
  朝外、4=次刻度朝内、8=次刻度朝外，可相加。脚本读出当前值后把显示中的
  主/次刻度重映射为朝内，位为 0（隐藏）的保持隐藏。刻度线粗细是独立属性
  `tickThickness`（主）/`mtickThickness`（次），不跟随 `thickness`。

## 只导出、不改样式：`export_figures.py`

通用导出器：把**任何** .opju/.opj 里的所有图导成图片文件，一个字节都不改项目
（只读打开）。跟格式化脚本互补——格式化脚本只导出它自己动过的图，这个谁都能导。

```powershell
# 最常用：每张图按自己的页面尺寸 600 dpi 导成 PNG
C:\Users\liuxc\miniconda3\envs\origin\python.exe export_figures.py "某项目.opju"

# 投稿要 PNG + 矢量 EMF，统一 8.5 cm 单栏宽，裁掉页面空白
... export_figures.py "某项目.opju" --type png,emf --width-cm 8.5 --margin tight

# 一整个目录 / 通配符，按项目管理器文件夹分子目录
... export_figures.py D:\papers --recursive --tree --out-dir D:\figs
```

默认输出 `<项目所在目录>\<项目名>_figures\<窗口短名>.png` ＋ `export_manifest.json`
（每张图的页面 cm 尺寸、像素宽、文件、层数、PE 文件夹，便于后续脚本处理）。

| 参数 | 默认 | 说明 |
|---|---|---|
| `--type` | png | 逗号分隔多格式；栅格 png/tif/jpg/bmp/gif/pcx/tga/psd，矢量 emf/wmf/pdf/eps |
| `--dpi` | 600 | 栅格分辨率（像素宽 = 页面 cm ÷ 2.54 × dpi） |
| `--width-cm` / `--width-px` | 页面原尺寸 | 统一印刷宽度 / 像素宽度 |
| `--margin` | page | `tight` = 裁掉页面周围空白（裁完再缩到目标宽度，字会相对变大） |
| `--name` | short | `long`/`both`/`auto` 用窗口长名 |
| `--tree` | 关 | 按项目管理器文件夹建子目录 |
| `--pattern` / `--exclude` | — | 按短名或长名通配符筛选，可多次 |
| `--overwrite` | replace | `skip` = 已存在就不导 |
| `--no-fix-dpi` | 关（默认修正） | 见下 |
| `--graphs-only` / `--embedded` | — | 只导 Graph 窗口 / 连嵌入工作表里的图一起导 |
| `--dry-run` | 关 | 只列清单不导出 |

**dpi 元数据修正**：Origin 无论导出多少像素，写进文件的 dpi 一律是 300 ——
600 dpi 的图插进 Word 会变成两倍大。脚本导完直接改文件头
（PNG pHYs / TIFF 282,283 / JPEG JFIF / BMP PelsPerMeter，无损不重编码），
让声明的物理尺寸正好等于 Origin 里的页面尺寸。用
`Revised manuscript_graphs_thesis.opju` 的 25 张图对比过：像素与字节数
和 `format_thesis_figures.py` 导出的完全一致，只有 dpi 元数据从 300 变成 600。

### expgraph 的坑（实测 Origin 2021 / 9.8，脚本末尾 NOTES 有完整版）

- `path:=` 结尾**不能留反斜杠**（`"…\"` 把引号转义掉），输出目录也必须先建好，
  否则 X-Function 静默不执行——不报错、不产文件。所以判断成功只能比对目标
  文件的 mtime/size 是否变化。
- `tr1.Unit`：0=inch 1=cm 2=pixel 3=页面百分比（4 以上无效）。
- **没有 dpi 节点**：`tr1.DPI`/`tr.dpi` 之类会让整条命令静默失败；
  `tr.Advanced.*` 任何叶子都"接受"但对栅格无效（Advanced 分支不校验名字）。
  想要 600 dpi 只能自己算像素走 `unit=2`。
- `tr.Margin`：2=整页（默认），1/3=裁到墨迹，0=裁到墨迹再留均匀白边。
- `type:=` 只认 png tif jpg bmp gif pcx tga psd emf wmf pdf eps；
  tiff/jpeg/ps/svg/webp 都失败（脚本自动把 tiff→tif、jpeg→jpg、ps→eps）。
- `page:=` 参数不可靠（实测被忽略，导出的是当前激活窗口）；指定页面要用
  该页面对象的 `LT_execute()`。
- originpro 没有 `op.lt_str`，字符串读取是 `op.get_lt_str`（写错会静默进
  except，`format_thesis_figures.py:745` 的 `yr.text$` 就是这么一直读空的，
  好在有 `yr_real` 兜底）。

## 辅助工具

`inspect_opju.py <project.opju> [preview_dir]`：枚举项目里所有 graph/layer 的
尺寸、字体、对象清单，导出当前状态预览图 —— 改样式前先看看现状用。

`inspect_43.py <project.opju> [preview_dir]`：轻量几何检查——只读每张图的
页面尺寸(mm)与各 layer 框架(cm)及宽高比，输出 JSON + 预览图，验证版式用。

`probe_ms.py <project.opju> <out.json>`：全量状态转储——每张图每层的几何、
四条轴属性、所有图形对象（名字/字号/字体/颜色/attach/矩形）与每条曲线的
线宽符号，规划改动前先看现状。

`cmp_objs.py <orig.opju> <formatted.opju> [graph ...]`：回归对比——把两个
项目里同名文本对象的位置换算成**框架相对坐标**再比，专抓"格式化后标注跑
位"。只看 `att=1.0`（页面锚定）那几行；`att=0/2` 的读回值是陈旧缓存，差值
大不代表真跑位（`3D` 是不可见的系统对象，永远在名单里，忽略）。

`contact_sheet.py <目录或通配符> -o out.png [--cols 4] [--cell 480]`：把一批
导出的 PNG 裁掉白边拼成带图名的联系表——一次看完整批图的版面，比逐张翻快得多，
验收整批格式化结果时先看它。

`probe_axis_title.py <project.opju> [GraphName ...]`：轴标题定位诊断——读回
`xb.y`/`yl.x` 换算成"距框架边缘 cm"，再做"写入→渲染→读回"看渲染是否重排。
怀疑标题压在刻度数字上时用它分清是"写不进去"还是"锚点偏移"。

`probe_export_opts.py [project.opju]`：探测当前 Origin 版本的 expgraph 能力——
支持哪些 `type:=`、哪些树节点有效、`tr1.Unit`/`tr.Margin` 各值什么语义。
`export_figures.py` 的结论就是这么测的；换 Origin 版本后重跑一次即可。

## 2026-08 处理审稿回复项目（UNTITLED.opju 4:3 版式）补充的坑

- `page.width/height` 赋值别用 LabTalk 表达式（`page.resx/2.54*9.8594`）：
  表达式求值结果被**截断**成整数像素（2328.99 → 2328，读回 98.552 mm 而非
  98.594）。像素数在 Python 里 `round()` 好写整数常量。
- `layer.y2.showLabels` 是**休眠开关**：Origin 默认模板四条轴全为 1，但
  右轴整条边未启用时并不渲染。判断"真有右轴刻度标签"须同时满足
  `showLabels > 0` 且 `layer.y2.showAxes` 含位 2（默认模板无框线 =1，
  带框线/双 Y 轴 =3）。否则默认样式图（如 Graph5）会被误判成双 Y 轴，
  右边距被加宽、图层变窄（本项目症状：7.59 cm 写成 6.86 cm，右边距
  恰好等于左边距）。注意 `showLabels`/`showAxes` 组合仍不能区分
  "带框线但顶轴无标签"（x2 常见 1/3），仅右轴判定够用。
- 新旧 layer 宽高比不同时（4:3 改版），图片对象改用 `min(sx, sy)` 等比
  缩放，按轴分别缩放会拉变形 TEM 照片。
- `op.save()` 之后 LabTalk 的 layer 读数上下文会失效（读回值 ≈ 目标
  矩形 × resx/屏幕dpi，纯假象）——验证保存结果要重新打开文件读。

## 2026-08 处理 SI 汇总项目时补充的能力与坑

- 全项目扫描：`op.graph_list()` 默认 `select='f'` **只列当前 PE 文件夹**，
  图分文件夹存放的项目必须用 `graph_list('p')`。
- layer 分类：unit=7 链接层分 overlay（双 Y 轴，铺满父层）与 linked_ext
  （如 -100% 偏移的堆叠谱图）；非链接层中框架中心落在别的层内部且明显
  更小的是 inset（放大插图）。含 inset/linked_ext 的图走 preserve 模式：
  不重排面板，整页等比缩放到 16 cm 宽。
- 链接层的框架渲染用**陈旧缓存**：父层大幅移动后读回值看似正确但渲染
  错位，且链接状态下写几何被忽略——必须 `layer.link=0` 解除链接后再显式
  写框架。
- 双 Y 轴：右轴刻度标签属于 `y2`（`layer.y2.label.pt`），只设 x/y 管不到；
  可见的右轴标题是 YR 对象（不能当占位符跳过，占位符特征是空白或含
  `%(`）；检测到右轴时右边距加宽到与左边距相同。
- `\g(...)` 区域（Symbol 字体）必须整体原样保留：内部常有
  `\f:Times New Roman(C)` 把个别字符切回正常字体（如 `130\g(°\f:...(C))`），
  剥掉内层包装会让 C 变成希腊字母 Chi、DMPO 变成 ΔΜΠΟ。
- `layer.x.label.rotate` 旋转刻度标签后，**下一次渲染**会自动重排轴标题、
  覆盖手工写的 xb.y——需要"写入→强制渲染(导出 dummy PNG)→读回校验→
  重写"循环直到位置保住。
- LabTalk 赋值表达式里内嵌属性求值（如 `xb.y = 1.55/layer.height*...`）
  结果不可靠，数值一律在 Python 里读出算好再写常量。
- 曲线样式用 `GPlot.set_cmd()`：`set -w` 线宽单位是 **1/500 pt**（实测
  `-w 500` 在 600 dpi 渲染 8 px ≈ 1 pt），`set -z` 符号大小直接是 pt。
  plot 句柄跨渲染（save_fig 等）会失效，取 `plot_list()` 后须单趟用完。
- 个别图的专项微调集中在脚本顶部 `PER_GRAPH_TWEAKS`（Python 函数，
  接收 GPage）。

## 手工拼好的大图统一格式：`format_composite.py`

`format_thesis_figures.py` 是**按 layer 数重排版面**；已经手工拼好网格的多面板
大图（正文 图3/图4，SI 的 UNTITLED/UNTITLED2）走 `format_composite.py`：
版面不动，只等比缩到印刷宽度 + 按角色统一字号/字体/线宽 + 加 (a)(b)(c) 标签
+ 收边。原文件不改，结果另存 `<名>_pub.opju` ＋ 600 dpi PNG。

```powershell
# 网格本来就规整（图4：3x3 差最后一张，行距已是所需留白）
C:\Users\liuxc\miniconda3\envs\origin\python.exe format_composite.py `
    --project "C:\Users\liuxc\tu\图4.opju"

# 页面按 3 行开好只放了 2 行（图3：行距 3.96 cm 是所需的两倍，底部空一整行）
C:\Users\liuxc\miniconda3\envs\origin\python.exe format_composite.py `
    --project "C:\Users\liuxc\tu\图3.opju" --regrid
```

统一后的值（`STYLE`）：页面宽 17.5 cm；Times New Roman；轴标题 7.5 pt、
刻度数字/曲线标识/图例 6.5 pt、图内标注 5.5 pt、面板标签 8 pt 粗体；
轴线/刻度线 0.75 pt、刻度长 2.6；曲线 0.75 pt、符号 3 pt。

主要参数：`--regrid`（重排行距+裁掉页面空白）、`--row-gap`/`--bottom`
（--regrid 的行距/底边距，**最终印刷 cm**，默认 1.21 = 已验收参考图的值）、
`--page-w`、`--no-rescale`、`--no-panel-labels`。

### 2026-08 处理正文 图3/图4 补充的坑

- **图例文本绝对不能改写**。图例串是"每条 `|` 或换行分隔一个条目"的独立语法，
  Origin 先切条目再逐条解析转义；整串外包一层 `\b()` 会让第 1 条变粗体、
  最后一条尾巴上多出一个 `)`（图4 六个面板全中招）。判据不能只看 `%(`——
  图4 的图例是写死的文本（`\l(1)\b( 500 ppm) | …`）没有替换串，必须按对象名
  `Legend` 直接豁免。字号/字体照常设。
- 图例框要跟着**一起收边**，且 pad 比标注大（0.12 vs 0.05 cm）：字号统一后
  图例框长高，原先贴着框线摆的会压住贴边的曲线（图4 面板 a 的 Ti-BDC-180
  就是条紧贴下框线的平线）。
- 字号是绝对 pt、页面却缩到 0.60 倍 → 文字相对面板放大约 1.35 倍，**原先手工
  留的水平间隙会被吃光**（图3 面板 b 的 `Ti³⁺ 2p₁/₂`、面板 d 的 `C=O` 直接
  叠到相邻的 Ti-BDC-xxx 上）。`separate_texts()` 只在**垂直方向**互推：这些
  标注的横坐标指向具体峰位，左右挪会指错峰。顺序必须是"先收边再互推"——
  反过来会把刚推开的又压回边界。
- `rescale_page()` 写完几何后要把新百分比写回 `rec["pct"]`：后面的面板标签
  定位和收边都读这个字段，留着旧值会按错误框架算。
- `--regrid` 用 `layer.unit=3`（cm）直接写最终几何，写完切回 `unit=1`
  让 Origin 自己折算百分比（切 unit 是**转换存储值**，不是重新解释数字）。
  行距按最终印刷 cm 给再除以缩放比换算回原页面坐标——X 轴刻度数字+轴标题
  需要的那条留白由绝对字号决定，与缩放比无关。
- 页面留白只裁不补：图3 六个面板重排后页面 17.5×9.76 cm（原 20.07 cm 高的
  等比结果），底部空白连同多余行距一起消失。


## 2026-08 处理正文投稿图（Revised manuscript_graphs.opju）补充的能力与坑

来源：`extract_origin_graphs.py` 从 `Revised manuscript.docx` 抽出的 25 个
graph 窗口——原稿的每张图是把 3–4 个窗口分别贴进 Word 拼的，所以每个窗口
只有一个面板，且面板摆在 29×20 cm 大画布的某个象限里。按单图版式重排后
（页面 9.8594×7.3999 cm）逐张统一，用 `--keep-legend-pos`（图例都是作者
手工避开曲线摆的）。

新增能力：

- **竖向堆叠谱图当一个面板**（`vertical_stack()`）：一个普通层 + 若干
  unit=7 链接层、每层 rel=(0, k×100, 100, 100) 的结构（XPS 分峰谱），
  按单图版式排、框架高度等分给各层。只写父层几何，链接层自动跟随
  （实测读回的 cm 正好等间距，渲染也对）——不要为它解链接，解了会
  丢掉共享 X 轴。判定链接层的相对矩形要**直接读 unit=7 下的值**，
  切 unit 是转换存储值，会破坏相对坐标。
- **含图片的层保持原框架宽高比**：图片只能等比缩放，而挂在坐标轴上的
  标注是随框架各方向拉伸的——宽高比一变（本项目 Fig1 的 NMR 原框架
  2.06 vs 版式 1.33），化学位移标注就对不上结构式上的原子。改为按宽
  定高并在单元格里垂直居中。
- **X 轴标题防裁切自检**（`fit_x_title()`）：`xb.y` 的锚点语义不一致，
  含上/下标或 `\g()` Symbol 区域的标题框更高，按固定 cm 距离写位置会有
  一批图（2θ (degree)、Relative pressure (P/P0)、Temperature (°C)…）
  被页面下边缘裁掉。改为渲染→量测底部墨迹→上移的闭环，底部留白目标
  0.12 cm，同时保证与刻度数字之间至少 0.08 cm。
- `IMAGE_PREFIXES` 加 `__OLECNT`：Word 里粘进来的 OLE 对象（ChemDraw
  结构式）也是不随 layer 缩放的图片。

新坑：

- **图例文本一律不改写**的判据要按转义认，不能只认对象名：作者会复制
  一个 `Text` 对象当第二个图例（Fig8 的 `\l(4)\b( Add TBA+BQ) | …`、
  Graph4 的 `\l(1) …`）。判据 = 名字以 Legend 开头 **或** 文本含 `\l(`。
- **页面锚定对象（attach=1）必须显式重映射**，且判据只能用 attach：
  存储坐标的"实时值"是**惰性刷新**的——没对对象做过写操作时（纯文本
  对象）读回的还是改页面尺寸前的旧像素，光靠"坐标变化"判断会漏判
  （症状：Graph9/Graph11 的 "Spent" 跑到别的曲线上）。图片因为先被
  SetWidth/SetHeight 碰过，反而能被旧判据抓到。
- **位置第一次写入无效**：改完页面尺寸后第一次 `SetLeft` 会被按旧页面
  几何换算（写 1812 读回 518，`SetTop` 却正常），渲染一次刷新内部几何
  后重写才生效 → `settle_objects()` 做"写入→渲染→重写→校验"闭环。
- `lt_str("yr.text$")` 在本项目读不到（返回 None），可见的右轴标题只能
  从对象文本判定（`format_text_objects()` 返回 `yr_real`）。X 轴反向的图
  （NMR/FTIR/XPS）Y 标题挂在 YR 上、渲染在**视觉左侧**，`yr.x = xt + d`
  给出的就是那一侧的统一距离；`.y` 不能重置（堆叠图的 YR 竖跨整叠）。
- 字号是绝对 pt 而框架从 ~11 cm 缩到 7.59 cm → 文字相对面板放大 ~1.4 倍，
  原先刚好排开的标注会连成一串（Graph12 的 `C-N`+`Ti-O-C`、Graph16 的
  `459.02 eV`+`Ti 2p`）。按 `PER_GRAPH_TWEAKS` 只在**纵向**错开——横坐标
  指着峰位，左右挪会指错峰。分类轴的长标签（Graph8 的催化剂名）改 45°
  旋转 + 压低框架高度：45° 比 30° 水平伸展短 1/3，最左那条才不顶出页面。
- 小图预览里轴标题看着发绿/发紫是**亚像素抗锯齿假象**（裁下来放大只有
  黑白 + 边缘条纹），`xb.color/yl.color` 读回都是 1（黑），别去"修"它。

## 2026-08-27 处理拆分单图项目（图拆.opju）补充的能力与坑

`图拆.opju` = 手工拼好的多面板大图拆成 23 个单面板窗口，每个窗口仍带着
原拼版的大页面（17.5×12.1 cm）和面板在某象限的位置。直接跑格式化脚本即可
（`--keep-legend-pos`，图例是作者避开曲线摆的），23 张全部落到
9.8594×7.3999 cm 标准页。

- **逐图微调必须按项目分组**：`PER_GRAPH_TWEAKS` 原来只按图名匹配，而
  `Graph8`/`Graph12`/`Graph16` 这种短名在不同项目里是完全不同的图（本项目
  Graph8 是动力学曲线，正文项目 Graph8 是分类轴柱状图）——套错会把 45°
  旋转刻度标签加到别人头上。现在外层 key 是输入 `.opju` 的文件名主干，
  另加 `--no-tweaks` 一键关掉。
- **轴标题的锚点偏移因图而异**，`reposition_axis_titles()` 按固定 cm 距离
  写位置在这批图上有一半标题压在刻度数字上：同为 10.5 pt 标题、同样的框架，
  写 `xb.y` = 框架下 0.80 cm，Graph2 渲染出来墨迹顶在 0.50 cm、Graph10 却在
  0.22 cm（差 0.28 cm），Y 标题同理。写入本身是有效的（写 0.8/1.6/0.3 渲染
  位置 1:1 平移，`probe_axis_title.py` 实测），纯粹是锚点语义不一致。
  → 新增 `fit_axis_titles()`：**不猜锚点，按渲染结果标定**——① 先把标题写到
  页面外（渲染被裁掉）量出刻度标签外缘；② 扫一组探测值（含写到**页面外**的：锚点偏移 k 实测 0～0.6 cm 因图而异，k 大时标题会缩回刻度标签里、只有写到页面边缘外才分得开）量出标题墨迹近端，得锚点偏移 k——远端被页面裁掉不影响标定，只用近端；③ 目标近端 = max(刻度外缘 + 0.12 cm, 0.16 cm)，
  写 d = 近端 + k 后进入校正环：渲染→量测→按残差修正 k、越出页面边缘就往回收（最多 4 轮），实测 23 张图的 X 标题与刻度数字间距收敛到 0.10–0.14 cm。X/Y/右 Y 三个
  方向同一套逻辑（量测带分别取框架下方 / 左侧 / 右侧，另一维限制在框架范围内，
  免得把 Y 刻度混进 X 的量测）。替代了原来只防"被页面下缘裁掉"的
  `fit_x_title()`。
- 标定失败（如 X 轴反向图的 YR 渲染在视觉左侧、右侧量不到墨迹）**必须把
  对象写回原值**——失败时它还停在最后一次探测位置（页面外）。`try_fit()`
  先存原值，量不到就换另一侧再试，仍失败才恢复原位。
- **链接层不一定要走 `preserve`**：unit=7 的链接层随父层自动缩放，只要它的
  相对矩形落在父层框架内（本项目 NMR 图里那段 7.0–7.2 ppm 放大谱），就是
  "跟着走的插图"，父层照常按标准版式重排即可。原来一律判成 `linked_ext` →
  整页只等比缩到 16 cm 宽 → 面板只有 3.4 cm、字比图还大。新增
  `linked_inset` 分类（rel 在 [-15,115]% 内），只有真正整层偏移到父层之外的
  才留给 `preserve`/`vertical_stack`。
- **插图层的字号只缩不放**（`format_layer_axes(keep_size=)` /
  `format_text_objects(keep_size=)`）：插图框只有几毫米宽，把它的刻度数字
  从 3 pt 放大到正文 9 pt，"7.2" 和 "7.0" 会糊成 "7.27.0"。`verify_graph()`
  相应放行插图层的小字号。

