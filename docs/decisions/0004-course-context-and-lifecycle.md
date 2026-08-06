# ADR 0004：课程语境、来源层次与生命周期契约

- 状态：Accepted
- 日期：2026-08-06

## 背景

`Position` 和 `MoveEdge` 是可由不同着序、课程和资料共享的棋规事实。如果把 NAG、排序或说明直接写在全局边上，一本书或一门课程的观点会覆盖另一份语境。另一方面，`Source` 若同时表示作品、版本和磁盘文件，也无法准确表达“同一本书的不同版次使用不同页码”和“同一版次有多个文件”的关系。

Stage 2C 还需要在没有 route 和 repository 的情况下先冻结 HTTP 边界，使后续数据库与 OpenAPI 实现能够用自动测试判断兼容性。

## 决定

### 1. 全局事实与课程 occurrence 分离

- `Position` 和 `MoveEdge` 只保存棋规可推导的全局事实；它们不保存课程排序、NAG 或局部说明。
- `Occurrence` 是课程中的一次出现，显式引用 `course_id`、可选 `module_id`、共享 `position_id`、完整 FEN，以及可选的父 occurrence 和入边。
- 根 occurrence 的 `parent_id` 与 `inbound_move_edge_id` 都为空；非根 occurrence 两者必须同时存在。
- 客户端不能直接写入上述派生引用：`RootOccurrenceCreate` 接收 `course_id`、可选 `module_id` 和 `fen`；`OccurrenceMoveCreate` 接收 `parent_occurrence_id` 和 `uci`。服务端负责解析局面、执行合法着、复用或创建全局事实，并填充 `position_id`、入边和完整 FEN。
- `nag`、`sort_order` 和扩展 context 属于 occurrence。同一 Position 可以在同一课程或不同课程中出现多次，因此“父节点”查询必须携带 occurrence/path 语境。
- 创建 `CourseModule` 时可选提供 `start_fen`，避免模块与尚未创建的 occurrence 形成循环依赖；read contract 的 `start_occurrence_id` 可空，并在服务端创建根 occurrence 后绑定。`start_occurrence_id` 引用课程语境，而不是仅引用全局 Position。

### 2. 说明默认局部，全局说明必须显式

- 创建普通说明时只需提供 `occurrence_id`，这是安全默认值。
- 全局说明必须省略 `occurrence_id`，并提供判别明确的 `global_position` 或 `global_move` target。
- 同时提供局部和全局 target、或两者都不提供，均为契约错误。
- `KnowledgeNote` 可以引用多个 `SourceSpan`；ID 不得重复。更新说明不能悄悄改变 target。
- 人工创建说明默认 `review_status=approved`；`draft` 保留给需要显式审核的自动导入或生成流程。

这使“将局部作者观点提升为全局知识”成为显式操作，而不是字段遗漏造成的副作用。

### 3. Source 表示作品、版本和文件三层

- `Source` 表示概念作品，例如一本书、一段视频或一篇网页文章。
- `SourceVersion` 表示具体版次、发布日期和版本级元数据。
- `SourceFile` 表示某个版本的不可变文件内容，以 SHA-256、相对路径、媒体类型和字节数描述。
- 文件路径必须是安全的 POSIX 相对路径；文件内容变化创建新文件记录，不用 PATCH 改写哈希或路径。
- `SourceSpan` 至少引用 `SourceVersion`，需要文件坐标时同时引用 `SourceFile`。

### 4. SourceSpan 使用判别联合

Span locator 只能是以下一种：

- `whole`：整个版本；
- `page`：从 1 开始的页码，以及可选的归一化 bbox；
- `video`：整数毫秒的半开区间 `[start_ms, end_ms)`；
- `text`：字符偏移半开区间 `[start_offset, end_offset)`。

bbox 使用左上角原点和 `[0, 1]` 坐标，必须具有正面积。判别联合禁止把页码和视频时间等互斥字段混在同一对象中。

### 5. 更新、归档和错误契约

- 所有实体使用 UUID。可编辑资源的 read contract 包含服务器生成的 UTC 时间、`version >= 1` 和可空 `archived_at`。
- `Position` 和 `MoveEdge` 是不可变事实：read contract 仅添加 `id` 与 `created_at`，不提供 PATCH/update contract，也不允许通过归档隐藏仍被 occurrence 引用的事实。
- 其余 PATCH contract 必须提供 `expected_version` 和至少一个实际修改字段。
- 归档通过 `archived: true` 表达，恢复通过 `archived: false` 表达；归档不是硬删除，也不得级联删除共享 Position、MoveEdge 或来源引用。
- `SourceFile` 的事实字段不可 PATCH；它的更新契约只承载归档/恢复。
- Stage 2 的稳定错误形状为 `{code, message, details?}`。首批固定 code 为：
  - `invalid_fen`
  - `illegal_position`
  - `invalid_uci`
  - `illegal_move`
  - `invalid_move`
  - `not_found`
  - `stale_version`
  - `resource_referenced`
  - `ambiguous_context`
  - `validation_error`
- Pydantic contract 全部使用 `extra="forbid"`，避免客户端拼错字段后被静默忽略。

## 后果

- 两个课程可以共享同一局面和着法，同时保持各自的顺序、NAG 和说明。
- 课程导航必须以 occurrence 为中心；仅凭 Position ID 无法定义唯一父节点。
- 数据库实现需要对 Course、Module、Occurrence、Source、Version、File、Span 和 Note 建立相应外键与版本约束。
- route 层必须用 `model_fields_set` 区分“PATCH 未提供字段”和“显式清空可空字段”。
- repository 必须实现 expected-version 条件更新，并把零行更新稳定映射为 `stale_version` 或 `not_found`。
- 本 ADR 只冻结 HTTP 契约和所有权边界，不在此阶段实现 route、repository、级联归档或文件写入。
