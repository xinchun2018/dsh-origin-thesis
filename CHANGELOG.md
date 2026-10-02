# Changelog

## 1.0.0 — 2026-10-02

首个公开发布版本。

### 能力

- **12 个 MCP 工具**，把 Origin 插图格式化接进 DeepSeek Harness：
  - 离线（不连 Origin）：`thesis_styles_list`、`thesis_style_show`、
    `thesis_style_set`、`thesis_batch_dir_info`
  - 批量：`thesis_format_project`、`thesis_format_composite`、`thesis_batch`、
    `thesis_export_project`、`thesis_verify_project`
  - 原子/可组合：`thesis_format_graph`、`thesis_apply_style_only`、
    `thesis_export_open`
- **三套样式配置档**（`styles.json`，改 JSON 即可调格式，不必动 Python）：
  - `thesis` — 博士论文插图：按 layer 数自动选版式（单图 4:3、2 图 1×2、
    3–4 图 2×2、6 图 2×3、8 图 2×4），Times New Roman，
    刻度 9 pt / 轴标题 10.5 pt 粗体 / 图例 9 pt，线宽 1.0 pt。
  - `composite` — 手工拼好的多面板大图：整页缩到 17.5 cm 宽，按角色统一
    字号（标题 7.5 / 刻度 6.5 / 标注 5.5 pt），补 (a)(b)(c) 面板标签并收边。
  - `manuscript` — 期刊投稿单图：继承 `thesis`，只保留作者手摆的图例位置。
- **随包绘图脚本**（vendored，可直接替换）：`format_thesis_figures.py`、
  `format_composite.py`、`export_figures.py`。
- **零 Python 依赖的 MCP 层**：服务器自己实现 stdio JSON-RPC 循环，不需要
  `mcp` 包，py3.9 / 3.10 均可。
- **600 dpi 导出 + dpi 元数据修正**：Origin 一律写 300 dpi，插件直接改
  文件头（PNG pHYs / TIFF 282,283 / JPEG JFIF / BMP PelsPerMeter），
  不重编码，保证插进 Word 后物理尺寸正确。

### 保留的关键行为（来自原工具链，未重写）

- `fit_axis_titles`：渲染 → 量底部墨迹 → 标定轴标题锚点偏移，多轮收敛。
- `clamp_texts` / `separate_texts`：按渲染结果收边，并在**垂直方向**互推
  避让重叠（横坐标指向峰位，左右挪会指错峰）。
- 插图层（inset / linked_inset）字号「只缩不放」，校验时按预期放行。
- 竖排堆叠谱图（XPS 分峰、质谱对比）整叠算一个面板，不拆进网格。
- 页面锚定对象与插入图片的重映射；图例串与 `\g()` Symbol 区域绝不改写。

### 已知边界

- 仅 Windows：Origin 的 COM 自动化接口只在 Windows 提供。
- 需要本机安装正版 Origin；插件不打包 Origin，也不含绘图内核。
- 需要装了 `originpro` 的解释器（该包目前只发 ≤ py3.9 的 wheel）。
- 单张图约 20–30 秒：必须启动 Origin COM 并跑像素量测闭环。
