# 架构概览

## 当前决策

ChessWorkbench 从一个本地优先的模块化单体开始：React SPA 通过 HTTP 读取和写入 Sanic API，正式数据只保存在 SQL 数据库中。第一阶段使用 SQLite；领域稳定后增加 MySQL/MariaDB 兼容测试。

```text
React SPA
  └─ SWR /api/*
       └─ Sanic application services
            ├─ Pydantic API schemas
            ├─ domain（棋规与局面身份，不依赖 HTTP）
            └─ repositories / SQLAlchemy → SQLite（后续 MySQL）
```

Stage 6 已加入 SQL 后台任务、Stockfish、Syzygy 和 WebSocket 失效通知；OCR 与 AI 会在
后续阶段进入系统，但不会改变以下边界：

1. 后端 SQL 数据是正式事实源；
2. 前端 `chess.js` 只能做交互预检，持久化棋步由 `python-chess` 验证；
3. PGN 是导入导出格式，Position/MoveEdge 局面图才是内部模型；
4. Source、Knowledge、Repertoire、Exercise 是不同领域概念；
5. WebSocket 只发轻量失效通知，客户端收到后由 SWR 重新取数；
6. AI 结果先进入候选和审核流程，不能直接写入正式知识。

## 代码边界

- `frontend/src/app`：路由和应用外壳；
- `frontend/src/components`：跨功能展示组件；
- `frontend/src/logic/api`：HTTP 客户端与从生成契约派生的类型；
- `backend/src/chess_workbench/api`：传输层与应用组装；
- `backend/src/chess_workbench/schemas`：Pydantic API 契约；
- `backend/src/chess_workbench/domain`：局面身份、FEN/棋步规则和稳定领域错误，不依赖 Sanic 请求对象；
- `backend/src/chess_workbench/store/models`：持久化模型与数据库约束；
- `backend/src/chess_workbench/store` 的 repository：事务内的数据访问与并发收敛；API 不直接拼装 SQL。

## 局面图与课程语境

Stage 2 已接受的架构决定记录在 ADR 0002–0004：

- 当前只接受标准国际象棋；`position_key` 使用带版本的 `standard:v1:` 身份，保留子布局、行棋方、易位权和仅在确有合法吃过路兵时的 en-passant 格；半回合钟和回合数不参与图去重；
- 完整六字段 FEN 与规范图身份同时保存。前者服务五十回合规则、对局重放和未来残局分析，后者服务转置合并，二者不能互相替代；
- `Position` 与合法 `MoveEdge` 表达可多父的全局事实。课程中的顺序、comment、NAG、来源和局部注释放在 occurrence/课程语境层，不写回全局边；
- `Source → SourceVersion → SourceFile` 区分逻辑来源、不可变版本和文件；`SourceSpan` 用带判别字段的页码/bbox/视频毫秒范围定位证据；
- 删除优先使用显式归档和引用保护。正式记录使用 UTC 时间、UUID 与乐观版本字段，破坏性历史审计仍在后续单元扩展。

异步 SQLAlchemy 的 MySQL 方言固定为 `mysql+asyncmy`，当前依赖版本为 0.2.11；SQLite 是现阶段自动验收数据库，真实 MySQL 兼容门禁按计划在 Stage 3D 引入。同步 PyMySQL 不能传给 AsyncEngine。

## 契约链路

Pydantic Schema 通过 Sanic Extensions 形成 OpenAPI。`scripts/contracts.py` 从真实 `/docs/openapi.json` 导出确定性文件，再由 `openapi-typescript` 生成前端类型。前端不得另写一份相同 DTO；`make check-contracts` 会比较重新生成结果并在漂移时失败。

## 运行时数据

默认 SQLite URL 指向 `data/database/chess-workbench.db`。目录由数据库适配层按需创建，clean checkout 不依赖被忽略的数据文件。测试注入临时 SQLite URL，避免污染个人数据。

## SQL 任务与本地引擎

ADR 0009 冻结 Stage 6A–6D：`jobs` 是带租约、心跳、重试、取消和幂等键的正式队列；
`invalidation_events` 是持久 outbox，WebSocket 断开后 HTTP polling 仍能取得同一事实。
Stockfish 子进程按操作创建并在所有退出路径清理，Threads/Hash/MultiPV/耗时受配置上限
约束。分析缓存包含完整六字段 FEN、引擎名称/版本和全部相关参数。Syzygy 能覆盖局面时
优先返回精确 WDL/DTZ，否则显式回退 Stockfish。Exercise 接线仍属于 Stage 5 后的 6E。

## 双模课程

ADR 0005 与 ADR 0007 定义了两种课程模式。`mode` 表达内容的组织与所有权，而不是底层是否
允许分支：

- **`traditional`**：按来源组织（一本书/视频系列/PGN → 章节）。默认界面沿作者主线线性
  阅读，但一个 MoveSequence 可以保留作者原有的有序变例树。用于整本棋书、中局专题、
  残局手册与 PGN 来源。
- **`opening_explorer`**：按问题和决策点组织（开局主题 → 变例分支），聚合用户显式发布的
  多来源观点。KnowledgeNote 通过 `source_note_id` 引用 traditional 模块中的原始内容。

两种模式共用 Position/MoveEdge 全局图和 occurrence 语境层。每个 occurrence 始终最多只有
一个父节点；两条路径转置到同一局面时只复用 Position/MoveEdge，不能合并 occurrence。
AI、PGN 和手动来源默认进入 traditional；进入 opening_explorer 必须经过显式发布。

## 章节内容块

ADR 0006 定义了章节内容的 Block 序列格式：

```
Block = SectionHeader | NarrativeParagraph | MoveSequence | KnowledgeNote
```

- `SectionHeader`：小节标题（纯文本）
- `NarrativeParagraph`：不属于任何特定局面的 Markdown 叙事段落
- `MoveSequence`：有根、有序的来源着法树；第一个子节点是主线，其余是作者变例，中心棋盘
  随当前路径同步更新
- `KnowledgeNote`：对当前局面的评注，可引用 `SourceSpan`

棋盘图不单独存储——OCR 提取着法和 FEN 后丢弃，交互界面用可交互棋盘替代。AI 从棋书中提取一章时直接产出这个 Block 序列，经用户审核后写入数据库。

Stage 3 先把每个 PGN game 的 Module occurrence 树视为一个隐式 MoveSequence；Stage 4
编辑器开始前再用 migration 确定性回填显式 Block，不为 PGN 导入提前引入两套结构。

## PGN 来源与语义边界

ADR 0007–0008 冻结 Stage 3 的 PGN 契约：

- 一份原始 PGN bytes 对应一个可复用的 Source/Version/File 资产；一次逻辑导入另有不可变
  receipt。相同内容与目标自动重放，不能重复创建用户课程内容；
- 一份文档解析全部 game，一次新导入默认创建一个 traditional Course，每局创建一个有序的
  顶层 Module 和一个根 occurrence；主线与全部 RAV 保留为来源有序树；
- round-trip 比较语义而非原始排版，必须覆盖全部 game、headers、起始完整 FEN、结果、
  分支顺序、root/starting/普通 comment 和全部 NAG；
- 导入先完成有界解析和文件 CAS，再在一个 SQL 事务内处理幂等、Source、Course、Module、
  occurrence、annotation 与 receipt，失败时不得留下部分业务行；
- 导出范围必须明确为一个 Module、该 Module 内一条 root-to-leaf 路径，或一个 import receipt
  的全部 game。遍历 occurrence 路径，不遍历无界的全局 Position 图。

## 尚未作出的决定

正式 MySQL 发布拓扑与 Stage 8 AI provider 审核协议仍未冻结。它们会在进入相应阶段前
单独写 ADR，避免提前固化未经真实夹具验证的设计。
