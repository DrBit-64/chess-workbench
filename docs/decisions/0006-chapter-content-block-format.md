# ADR 0006：章节内容块格式

- 状态：Accepted
- 提议日期：2026-08-07
- 接受日期：2026-08-09
- 补充接受日期：2026-08-10（来源引用、原子局面说明与阅读呈现）

## 背景

当前 `CourseOccurrence` 树只能表示纯棋谱（着法链 + 行间评注）。但真实棋书的一章还包含：

- 小节标题（"阻塞战术的定义"）
- 叙事段落（不附属任何特定局面，在着法之间穿插）
- 静态棋盘图（用于印刷，但交互界面已用可交互棋盘替代，无需保留）

AI 从 PDF/视频中提取一章内容时，产出的也是这种混合序列。因此 Chapter 的内容格式和 AI 提取格式应该是**同一结构**——否则 AI 导入和用户手工编辑要用两套不同的存储方式，会导致不必要的 migration。

## 决定

### Chapter 内容是 Block 有序序列

一个 Chapter 的内容 = `list[Block]`，其中 Block 是以下类型的标签联合：

```
Block = SectionHeader | NarrativeParagraph | MoveSequence | KnowledgeNote
```

| Block 类型 | 数据 | 棋盘交互 |
|-----------|------|---------|
| `SectionHeader` | 标题文本（纯字符串） | 无 |
| `NarrativeParagraph` | Markdown 文本 | 无 |
| `MoveSequence` | 一棵有根、有序的来源着法树；第一个子节点是主线，其余是作者变例 | **是**——中心棋盘沿当前路径同步更新 |
| `KnowledgeNote` | 对当前棋盘局面的评注（Markdown），可引用 SourceSpan | 停在当前局面 |

### 来源引用与写入边界

- `NarrativeParagraph` 可通过独立的多对多关联引用一个或多个 `SourceSpan`。引用属于
  block，而不是复制进 Markdown；这样 PDF/视频提取和手工正文使用同一溯源结构。
- `SectionHeader`、`MoveSequence` 不直接持有来源；局面相关来源仍属于其
  `KnowledgeNote`。这避免同一来源在章节标题、棋谱容器和实际解释之间出现歧义。
- 新建局面说明时，`KnowledgeNote` 与指向它的 `KnowledgeNote` block 必须在同一事务中
  创建，并追加到 Module 的有序内容流。失败时两者一起回滚，不能留下“保存成功但正文
  不可见”的孤儿说明。
- 对已有 note 的修改只更新 note 本身；其 block 身份和顺序保持稳定。历史快照同时记录
  narrative block 当时的 `source_span_ids`。

### 阅读呈现

传统课程默认按 block 顺序渲染为可阅读正文：叙述段落直接阅读，`KnowledgeNote` 显示在
相邻内容中并可跳到关联局面，`MoveSequence` 是切换棋盘上下文的交互锚点。编辑控件按需
展开，不与默认阅读流争夺版面。Opening Explorer 不复制整章正文；来源观点可打开原
Module 的相邻 block 上下文，并保留到原 occurrence 的导航。

### 棋盘图不保留

`MoveSequence` Block 走到某个局面后，页面中央的可交互棋盘已经展示了那个局面——不需要再存储一张静态棋盘图。OCR 识别出的棋盘图仅用于提取着法和 FEN，提取完成后丢弃原图引用。

### 与现有模型的关系

- `MoveSequence` → 内部展开为一个根 `CourseOccurrence` 及其有序子树（复用现有
  `create_root_occurrence` / `create_move_occurrence`）；只含主线时自然退化为线性链
- `KnowledgeNote` → 复用现有 `KnowledgeNote` 模型，关联到当前 `Occurrence`
- `SectionHeader` / `NarrativeParagraph` → **新模型**，属于 CourseModule 的内容块序列

`CourseOccurrence` 始终只有一个父 occurrence。不同路径到达同一局面时复用全局
`Position`/`MoveEdge`，但不合并带有来源顺序、注释和 NAG 的 occurrence。PGN 的具体映射
由 ADR 0007 定义。

### AI 提取格式

AI 从棋书 PDF 中提取一章时，输出就是这个 Block 序列。经用户审核后直接写入数据库，无需格式转换。

### 实施阶段

Stage 3 的 PGN 导入可以先把“每局棋 → 一个 Module 根及 occurrence 子树”视为一个隐式
`MoveSequence`。在 **Stage 4（三栏课程编辑器）** 开始前，内容块模型与 migration 必须
落地，并把已有 PGN Module 确定性回填为一个显式 `MoveSequence` Block。

## 后果

- ✅ 一章的叙事结构（标题、段落、着法、评注）被完整保留
- ✅ AI 提取结果可以直接导入，无需中间格式
- ✅ 叙述和局面说明都能追溯 SourceSpan，且不会因两个独立写请求产生孤儿内容
- ✅ 同一 block 序列既是存储格式，也是传统课程阅读和 Explorer 原文回看格式
- ✅ 交互棋盘替代静态棋盘图，减少存储和 OCR 复杂度
- ⚠ 需要新模型 `SectionHeader` / `NarrativeParagraph` + Block 有序序列的存储方式
- ⚠ `MoveSequence` 和 `KnowledgeNote` 需要调整以嵌入 Block 序列（当前是独立的树形结构）
