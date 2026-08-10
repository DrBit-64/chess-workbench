# ADR 0005：双模课程：传统课程与开局探索器

- 状态：Accepted
- 日期：2026-08-06
- 修订：2026-08-10（Explorer 发布改为按局面与共同前缀聚合，不暴露来源章节结构）

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
| Occurrence 结构 | 按来源排序的单父变例树，默认主线阅读 | 按问题和决策点组织的单父变例树 |
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

- 每个底层 Module 的 Occurrence 是按来源顺序排列的单父树。界面默认沿第一子节点阅读主线，但作者在 PGN 中的 RAV 变例必须保留；本点由 ADR 0007 补充并取代旧的“线性链”描述。
- KnowNote 直接包含 markdown 内容，通过 SourceSpan 引用原书位置。
- 章节嵌套用 Module.parent_id 树表示。
- Source → SourceVersion → SourceFile 三层保持不变。

### 3. Opening Explorer：按问题组织

`mode="opening_explorer"` 的课程按问题和决策点组织，与 ADR 0004 描述的模型一致：

```
Course "斯堪的纳维亚防御" (mode="opening_explorer")
└── 内部探索图组件（不沿用来源章节名）
    ├── Occurrence → Position(初始局面)
    │   └── 1.e4 → 1...d5 → 2.exd5
    │       ├── 2...Nf6 → 多个来源引用卡
    │       └── 2...Qxd5 → 多个来源引用卡
    └── 无法与上述图连通的自定义 FEN → 另一个“入口局面”组件
```

Explorer 的主要信息架构是合并后的局面图，不是 Module 目录。`CourseModule` 仅作为当前
单根 occurrence 约束下的内部连通组件：共同起点或起点已存在于图中的来源章节必须合并到
同一组件；确实无法连通的 FEN 才创建另一个匿名入口组件。界面可以让用户切换入口局面，
但不得把来源章节标题重新显示成 Explorer 章节列表。

### 4. 两种 KnowNote

```
Traditional Module 的 KnowNote:        Opening Explorer 的 KnowNote:

  id: uuid                               id: uuid
  occurrence_id: xx                      occurrence_id: yy  (Explorer 中的局面)
  markdown: "黑方最活跃的选择..."          markdown: null
  source_spans: [...]                     source_note_id: uuid  → Traditional 中的原始 KnowNote
  review_status: "approved"
```

Opening Explorer 中的 KnowNote **不重复存储内容**。它是一个**引用卡片**：`markdown` 必须为 null，也不单独保存 SourceSpan；渲染时实时读取 `source_note_id` 指向的原始 Note 及其引用。这避免原始内容修订后出现过期副本。

`source_note_id` 只能直接指向活动的 traditional Course 中、挂在 Occurrence 上且 `review_status="approved"` 的原始 Note。禁止指向 global Note、草稿/已拒绝/已归档 Note，也禁止引用卡再指向另一张引用卡。同一 Explorer Occurrence 不能重复引用同一原始 Note。

只要存在活动引用卡，原始 Note 不得改为非 approved 状态或归档。引用卡先归档后，原始 Note 才可继续生命周期操作。

### 5. 发布关系：从 Traditional 到 Opening Explorer

用户从 Traditional Module 选择章节，发布到 Opening Explorer。系统执行：

1. 遍历该章节的所有 Occurrence 和 KnowNote。
2. 系统先按来源根局面的 Position 在目标 Explorer 中寻找入口；若该局面已在任一组件中，
   从该 occurrence 接入，否则创建一个匿名入口组件。
3. 对每个后续 Occurrence：相同父 occurrence + 相同 MoveEdge 复用同一 Explorer occurrence；
   因而来自多个章节的共同前缀和候选着自动合并。转置仍以共享 Position 表达，路径 occurrence
   保持单父，遵守 ADR 0007。
4. 对每个 KnowNote：在合并后的 Explorer occurrence 上创建一个引用卡片
   （`source_note_id` + `occurrence_id`），不复制 markdown。

这是一个显式操作——不是自动把整本书塞进去。

发布 API 属于 Stage 4C，Stage 2D 只提供上述可验证的存储边界。Stage 4C 的发布必须在一个数据库事务内完成；重试同一组“目标 Explorer Occurrence + 原始 Note”不能新增 occurrence 或引用卡，任意一条来源不合法时整次发布零部分写入。发布不修改原始 traditional Course，也不复制 markdown、NAG、来源 context 或 SourceSpan；这些来源语义由引用卡实时呈现。

### 6. Course 和 Occurrence 的不变量

- Course 一旦拥有 Module 或 Occurrence，`mode` 不得切换；否则已有 Note 会在不经审核的情况下改变语义。空 Course 可修正 mode。
- 通用 Occurrence PATCH 不能把节点移到另一 Module；子树搬迁需要未来的显式原子操作。
- 存在活动子节点的 Occurrence 不能归档。恢复子节点时，其父节点和 Module 必须均为活动状态；恢复根节点不能使同一 Module 出现两个活动根。
- 每个有坐标的 SourceSpan（page/video/text）必须指向同一 SourceVersion 下的 SourceFile；只有 whole locator 可以不指定文件。

### 7. KnowledgeNote 的导航按钮

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
- **发布不会复制来源目录**：多个来源 Module 可以共享同一个 `target_module_id`；该字段表示
  Explorer 的内部连通组件，而不是来源章节的一对一副本。
- **Traditional Course 的默认主线阅读简化了导航**：但作者变例仍按 ADR 0007 保存，每条 UCI 仍必须由 python-chess 校验合法性。
- **导航按钮是前端工作**：不需要新 Schema，但 Occurrence 的 parent_id 和 inbound_move_edge_id 必须正确维护。
- **AI 导入（Stage 8）默认进入 Traditional Module**：因为 AI 处理的是整本书/视频，应保留原书结构。用户在审核后可以选择"将第 X 章发布到 Opening Explorer"。
- **Source → Course 的反向查询**：`list_notes_by_source(source_id)` 可以找到一本书在系统中产生的所有 KnowledgeNote，不需要额外关联表。

## 与现有 ADR 的关系

- **ADR 0004** 的 Occurrence、KnowledgeNote、SourceSpan 设计完全保留。
- **ADR 0004** 中"课程按问题和决策点组织"的描述现在对应 `mode="opening_explorer"`。
- 本 ADR 补充了 `mode="traditional"` 作为另一种同等重要的课程组织方式。
- **ADR 0007** 取代本 ADR 早期对 traditional Occurrence “线性链”的过度约束；两种 mode 都使用单父 occurrence 树，区别是组织与导航语义。
