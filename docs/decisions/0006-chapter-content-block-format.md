# ADR 0006：章节内容块格式

- 状态：Proposed
- 日期：2026-08-07

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
| `MoveSequence` | 一个着法序列（多步），每步推进棋盘 | **是**——中心棋盘随走子同步更新 |
| `KnowledgeNote` | 对当前棋盘局面的评注（Markdown），可引用 SourceSpan | 停在当前局面 |

### 棋盘图不保留

`MoveSequence` Block 走到某个局面后，页面中央的可交互棋盘已经展示了那个局面——不需要再存储一张静态棋盘图。OCR 识别出的棋盘图仅用于提取着法和 FEN，提取完成后丢弃原图引用。

### 与现有模型的关系

- `MoveSequence` → 内部展开为一组 `CourseOccurrence` 节点（复用现有 `create_root_occurrence` / `create_move_occurrence`）
- `KnowledgeNote` → 复用现有 `KnowledgeNote` 模型，关联到当前 `Occurrence`
- `SectionHeader` / `NarrativeParagraph` → **新模型**，属于 CourseModule 的内容块序列

### AI 提取格式

AI 从棋书 PDF 中提取一章时，输出就是这个 Block 序列。经用户审核后直接写入数据库，无需格式转换。

### 实施阶段

此格式在 **Stage 4（三栏课程编辑器）** 前落地为模型 + migration。

## 后果

- ✅ 一章的叙事结构（标题、段落、着法、评注）被完整保留
- ✅ AI 提取结果可以直接导入，无需中间格式
- ✅ 交互棋盘替代静态棋盘图，减少存储和 OCR 复杂度
- ⚠ 需要新模型 `SectionHeader` / `NarrativeParagraph` + Block 有序序列的存储方式
- ⚠ `MoveSequence` 和 `KnowledgeNote` 需要调整以嵌入 Block 序列（当前是独立的树形结构）
