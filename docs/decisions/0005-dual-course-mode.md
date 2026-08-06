# ADR 0005：双模课程：传统课程与开局探索器

- 状态：Accepted
- 日期：2026-08-06

## 背景

ADR 0004 建立的课程语境模型以局面图为核心，课程按问题和决策点组织，不同来源对同一局面的观点通过 KnowledgeNote 并列展示。这种模型在开局理论场景中表现优秀——同一局面下多本书给出不同推荐，用户在候选着中选择。

但国际象棋教程的类型远不止开局理论树：

- **中局专题**：作者选取彼此无关的典型局面，每个局面讲解一种战术思想或计划。这些局面不共享根节点。
- **残局定式**：从给定 FEN 开始，演示关键着法。分支少，重点是解释。
- **开局例局**：一条线性对局从头走到尾，展示某种开局的典型发展。不需要候选着分支。
- **整本书/视频系列**：作者按自己的逻辑组织章节，章节内是线性叙事。用户需要按原书顺序浏览。

如果将所有这些内容强行塞入"按问题合并"的单一模型，会导致三个实际问题：

1. **中局和残局没有"同一局面多来源"场景**，Opening Explorer 的组织方式对它们不适用。
2. **即使开局书也有大量例局**，不是每本书都按照开局树的形式编写。
3. **用户需要两种浏览体验**：一种是"按作者的原书结构从第一章读到最后一章"，另一种是"在开局树上探索分支并比较不同来源的观点"。

## 决定

### 1. Course 增加 `mode` 字段

```
mode: "traditional" | "opening_explorer"
```

| 属性 | traditional | opening_explorer |
|------|-------------|------------------|
| 组织方式 | 按来源（一本书/视频系列 → 章节） | 按问题和决策点（开局主题 → 变例分支） |
| Occurrence 结构 | 线性链（parent_id 单链） | 图（多父、转置合并、多分支） |
| 来源引用 | KnowNote 通过 SourceSpan 指向原文 | KnowNote 通过 source_note_id 引用 traditional 模块中的原始 KnowNote |
| 典型对象 | 整本棋书、视频系列、中局专题、残局手册 | 开局探索器（用户自建或从 traditional 导入） |

### 2. Traditional Course：按来源组织

`mode="traditional"` 的课程按作品的自然结构组织：

```
Course "The Amateur's Mind" (kind="book")
├── Module "Part 1"          ← parent_id=null
│   ├── Module "Chapter 4: 阻塞战术"  ← parent_id=Part1
│   │   ├── Occurrence → Position(局面1)  ← 线性 linked list
│   │   │   └── KnowNote(内容、SourceSpan)
│   │   ├── Occurrence → Position(局面2)
│   │   └── Occurrence → Position(局面3)
│   └── Module "Chapter 5"
└── Module "Part 2"
```

- 每个底层 Module 的 Occurrence 构成线性链（单 parent_id）。
- KnowNote 直接包含 markdown 内容，通过 SourceSpan 引用原书位置。
- 章节嵌套用 Module.parent_id 树表示。
- Source → SourceVersion → SourceFile 三层保持不变。

### 3. Opening Explorer：按问题组织

`mode="opening_explorer"` 的课程按问题和决策点组织，与 ADR 0004 描述的模型一致：

```
Course "斯堪的纳维亚防御" (mode="opening_explorer")
├── Module "2...Nf6"
│   ├── Occurrence → Position(1.e4 d5 2.exd5 Nf6)
│   │   ├── 候选着 3.d4 → MoveEdge → Position(...)
│   │   │   └── KnowNote(引用 traditional 中的原始 Note)
│   │   ├── 候选着 3.c4 → MoveEdge → Position(...)
│   │   │   └── KnowNote(引用 traditional 中的原始 Note)
│   │   └── 候选着 3.Nc3 → MoveEdge → Position(...)
│   │       └── KnowNote(引用 traditional 中的原始 Note)
│   └── ...
└── Module "2...Qxd5"
```

### 4. 两种 KnowNote

```
Traditional Module 的 KnowNote:        Opening Explorer 的 KnowNote:

  id: uuid                               id: uuid
  occurrence_id: xx                      occurrence_id: yy  (Explorer 中的局面)
  markdown: "黑方最活跃的选择..."          markdown: null | "缓存副本"
  source_spans: [...]                     source_note_id: uuid  → Traditional 中的原始 KnowNote
  review_status: "approved"
```

Opening Explorer 中的 KnowNote **不重复存储内容**。它是一个**聚合卡片**——markdown 可以从 `source_note_id` 指向的原始 Note 渲染；它自身的价值在于把来自不同书的多个观点按局面组织在一起。

### 5. 发布关系：从 Traditional 到 Opening Explorer

用户从 Traditional Module 选择章节，发布到 Opening Explorer。系统执行：

1. 遍历该章节的所有 Occurrence 和 KnowNote。
2. 对每个 Occurrence：在 Opening Explorer 中复用或创建 `position_key` 和 MoveEdge。
3. 对每个 KnowNote：在 Opening Explorer 中创建一个引用卡片（`source_note_id` + `occurrence_id`），不复制 markdown。

这是一个显式操作——不是自动把整本书塞进去。

### 6. KnowledgeNote 的导航按钮

在 Opening Explorer 界面中，每个 KnowledgeNote 卡片提供三个操作：

| 按钮 | 语义 | 实现 |
|------|------|------|
| [←] 上一步 | 在 Opening Explorer 中，沿 occurrence 链回溯到父局面 | `occurrence.parent_id` |
| [→] 下一步 | 在 Opening Explorer 中，沿 occurrence 链前进到第一个子局面 | 查询子 occurrence |
| 跳转到条目 | 跳转到 Traditional Module 中该 KnowNote 所在的原始位置（原书章节） | `source_note_id → 原始 Note → 原始 occurrence → 原始 Module → 在 traditional course 中定位并展开` |

点击 KnowledgeNote 的标题等效于"跳转到条目"。KnowledgeNote 默认锚定一个局面节点；不需要支持"一个 Note 跨越多个连续局面"——连续的说明由多个 Note 组成，用户用 [←] [→] 在它们之间导航。

## 后果

- **Course 表需要 `mode` 字段**：在 Stage 2 migration 中加入，默认值 `"traditional"`。
- **KnowledgeNote 表需要 `source_note_id` 字段**：可空的外键，指向同表的另一条记录。这是 Opening Explorer 引用 Traditional 内容的桥梁。
- **发布操作需要新 API**：`POST /api/courses/:id/publish-modules` 接收一组 module_id，将选中章节的内容发布到指定的 Opening Explorer course。
- **Traditional Course 的线性链简化了验证**：不需要处理多父或转置合并，但每条 UCI 仍然必须由 python-chess 校验合法性。
- **导航按钮是前端工作**：不需要新 Schema，但 Occurrence 的 parent_id 和 inbound_move_edge_id 必须正确维护。
- **AI 导入（Stage 8）默认进入 Traditional Module**：因为 AI 处理的是整本书/视频，应保留原书结构。用户在审核后可以选择"将第 X 章发布到 Opening Explorer"。
- **Source → Course 的反向查询**：`list_notes_by_source(source_id)` 可以找到一本书在系统中产生的所有 KnowledgeNote，不需要额外关联表。

## 与现有 ADR 的关系

- **ADR 0004** 的 Occurrence、KnowledgeNote、SourceSpan 设计完全保留。
- **ADR 0004** 中"课程按问题和决策点组织"的描述现在对应 `mode="opening_explorer"`。
- 本 ADR 补充了 `mode="traditional"` 作为另一种同等重要的课程组织方式。
