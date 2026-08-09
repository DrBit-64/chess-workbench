# ADR 0008：PGN 语义、来源资产、幂等导入与 HTTP 边界

- 状态：Accepted
- 日期：2026-08-09
- 依赖：ADR 0002、0004、0007

## 背景

Stage 3 的初版逻辑可以处理若干 happy path，但没有产品 API、Source 所有权、幂等记录或完整
事务边界。headers 被塞进 Course.description，parser 只返回第一局并丢失部分 FEN、comment
和 NAG；导出比较器又会忽略这些差异。输入限制和 MySQL 行为也没有可靠门禁。

本 ADR 冻结 Stage 3 必须支持的语义范围、持久化归属、HTTP 契约和资源边界。PGN 仍然只是
Source/导入导出格式；Position/MoveEdge 与课程 occurrence 继续是可编辑知识模型。

## 决定

### 1. 支持的是语义等价，不是字节等价

PGN semantic document 必须保存并比较：

- 文档中的全部 game 及顺序；
- 所有合法、名称唯一的 tag pair，包括 ECO、Annotator 等自定义 header；
- header Result 与 movetext termination，并验证二者一致；
- 起始完整六字段 FEN，包括原始 en-passant 格、半回合钟、回合号和行棋方；
- 每个节点的 ply、SAN、标准小写 UCI 和走后完整 FEN；
- RAV 拓扑与 sibling 顺序；
- root、starting 和普通 comment 的 Unicode 文本与位置；
- 每个节点排序去重后的全部 NAG。

以下不属于语义等价：空白与换行风格、tag 顺序、brace/semicolon comment 语法、等价 SAN 的
原始拼写、NAG 的文本或数字写法。导出使用规范 move number、SAN、escaping 和换行。重复 tag
name、header/result 冲突、非法 UTF-8/NUL 和无法无损映射的输入返回 `invalid_pgn`，不得静默
选择一个值。

### 2. Source 工件与逻辑导入是两种身份

原始 UTF-8 bytes 的身份为：

```text
content_sha256 = SHA256(raw_bytes)
```

不规范化 BOM、换行、空白或 header。相同 bytes 经 JSON、raw text 或 multipart 进入系统时
复用同一 PGN asset 和 Source 链：

```text
PgnAsset → Source(kind="pgn") → SourceVersion → SourceFile
```

- upload 和 paste 都生成不可变 SourceFile；paste 使用服务端合成文件名。
- 真实路径只由 hash 生成，例如 `sources/pgn/ab/<sha256>.pgn`；客户端 filename 仅作显示
  metadata，绝不参与路径。
- 单 game 建 whole SourceSpan；多 game 按严格 UTF-8 解码后的字符半开区间建 text span。
- 相同 bytes 导入到不同目标可以产生不同 PgnImport/Course 内容，但不得重复 Source 链。

一次成功的逻辑导入由不可变 `PgnImport` receipt 表示。逻辑指纹为：

```text
SHA256(
  "pgn-import:v1" + content_sha256 +
  canonical_json(destination_without_expected_version,
                 explicit_titles,
                 mapping_version)
)
```

`expected_version` 是一次并发前置条件，不进入逻辑身份。

### 3. 持久化归属

新增四类 PGN adapter 记录；它们保存来源和导入 provenance，不取代课程图：

- `PgnAsset`：`content_sha256` 全局唯一，并一对一引用其 Source、SourceVersion、SourceFile；
  保存字节数。
- `PgnImport`：保存有效幂等 key hash、逻辑指纹、asset、目标 Course、mapping version、game/
  occurrence 总数和提交后的 Course version；只记录成功导入。
- `PgnImportGame`：保存 import、0-based game_index、Module、根 occurrence、SourceSpan、全部
  headers、movetext result、semantic hash 和 occurrence 数。
- `PgnOccurrenceAnnotation`：以 occurrence_id 为主键，保存全部 NAG、starting comment 与普通
  comment。

`headers` 使用有序 `{name,value}` 数组，而不是 Course/Module description。PgnImport 相关外键
均为 RESTRICT；Course 归档不删除 receipt 或 Source。现有单值 occurrence.nag 暂时保留兼容，
但 PGN annotation 是 round-trip 权威值，后续只能通过单独兼容 migration 移除旧字段。

### 4. 统一导入 API

```http
POST /api/pgn/imports
Idempotency-Key: <可选的 1..128 字节可见 ASCII>
```

同一路径支持：

- `application/json`：`pgn`、判别联合 `destination`、可选 `source_title`；
- `text/plain; charset=utf-8` 或 `application/x-chess-pgn`：使用默认 new_course 目标；
- `multipart/form-data`：恰好一个 `file` 和可选的 JSON `options` part。

destination 为：

```text
new_course:
  kind = "new_course"
  title = optional

existing_course:
  kind = "existing_course"
  course_id = UUID
  expected_version >= 1
```

- new_course 创建 `mode="traditional"` Course。
- existing_course 必须存在、未归档且为 traditional；每局追加一个顶层 Module，整个请求只把
  Course version 增加一次。
- 直接导入 opening_explorer 返回 `course_mode_conflict`。
- raw body 不能表达 existing_course；需要该能力时使用 JSON 或 multipart options。
- unknown JSON field、额外 multipart part、多文件、空文件或非法 options 都返回稳定错误。

首次成功返回 `201 Created` 和 `Location: /api/pgn/imports/{id}`。响应包含 receipt、Source 链、
Course ID/version，以及每局的 Module/root/SourceSpan/occurrence 数。另提供：

```http
GET /api/pgn/imports/{import_id}
```

receipt 没有 PATCH 或硬删除 API。

### 5. 幂等与并发规则

- 有 `Idempotency-Key` 时只保存 key 的 SHA-256，不保存或记录原文；无 header 时使用自动逻辑
  指纹作为有效 key。
- 相同 key 与相同逻辑指纹返回原 receipt、原 ID 和 `200 OK`，设置
  `Idempotency-Replayed: true`，所有业务表计数及 Course version 不变。
- 相同 key 与不同逻辑指纹返回 `409 idempotency_conflict`，零写入。
- 无显式 key 的相同逻辑请求自动重放；同内容但不同目标或显式标题是新逻辑导入，但复用
  PgnAsset/Source。
- 并发相同请求通过数据库唯一约束和 savepoint 收敛到一个 winner；所有成功/重放响应指向
  同一 receipt。
- 幂等查询早于 existing_course 的 expected-version 检查；原成功请求重放时不能因 Course
  version 已变化而返回 stale。
- Stage 3 不提供 `force_new`。需要重复副本时使用未来的显式 Course clone 操作。

### 6. 事务与文件边界

Stage 3 保持同步 HTTP，不提前引入 job 系统。处理顺序固定为：

1. 限制并读取唯一 PGN payload，计算 raw SHA-256，严格解码 UTF-8。
2. 在 SQL 事务外完成 bounded parse、全部 game/FEN/move/result 预验证和逻辑指纹计算。
3. 将原始 bytes 写入 Source CAS 同目录临时文件，校验 size/hash 后原子 rename，权限限制为
   当前用户；已存在 blob 必须再次核对 hash。
4. 开启唯一一个 `session.begin()`，先处理幂等 replay/conflict，再创建或复用 asset/Source，
   并写 Course、Module、Occurrence、annotation、span 和 receipt。
5. 事务提交后返回；任一异常回滚所有 SQL 业务行。

先落 CAS、后提交 SQL 可以保证数据库绝不引用缺失文件。数据库失败可能留下未引用 blob，
它不是正式数据，可由 Stage 8 的安全 GC 清理；不得为了清理失败而回滚已提交 SQL。CAS 写入
失败返回 `source_storage_unavailable`，且不开启业务写事务。

### 7. 导出 API 与响应

```http
GET /api/courses/{course_id}/pgn?module_id={module_id}
GET /api/courses/{course_id}/pgn?module_id={module_id}&leaf_occurrence_id={leaf_id}
GET /api/pgn/imports/{import_id}/download
```

- module_id 必填，避免对多根 Course 猜测；无 leaf 时导出完整 Module RAV 树。
- 有 leaf 时验证其属于该 Course/Module 且为根的后代，只导出 root-to-leaf；Result 固定 `*`。
- receipt download 按 game_index 生成 multi-game PGN。
- 导出使用 PgnImportGame headers，而不是 Course.description；手工创建且没有来源 header 的
  Module 使用确定性的标准默认 header。
- exporter 维护 visited occurrence ID 和节点上限；环、跨模块边、缺失 MoveEdge 或不明确 scope
  返回 `pgn_not_exportable`，不得裸递归或静默跳过。

下载响应至少包含：

```text
Content-Type: application/x-chess-pgn; charset=utf-8
Content-Disposition: attachment; filename="safe-name.pgn"; filename*=UTF-8''...
Content-Length: <bytes>
ETag: "<rendered-bytes-sha256>"
Cache-Control: no-store
X-Content-Type-Options: nosniff
```

filename 必须过滤 CR/LF、引号、路径分隔符和控制字符。

### 8. 稳定错误契约

沿用 `{code,message,details?}`：

| HTTP | code | 场景 |
|---|---|---|
| 413 | `payload_too_large` | PGN part 超过 5 MiB |
| 415 | `unsupported_media_type` | 不支持的 Content-Type |
| 422 | `invalid_pgn` | UTF-8、语法、FEN、棋步、tag/result 不合法 |
| 422 | `pgn_limit_exceeded` | game/node/RAV/deadline 上限 |
| 409 | `idempotency_conflict` | 同 key 对应不同逻辑请求 |
| 409 | `course_mode_conflict` | 目标不是 active traditional Course |
| 409 | `pgn_not_exportable` | occurrence/export 结构损坏或 scope 不明确 |
| 409 | `stale_version` | existing_course 乐观锁失败 |
| 503 | `source_storage_unavailable` | CAS 无法安全写入或校验 |
| 404 | `not_found` | import/course/module/leaf 不存在 |
| 422 | `validation_error` | JSON/multipart/query shape 非法 |

棋谱错误 details 至少包含可获得的 `game_index`、root=0 的 `ply`、0-based child-index `path`、
line/column、token 和稳定 reason；不得暴露 python-chess 异常、SQL、绝对路径或堆栈。

### 9. 固定资源与安全边界

- 单 payload：5 MiB；multipart 总上限可为边界开销略高，但 file part 精确执行 5 MiB。
- 单请求：最多 1,000 game、50,000 个 move occurrence、RAV 嵌套 128。
- 合法 5,000-ply 主线必须成功；主线 ply 与 RAV nesting 是不同限制。
- 2-core CI 中处理不超过 15 秒，峰值 RSS 低于 512 MiB。
- parser/importer/exporter 使用显式栈，不依赖 Python recursion；导出还维护 visited set。
- 不自动解压 zip/gzip，不接受 URL 让服务器抓取，不调用任何公网服务。
- header/comment/filename 始终视为不可信数据；PGN escaping、HTTP header 过滤和前端 HTML/
  Markdown 清理分别执行，不能互相替代。

## 自动验收

1. Runtime OpenAPI 和生成 TS 类型覆盖 JSON/raw/multipart、receipt、module/path export 和
   multi-game download；unknown field/part 有确定响应。
2. JSON 连续两次、multipart 连续两次和 JSON→multipart 跨 transport 重放取得相同 receipt/
   course/module/root ID，所有相关表计数不变。
3. 同 key 不同 content/target/title 返回 409 且零写入；SQLite/MySQL 并发相同请求只生成一个
   receipt。
4. 单 game 精确创建一个 Source 链/Span/Course/Module；N-game 创建一个 Source 链、N 个 Span
   和有序 Module；同 bytes 不同目标复用 Source。
5. 在 Source、Module、第 N 个 occurrence、annotation 和 receipt 收尾阶段注入异常，全部 SQL
   业务表保持请求前计数；错误含准确 game/ply/path。
6. 全部修正后的 golden fixtures 与 multi-game fixture 执行
   `parse all → import → export → parse all → semantic compare`；逐字段 mutation 必须失败。
7. 5 MiB/50,000 move/RAV 128 的边界值通过，越界值分别返回 413/422；合法 5,000-ply 无
   RecursionError，性能/RSS 满足门槛。
8. module tree、root-to-leaf 和 multi-game download 分别断言结构、result、header 和全部安全
   响应头；跨 Course/Module leaf 与人工损坏结构返回稳定错误。
9. 同一 Alembic schema 与共享 API/domain fixture 在 SQLite/MySQL 都运行；PGN 关键模块覆盖率
   至少 90%，全局保持 80% line / 75% branch。

## 后果

- Stage 3 需要 additive migration、新的 PGN adapter repository/service 以及 Source CAS 配置。
- Course.description 恢复为用户描述，不再承载隐藏 headers JSON。
- 原始 PGN 可追溯、逻辑导入可重放，Source 与 Course 不再被混成同一身份。
- 同步事务足以完成本阶段；失败/取消任务状态机仍留到 Stage 6。
- 文件 CAS 的未引用 blob 清理与完整文件生命周期在 Stage 8 完成，但 Stage 3 必须保证 SQL
  永不引用缺失或 hash 不符的文件。
