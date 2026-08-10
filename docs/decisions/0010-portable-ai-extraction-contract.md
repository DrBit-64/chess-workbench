# ADR 0010：可移植 AI 识别交换格式与双向适配边界

- 状态：Accepted
- 日期：2026-08-11
- 补充：澄清 ADR 0006 中“AI 输出直接成为 Block 序列”的边界；不取代 ADR 0006 的课程正文模型

## 背景

Stage 8 最初只要求把 PDF/OCR/AI 候选导入 ChessWorkbench，因此 ADR 0006 将 AI 输出描述为
课程 `Block` 序列。后续需求要求同一识别模块能够接入其他网站。如果模型响应直接包含
`CourseModule`、`KnowledgeNote`、数据库 UUID 或 ChessWorkbench 的审核状态，那么：

- 更换 DeepSeek、千问、OpenAI 或本地模型会影响业务代码；
- 其他网站必须理解 ChessWorkbench 的数据库和四层领域模型；
- 提取、棋规验证、人工审核和正式发布会被混成一个不可复用步骤；
- 内部模型演进会破坏已经保存或导出的识别结果。

本项目需要同时解耦两个方向：模型供应商是输入侧可替换端口，识别结果是输出侧可移植契约。
这不意味着提前拆成独立微服务；第一版仍在模块化单体内实现清晰边界。

## 决定

### 1. 冻结独立交换格式 CCEF v1

定义 **Chess Content Extraction Format（CCEF）**，首个版本标识固定为：

```text
chess-content-extraction/1.0
```

CCEF 的规范化 JSON 是识别模块唯一的跨系统输出。机器可读契约以仓库中固定版本的 JSON
Schema 发布；Python Pydantic 模型是本项目的严格实现与 Schema 生成源。外部消费者只需要
JSON Schema，不需要 Python、Sanic、SQLAlchemy 或 ChessWorkbench 数据库。
字段级规范见 [`docs/architecture/ccef-v1.md`](../architecture/ccef-v1.md)。ADR 决定所有权
和依赖方向，字段规范冻结 v1 的精确合法值；实现不得自行补充第三种解释。

CCEF 不出现以下内部概念：

- SQL 主键、`Course`、`CourseModule`、`CourseOccurrence`；
- `KnowledgeNote`、`Repertoire`、`Exercise`；
- 乐观锁版本、归档状态、内部审核记录；
- DeepSeek/OpenAI 请求形状或供应商错误码。

### 2. 包结构

`ExtractionPackage` 包含：

| 字段 | 含义 |
|---|---|
| `schema_version` | 固定为 `chess-content-extraction/1.0` |
| `package_id` | 本次规范化结果的 UUID，不是任何消费者数据库 ID |
| `source` | 调用者提供的不可解释 `source_ref`、媒体类型、语言和可选页段 |
| `items` | 按来源阅读顺序排列的有序内容项；列表顺序是唯一权威顺序 |
| `diagnostics` | 包级或 item 级、供应商无关的 info/warning/error |
| `provenance` | 生成时间、适配器版本、可选供应商/模型名和请求/响应内容哈希 |
| `extensions` | 可选、显式、反向域名命名空间的 JSON 值；未知顶层字段仍被拒绝 |

`source_ref` 是调用网站定义的不透明字符串。识别核心不得假设它是路径、URL 或
ChessWorkbench UUID。

### 3. 来源证据

每个有语义的 item 和每个候选棋步都携带一个或多个 `EvidenceRef`：

- PDF 页码从 1 开始；
- bbox 使用左上角原点和 `[0, 1]` 归一化坐标；
- 可选字符半开区间 `[start_offset, end_offset)`；
- 可选 `fragment_sha256` 校验原文片段；
- 页码必须落在 package 声明的页段内；bbox 必须有正面积。

CCEF 保存识别后的文本和证据引用，而不是只保存消费者内部的 SourceSpan ID。这样其他
网站即使采用不同来源模型，也能显示、审核和重新定位原文。

### 4. 内容项判别联合

`items` 是严格的判别联合：

| `kind` | 必需语义 |
|---|---|
| `heading` | 1–6 级标题和文本 |
| `prose` | 原文顺序中的 plain/markdown 文本，可选锚定到棋步或明确 FEN |
| `move_sequence` | 初始局面和一棵来源有序候选棋步树 |
| `figure` | 棋盘图、照片、插图或其他图形证据；允许尚未解析 |
| `unresolved` | 无法可靠分类但不能静默丢失的原文/图形及原因 |

所有 item 有 package 内唯一的 `id`、至少一个证据、可选 `[0, 1]` 置信度和结构化 warning。
模型自报置信度只是审核提示，不能覆盖确定性验证结果。

`prose` 的锚点是可移植引用：

- 无锚点表示叙述性正文；
- `move_node` 锚点引用同一 package 中的 sequence item 与 node；
- `position` 锚点携带候选完整 FEN。

因此 ChessWorkbench 可以把无锚点正文映射为 `NarrativeParagraph`，把棋步锚定正文映射为
候选 `KnowledgeNote`，其他网站可以采用不同的展示或存储方式。

### 5. 来源有序棋步树

`move_sequence.nodes` 使用扁平、拓扑有序的节点列表，避免把内部 Position 图暴露给外部：

- `id` 在 sequence 内唯一；
- `parent_id=null` 表示从 sequence 初始局面出发；父节点必须先出现；
- 相同父节点下 `sibling_order` 唯一且从 0 连续；0 是来源主线，其余是作者变例；
- `move_text` 保存来源中的原始棋步文本；
- `san_candidate`、`uci_candidate`、`fen_before`、`fen_after` 都是可选候选字段；
- `validation_status` 为 `unvalidated|valid|invalid|ambiguous`；只有本地棋规验证器可以写入
  `valid` 及权威规范化字段；
- 节点自身也携带证据、NAG、置信度和 warnings。

模型不能仅凭棋盘图片宣告一个局面有效。`python-chess` 必须从明确初始局面沿候选棋步重建
路径；非法、断裂或多解内容保留在 CCEF 中并标记 warning，不得伪造合法结果。

### 6. 四段流水线与依赖方向

识别流程固定为：

```text
Source/OCR fragments
    -> StructuredGenerationProvider
    -> CCEF decoder and assembler
    -> structural + referential + python-chess validation
    -> ConsumerAdapter
```

依赖只能朝下游：

- `extraction` 核心可依赖标准库、Pydantic，棋规验证子模块可依赖 `python-chess`；
- `extraction` 不得导入 Sanic、SQLAlchemy、store、HTTP domain schema 或课程 service；
- provider 实现只负责鉴权、超时、重试、结构化生成和用量元数据，不写数据库；
- provider 接口接收调用者提供的 JSON Schema，不能硬编码 CCEF 或某个网站的输出格式；
- ChessWorkbench consumer adapter 可以依赖 CCEF 和内部服务，反向依赖禁止；
- 原始供应商响应与规范化 CCEF 分开保存，供应商私有字段不能混入核心 item。

第一版默认 provider 是 DeepSeek V4 Flash 非思考模式；V4 Pro、千问、OpenAI 和本地模型只是
后续可选 adapter。默认供应商不改变 CCEF。

### 7. ChessWorkbench 映射不是 CCEF 的组成部分

审核通过前，CCEF 只是一份可移植候选包。ChessWorkbench consumer adapter 执行以下映射：

| CCEF | ChessWorkbench 候选 |
|---|---|
| `heading` | `SectionHeader` |
| 无锚点 `prose` | `NarrativeParagraph` + SourceSpan |
| `move_sequence` | 来源有序 `MoveSequence` occurrence 树 |
| 有棋步/局面锚点 `prose` | `KnowledgeNote` + SourceSpan |
| 已解析 `figure(chessboard)` | 仅作重建/审核证据，成功后不复制静态棋盘图 |
| `unresolved` 或 error diagnostic | 必须人工处理的审核 warning |

映射产生消费者自己的草稿/审核 ID，但不能回写或改变原始 CCEF package。批准、修改、拒绝、
多来源合并和正式 SQL 发布仍属于 ChessWorkbench Stage 8D。

### 8. 版本与兼容性

- `1.x` 只允许新增可选字段或新的 namespaced extension；既有字段语义不变；
- 删除字段、收紧既有合法值或改变棋步树语义必须发布新 major；
- 消费者必须拒绝不支持的 major，不得猜测降级；
- 相同规范化 JSON 使用确定性序列化计算内容哈希，以支持缓存、幂等和跨站传输；
- CCEF v1 的 JSON Schema 必须作为测试夹具固定，生成漂移会使门禁失败。

## 后果

- ✅ DeepSeek 充值、模型升级或供应商切换不会改变消费者协议；
- ✅ 其他网站可以直接消费 CCEF JSON 或实现自己的 ConsumerAdapter；
- ✅ ChessWorkbench 内部模型和审核流程不会泄漏进识别核心；
- ✅ 未识别内容通过 `unresolved` 保留，避免模型静默删减原书；
- ✅ 棋规有效性由确定性程序证明，不由模型置信度决定；
- ✅ 第一版仍是模块化单体，不提前引入部署、队列或网络微服务；
- ⚠ 需要维护版本化 JSON Schema、兼容性夹具和 provider/consumer 双向契约测试；
- ⚠ DeepSeek JSON Object 不是完整 JSON Schema 保证，decoder 必须拒绝或修复不合约输出；
- ⚠ CCEF 不包含消费者审核状态，因此跨网站同步审核结果需要未来单独协议，不能塞进 v1。
