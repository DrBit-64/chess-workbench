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

后台任务、Stockfish、OCR、AI 和 WebSocket 会在对应阶段进入系统，但不会改变以下边界：

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

## 双模课程

ADR 0005 引入了两种课程模式：

- **`traditional`**：按来源组织（一本书/视频系列 → 章节），Occurrence 构成线性链。用于整本棋书、中局专题、残局手册。
- **`opening_explorer`**：按问题和决策点组织（开局主题 → 变例分支），Occurrence 构成图，支持转置合并和多分支。KnowledgeNote 通过 `source_note_id` 引用 traditional 模块中的原始内容。

两种模式共用同一套表结构，通过 `Course.mode` 区分。AI 导入和手动导入默认进入 traditional 模式；用户选择章节发布到 opening_explorer。

## 章节内容块

ADR 0006 定义了章节内容的 Block 序列格式：

```
Block = SectionHeader | NarrativeParagraph | MoveSequence | KnowledgeNote
```

- `SectionHeader`：小节标题（纯文本）
- `NarrativeParagraph`：不属于任何特定局面的 Markdown 叙事段落
- `MoveSequence`：一连串着法，内部展开为 `CourseOccurrence` 链，中心棋盘随走子同步更新
- `KnowledgeNote`：对当前局面的评注，可引用 `SourceSpan`

棋盘图不单独存储——OCR 提取着法和 FEN 后丢弃，交互界面用可交互棋盘替代。AI 从棋书中提取一章时直接产出这个 Block 序列，经用户审核后写入数据库。

## 尚未作出的决定

PGN 导入如何把任意层 variation 映射为 occurrence、超出乐观锁字段的版本审计、后台任务租约与重试，以及正式 MySQL 发布拓扑仍未冻结。它们会在进入相应阶段前单独写 ADR，避免提前固化未经真实夹具验证的设计。
