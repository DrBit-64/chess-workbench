# ADR 0007：来源有序课程中的 PGN 变例树

- 状态：Accepted
- 日期：2026-08-09
- 修订：ADR 0005 中把 traditional occurrence 限定为严格线性链的部分
- 依赖：ADR 0002、0004、0005、0006

## 背景

ADR 0005 用“traditional 为线性链、opening_explorer 为图”说明两种浏览体验。但合法 PGN
可以包含任意层 RAV（recursive annotation variation），Stage 3 又要求保留变例拓扑、顺序、
comment 和 NAG 并完成语义 round-trip。

若严格把 traditional 限制为一条链，只剩三种选择：丢弃变例、把每条根到叶路径复制成独立
模块，或把任何带变例的 PGN 直接变成 opening_explorer。三者都会破坏来源结构或双模课程的
产品含义。

同时，当前 `CourseOccurrence` 只有一个 `parent_id`。所谓“多父与转置”应发生在共享的
`Position`/`MoveEdge` 图，而不是把带有路径局部语义的 occurrence 变成多父节点。

## 决定

### 1. Course.mode 表达组织方式，而不是是否允许分支

- `traditional` 表示**按来源组织**：Course/Module/Block 保留书、视频或 PGN 的原始顺序。
- `opening_explorer` 表示**按问题与局面组织**：用户把多个 traditional 来源中的观点显式
  发布到探索器，并通过 `source_note_id` 回到原始条目。
- 两种模式中的 MoveSequence 都可以有分支。它们的区别是内容所有权、聚合方式和默认浏览
  体验，不是数据库是否允许一个 occurrence 有多个 child。
- Stage 3 不把 PGN 直接导入 opening_explorer；进入 Explorer 必须使用 ADR 0005 的显式发布
  操作。

### 2. MoveSequence 是有根、有序的作者变例树

- 每个 occurrence 最多有一个父 occurrence；根没有父与入边。
- 同一父节点下，`sort_order=0` 是来源主线，其余 child 按原始 RAV 顺序使用连续的
  `sort_order=1..n`。
- traditional UI 默认沿每个节点的 `sort_order=0` child 线性阅读，但允许用户展开作者变例。
- 两条路径到达相同规范局面时复用全局 Position/MoveEdge；每条来源路径仍保留独立
  occurrence、完整 FEN、顺序和注释。
- 同一父节点下的相同 UCI 可以作为两个独立来源变例出现。因此 occurrence 不能以
  `(parent_id, inbound_move_edge_id)` 唯一；应以 sibling 顺序保证确定性，并在读取/导出时
  明确使用 `sort_order`。
- 服务层必须拒绝 occurrence 环、跨 Course/Module 父子关系、重复 sibling sort order，以及
  恢复归档记录后产生多个活动根的情况。

### 3. 一份 PGN 文档的课程映射

- 一份原始 PGN 文本或文件是一个 Source 工件；来源身份和逻辑导入身份由 ADR 0008 定义。
- 默认解析文档中的**全部 game**；不能静默只取第一局。
- 新建目标时，一次逻辑导入创建一个 `mode="traditional"` Course。
- 每个 game 创建一个顶层 CourseModule，`sort_order` 等于 0-based `game_index`；模块标题使用
  显式标题或 Event/棋手信息的确定性回退。
- 每个 game 在自己的 Module 中创建一个根 occurrence；起始局面来自有效的 SetUp/FEN，
  否则使用标准初始局面。
- PGN game 的主线与 RAV 按上一节映射为一个 occurrence 有序树。一个 game 在 ADR 0006 的
  Block 模型中对应一个 MoveSequence Block。
- 多 game 文档为每局建立独立 SourceSpan；单局可以使用 whole span，多局使用解码文本的
  半开字符区间。

### 4. 来源注解保持在 occurrence 语境

PGN 的以下内容属于来源路径，不得写入全局 MoveEdge：

- 排序、完整 NAG 集合；
- root comment；
- variation 首着之前的 starting comment；
- 普通走后 comment；
- 每条路径的完整六字段 FEN。

Stage 3 使用一对一的 PGN occurrence annotation 记录保存这些 PGN 专用字段；现有单值
`CourseOccurrence.nag` 只能作为兼容字段，不能继续作为 round-trip 的权威数据。

### 5. 导出必须选择明确的来源范围

- 导出一个 Module 时重建该 game 的完整有序 RAV 树。
- 指定 leaf occurrence 时只导出从 Module 根到该 leaf 的当前路径，不隐式附带 sibling；其
  movetext Result 固定为 `*`。
- 导出一次 import receipt 时按 game_index 输出 multi-game PGN。
- 不再假设整个 Course 只有一个根；任何 scope 不明确、跨模块或损坏的路径都返回稳定错误。

## 被否决的方案

### 每条 variation 拆成独立线性 Module

该方案复制公共前缀、难以恢复嵌套关系和原始 sibling 顺序，也会让一局棋在课程目录中膨胀为
大量伪章节。

### 任意带 variation 的 PGN 直接进入 opening_explorer

PGN 变例只是某一来源的作者结构，不等于用户已经把多个来源整理成局面问题。自动进入
Explorer 会绕过显式发布和来源引用边界。

### 合并到同一 Position 后复用 occurrence

这会让一个 occurrence 出现多个父路径，并混合不同路径的 full FEN、comment、NAG 和顺序，
违反 ADR 0004。

### 丢弃或只保留主线

这直接违反 Stage 3 的 round-trip 目标，也会在没有警告的情况下删除用户资料。

## 后果

- ADR 0005 中“traditional=严格线性链”由“来源有序，默认主线线性阅读，单个 MoveSequence
  可含作者变例树”替代。
- Opening Explorer 仍然保持问题导向和跨来源聚合的独特产品语义。
- occurrence 的单父路径语境保持不变；真正的转置继续由 Position 图表达。
- Stage 3 migration 必须调整 sibling 唯一约束并保存明确 sort_order。
- Stage 4 的 Block migration 必须把已有 PGN game Module 回填为一个 MoveSequence Block。
- parser/importer/exporter 必须用显式栈处理长主线和深层 RAV，不能依赖 Python 调用栈。

## 自动验收

1. 主线 child 的 sort_order 恒为 0，其他 variation 连续递增；数据库拒绝同父重复顺序。
2. 同父相同 UCI 的两个来源变例都能保留各自 comment/NAG。
3. 两条转置路径共享 Position，但 occurrence ID、父路径和局部注解不同。
4. traditional 默认导航沿主线，同时 API 可枚举并稳定排序全部作者变例。
5. 多 game PGN 创建一个 Course、N 个有序 Module 和 N 个根。
6. Module 完整树导出与 root-to-leaf 路径导出分别有结构断言。
7. 人工构造环、跨 Course/Module parent、重复 sibling order 和双活动根均被拒绝。
