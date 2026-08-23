# ChessWorkbench 开发计划与自动化验收矩阵

> 基于 `docs/chess-workbench-project-description.md`。计划把原文档的大阶段拆成能够独立交付、独立回退、尽量由机器验收的纵向切片。

## 1. 对项目的理解

ChessWorkbench 的核心不是棋谱播放器，而是一个个人国际象棋知识系统。它要把棋书、视频、PGN 和个人实战统一到“局面—着法—来源—解释—个人选择—练习记录”这条学习闭环中。

开发中必须持续守住六条边界：

1. `Source`、`Knowledge`、`Repertoire`、`Exercise` 分层，来源观点不能在导入时相互覆盖；
2. 内部事实模型是可合并转置的局面图，PGN 只是导入导出格式；
3. SQL 后端是正式数据权威，前端棋规库只做即时交互；
4. 个人首选、人工可接受集合、引擎阈值和残局 WDL/DTZ 是不同答案策略；
5. AI 只生成候选，必须经过 Schema、棋规、局面一致性和人工审核；
6. 先完成单用户本地闭环，再引入部署、重计算和协作复杂度。

产品里程碑分成三个层次：

- **编辑器 MVP**：能够可靠建立、引用、导入和导出局面知识；
- **开局库训练 MVP**：能够把个人选择转成练习，并用 FSRS 推动下一次复习；
- **实战学习闭环 MVP**：能够从 Lichess 实战识别偏离与客观错误，再生成练习并观察复发趋势。

## 2. 每个阶段共同的完成定义

除非阶段另有说明，每一步只有同时满足以下条件才算完成：

- 行为有测试，而不只是文件或接口存在；
- 当前阶段唯一验收入口（Stage 1 为 `make acceptance`，后续为 `make acceptance-stage-N`）在 clean checkout 退出码为 0；
- API Schema 变化已重新生成 OpenAPI 和 TypeScript 类型，漂移检查通过；
- 数据模型变化能从空库迁移，并有升级测试；涉及破坏性变化时还要有迁移夹具；
- 测试不访问真实 AI、Lichess 或不稳定公网；外部服务使用固定 fixture/fake；
- 关键失败路径有断言，包括非法输入、事务回滚、重复请求和依赖不可用；
- 新架构决定写 ADR；用户文档中的命令被 CI 实际执行；
- 不用人工阅读代码来证明正确性。人工验收只保留视觉舒适度、文案和产品取舍。

初始质量门槛：

- ESLint `--max-warnings=0`，Ruff lint/format 零错误；
- TypeScript strict 与 Python mypy 零错误；
- 前后端行覆盖率不低于 80%，分支覆盖率不低于 75%；
- position key、棋步合法性、PGN round-trip、答案策略、任务状态机等关键规则分支覆盖率不低于 90%；
- 单元和集成测试不重试；Playwright 最多重试一次并保存 trace；
- 所有随机/性质测试固定并打印 seed，失败时保留最小反例。

---

## Stage 1：可复现工程底座与最小纵向切片

状态：**已完成（2026-08-05）**

### 目标

建立后续所有功能共用的工程、契约和质量基础，并用真实的“Vite 开发代理 → Sanic → SQLite”HTTP 链路证明前后端服务已经接通；React 应用本身由 Vitest 和生产构建验收，真正浏览器 E2E 从 Stage 4 引入。

### 交付物

- pnpm workspace、uv 项目、Node 22/Python 3.13 版本约束和锁文件；
- React 18、Vite 7、Router 7、SWR、Ant Design 6、Tailwind 4 应用壳；
- Sanic 应用工厂、Pydantic 配置、SQLAlchemy 异步 SQLite 连接；
- `/api/health` 实际执行 `SELECT 1`，数据库不可用时返回 503；
- Sanic OpenAPI → `openapi-typescript` → 前端类型的单向生成链；
- Ruff、mypy、pytest、ESLint、tsc、Vitest、覆盖率和生产构建；
- `make bootstrap`、`make verify`、`make smoke`，以及聚合验收入口 `make acceptance`；
- GitHub Actions、`.env.example`、README、架构概览和 ADR 机制；
- Alembic 基础配置，但暂不创建业务表。

### 自动验收标准

1. `make bootstrap` 在 clean checkout 使用 uv `--locked` 与 pnpm `--frozen-lockfile` 成功，不依赖 `data/` 中的本地文件；
2. `make acceptance` 从锁文件安装依赖后，一次运行完格式、lint、类型、测试、行/分支覆盖率、契约漂移、构建与双服务 smoke 并退出 0；
3. 后端测试断言健康接口 200 响应、固定 JSON Schema、SQLite 文件按需创建及真实查询；
4. 故障测试让数据库 ping 失败，断言接口返回 503 且不泄漏内部异常；
5. 前端测试覆盖 SWR 的 loading、success、error 三种状态；
6. OpenAPI 连续生成两次字节一致，生成 TypeScript 被 `tsc` 编译；
7. `make smoke` 用 HTTP 客户端自动拉起两端，分别直连 API 和经过 Vite proxy 请求 `/api/health`，校验响应后自动清理进程；它不冒充浏览器 E2E；
8. GitHub Actions 调用同一个 `make acceptance`，安装使用 frozen lock；
9. 没有 OpenAI key、Stockfish、MySQL 或公网时，全部基础测试仍可运行。

### 不进入本阶段

Position 等业务表、首个 migration、棋盘组件、Docker、Stockfish、任务队列和 AI SDK。它们没有被脚手架“假实现”。

---

## Stage 2：棋规内核、局面身份与最小领域模型

状态：**整改后已验收（2026-08-09）**。2A–2D 的领域、HTTP、双模课程与来源笔记约束均已
实现；SQLite 累积门禁与固定 MySQL 8.4 镜像上的真实迁移/业务夹具通过。原始审计反例与整改
记录保留在 `docs/agent/stage-2-3-audit.md` 和 `docs/agent/HANDOFF.md`。

### 目标

先解决数据系统最难逆转的语义：什么算同一局面、图如何表达转置、课程语境如何引用全局图，再建立第一批表和 API。

### 交付物

- ADR：`position_key` 的规范化规则；明确半回合钟、回合数、易位权和 en-passant 的处理；
- ADR：SQLAlchemy 异步 MySQL URL 使用 `mysql+asyncmy`，锁定 `asyncmy 0.2.11`；`aiomysql` 仅作为出现已验证兼容性问题时的候选，不得把同步 PyMySQL 塞给 AsyncEngine；
- 区分用于图去重的规范局面身份和完整对局状态，避免破坏五十回合规则/DTZ；
- `Position`、`MoveEdge`、`Source`、`SourceSpan`、`Course`（含 `mode` 字段）、`CourseModule`、`KnowledgeNote`（含 `source_note_id` 字段）；
- 课程/来源 occurrence 或等价的上下文关联，避免把某本书的 comment/NAG 污染为全局边属性；
- ADR 0005：双模课程（traditional vs opening_explorer）；
- Alembic 首个 migration、Pydantic Schema、CRUD API、OpenAPI 类型；
- 后端以 `python-chess` 验证 FEN 和每个持久化棋步；
- 明确外键、唯一约束、删除/归档规则和时间字段的 UTC 语义。

### 自动验收标准

1. 空目录中执行 `alembic upgrade head` 成功，`alembic check` 无漂移；
2. 固定向量覆盖普通着、王车易位、吃过路兵、升变、将军/被将、非法 FEN 和非法棋步；
3. 两条不同着序到达同一规范局面时数据库只有一个 `Position`，但导航路径仍各自保留；
4. 仅半回合/回合计数不同的 FEN 按 ADR 得到预期的 graph key，同时完整状态未丢失；
5. en-passant 可捕获与不可捕获、易位权变化都有回归向量；
6. 并发插入同一 position key 由唯一约束安全收敛，不产生重复行；
7. API 绕过前端提交非法着时返回确定的 422 错误，事务不留下任何 Position/MoveEdge；
8. Course A 与 Course B 对同一边保存不同注释/NAG 后互不污染；
9. SQLite 集成测试全绿；2A 用 ADR 和 SQLAlchemy 配置测试锁定异步 MySQL 驱动选择，真实 MySQL 双库门禁到 3D 引入；
10. 属性测试从随机合法局面走一步，验证保存的目标 FEN 与 `python-chess` 权威结果一致。

### 主要风险控制

- 局面图允许多父，所有“返回父节点”API 都必须带当前路径语境；
- 图遍历默认防环、限制深度和节点数；
- `SourceSpan` 必须有稳定主键，因为 KnowledgeNote 会引用它。

### 分层自动验收入口

Stage 2 的单元门禁按依赖关系累积，不能用文档中的“已实现”描述替代命令结果：

1. `make acceptance-stage-2a`：运行全后端静态检查，以及局面身份、FEN/棋步固定向量、性质测试和数据库 URL 配置测试；关键身份模块覆盖率门槛为 90%，并检查 ADR 0002/0003/0005 存在；
2. `make acceptance-stage-2b`：先验收 2A，再运行模型、仓储、唯一约束与并发收敛测试；从临时空 SQLite 数据库执行 `upgrade head → alembic check → downgrade base`，关键仓储模块覆盖率门槛为 90%；
3. `make acceptance-stage-2c`：先验收 2B，再运行课程/来源/语境 Schema 和 CRUD API 测试，包括确定的 422 错误码、事务回滚及跨课程隔离；关键 Schema 模块覆盖率门槛为 90%，并检查 ADR 0004 存在；
4. `make acceptance-stage-2d`：先验收 2C，再运行 `Course.mode` 与 `KnowledgeNote.source_note_id` 的 migration、Schema、模型约束与 API 测试；关键内容模块覆盖率门槛为 90%，并检查 ADR 0005 存在；
5. `make acceptance-stage-2`：先验收 2D，再执行全仓 `verify` 与双服务 `smoke`，因此还覆盖全局覆盖率、OpenAPI/TypeScript 生成物漂移、前端类型/测试/生产构建和真实代理链路。

前三个单元只需要 Python 工具链；最终聚合验收因为包含契约和前端检查，需要 Node.js 22 与 pnpm 10.14.0。若 pnpm 命令缺失但 Corepack 可用，Make 会自动使用 `corepack pnpm`。CI 的稳定入口 `make acceptance` 随当前已交付阶段推进，现累计到 Stage 4。

---

## Stage 3：PGN 语义 round-trip 与课程后端

### 独立整改后的状态（2026-08-09）

原审计反例已全部转换为自动测试并修复。`make acceptance-stage-3` 在 SQLite、固定镜像
MySQL、运行时契约、前端构建和双路 smoke 上累计退出 0；历史反例保留在
`docs/agent/stage-2-3-audit.md`。

| 单元 | 现有测试情况 | 功能状态 |
|------|-------------|----------|
| 3A | 71 个解析测试，97.43% 聚焦覆盖 | 已验收 |
| 3B | 30 个导入/API 测试，96.68% 聚焦覆盖 | 已验收 |
| 3C | 12 个导出/比较测试，91.69% 聚焦覆盖 | 已验收 |
| 3D | MySQL 4/4 真实迁移与 PGN 业务链路 | 已验收 |
| 聚合 | 后端 225 passed，93.22% line / 76.36% branch | 已验收 |

### 已验收实现模块

| 模块 | 职责 |
|------|------|
| `logic/pgn.py` | 有资源上限的 PGN 文本 → `PgnGame`/`PgnNode` 不可变语义树 |
| `logic/pgn_import.py` | 原子、幂等的 PgnGame → Source/receipt/course/occurrence 图导入 |
| `logic/pgn_export.py` | Module、路径和 receipt 范围的完整语义 PGN 导出 |
| `logic/pgn_compare.py` | 覆盖 headers/result/FEN/变化顺序/comment/NAG 的结构化比较器 |
| `scripts/check_mysql.py` | 固定 MySQL 8.4 容器生命周期与失败传播 |
| `tests/test_mysql_compat.py` | 真实 Alembic 往返、CRUD、局面唯一性和 PGN 业务链路 |

### 目标交付物

- 按 ADR 0007 将一份 PGN 的全部 game 映射到一个 traditional Course 的有序 Module，保留
  mainline/RAV occurrence 树；traditional 表示按来源组织，不表示底层无分支；
- PGN 粘贴/文件导入 API（默认导入到 `mode="traditional"` 课程）；
- 主线、任意层分支、comment、NAG、headers、`SetUp/FEN` 和结果解析；
- 基于 occurrence 的导入结构，保留来源顺序和同一全局边的局部语义；
- 按 ADR 0008 建立原始 bytes 的 Source/Version/File CAS 资产、不可变 import receipt、
  transport-independent 幂等键与同内容 Source 复用；
- 提供 Module 完整树、Module 内 root-to-leaf 路径和 receipt 多局下载三种明确导出范围；
- 课程、模块、注释和手工来源的完整后端用例（支持两种 mode）；
- 固定 5 MiB、1,000 game、50,000 move occurrence、RAV nesting 128 和 15 秒/512 MiB 资源
  边界；合法 5,000-ply 主线不得依赖 Python 递归；
- MySQL 兼容测试入口：CI 使用 service container，本地验收脚本可启动一次性测试实例。

ADR 0007–0008 是 Stage 3 实现的规范来源。若实现与旧代码或旧测试冲突，以 ADR 为准并修改
误导性测试；不得为了保留现有接口而静默降低语义范围。

### 自动验收标准

1. 至少 12 份修正后的黄金夹具覆盖多 game、主线、嵌套分支、Unicode 注释、多个 NAG、
   root/starting/普通 comment、完整起始 FEN、升变、转置、自定义 header 和不完整结果；
2. `parse all → import → export → parse all` 后，用结构化比较器断言全部 game、headers、
   result、变化拓扑与顺序、SAN/UCI、comment/NAG 和起始完整 FEN 语义等价；每个字段的单点
   mutation 都必须令比较失败；
3. 相同逻辑输入跨 JSON/raw/multipart 重放时返回同一 receipt，Course/Module/Occurrence/
   Position/Source 计数和 Course version 均不增加；同一 key 的不同请求返回 409 且零写入；
4. 两份 PGN 到达同一局面会共享 Position，但各自注释和分支顺序独立；
5. 任一非法棋步导致整个导入事务回滚，并返回带 ply/path 的可定位错误；
6. 导出按 occurrence scope 处理转置；Module、路径和多 game 下载均有结构断言，损坏环与
   跨模块 leaf 返回稳定错误且不无限递归；
7. 边界值通过，越界输入返回 413/422；合法 5,000-ply 主线不出现 RecursionError，2-core CI
   中不超过 15 秒且峰值 RSS 低于 512 MiB；
8. Runtime OpenAPI 与生成 TS 类型覆盖 JSON/raw/multipart、receipt、Module/path 导出、
   multi-game 下载、错误响应及安全下载 headers；
9. 从本阶段起 SQLite 与 MySQL 都作为 PR 阻塞集成环境，使用真实 Alembic migration 和共享
   API/domain fixture 验证 JSON、布尔、排序、时间和唯一约束行为一致。

---

## Stage 4：三栏课程编辑器（编辑器 MVP）

状态：**已实现并通过自动验收；两轮交互反馈已修正，等待继续产品验收（2026-08-10）**。

`make acceptance-stage-4` 累计退出 0：后端 247 passed / 4 个仅在普通 SQLite 测试中条件
跳过的 MySQL 用例，行覆盖率 92.47%、分支覆盖率 75.06%；固定 MySQL 8.4 门禁 4/4，前端
26/26，生产构建、契约、迁移往返、direct/proxy smoke 以及全新临时数据库 Chromium 编辑器
流程全部通过。Stage 4A–4D 必需项为 0 个剩余项；4E 仍按原决定留在非阻塞 backlog。

### 目标

交付原项目说明 §16 的 15 条 MVP：用户可从起始局面/FEN 建课程（支持 traditional 和 opening_explorer 两种模式）、走合法棋、创建和导航分支、写说明、关联来源并导入导出 PGN。

### 交付物

- Dashboard 基础卡片、后台状态占位与快速入口；课程数据出现后展示真实统计，不用硬编码假数据；
- Learn 课程列表、搜索和基础筛选；
- 独立 Sources 一级页与网页笔记/手工来源入口；
- 课程页：traditional 左侧展示章节，opening_explorer 左侧只展示合并后的入口局面；中间
  `react-chessboard`，右侧展示当前节点直接候选着；
- 发布到 opening_explorer 时按根 Position 和“父 occurrence + MoveEdge”合并共同前缀，
  不把来源章节标题复制成探索器目录；
- 棋盘选中/拖动棋子时显示合法空格圆点和吃子圆环，并使用 100 ms 快速移动动画；
- 当前导航路径而非“唯一父节点”；
- `chess.js` 前端预检 + 后端 `python-chess` 权威校验；
- Markdown 编辑与经过白名单清理的预览；
- 编辑会话使用 `useReducer` 实现 undo/redo；
- 来源关联、保存/重载、错误恢复；
- 注释和课程结构的历史版本入口；
- PGN/FEN 导入和当前线导出；
- Playwright 关键路径与可访问性扫描。

### 自动验收标准

Playwright 在全新临时数据库中自动完成：

1. 新建课程和嵌套模块；
2. 分别从初始局面和自定义 FEN 开始；
3. 在棋盘走合法棋并添加两个分支；
4. 沿当前路径后退、切换分支，再命中一个转置局面；
5. 给局面和着法写 Markdown，关联手工来源；
6. 刷新浏览器，断言棋盘、路径、分支、说明和来源全部保持；
7. 导出 PGN，再用 Stage 3 的语义比较器验证；
8. 通过原始 HTTP 绕过 UI 提交非法着，断言后端拒绝且 UI 重新取数后无幽灵节点；
9. 模拟保存 500/断网，断言未保存状态明确、重试不重复写入；
10. axe 扫描无 serious/critical 可访问性问题，核心操作可以键盘完成；
11. 视口矩阵覆盖常见桌面宽度，关键控件没有遮挡；截图仅用于回归提示，不代替行为断言。
12. 发布两个共享起点/前缀的 traditional 章节后，Explorer 只有合并后的候选路径且不显示
    来源章节名；真实棋盘点击棋子后可见合法落点标记。

完成后，将项目说明中的“第一版 MVP”称为**编辑器 MVP**，避免与真正训练闭环混淆。

全局图视图作为 **Stage 4E 非 MVP backlog**：编辑器 MVP 稳定后再加入转置、孤立节点、深度/来源/错误筛选，不阻塞 Stage 5。

第二轮产品验收把内容呈现收口为同一套 ADR 0006 block：传统课程默认在宽正文栏按顺序
阅读 Narrative/MoveSequence/KnowledgeNote，narrative 可引用 SourceSpan，新局面说明与其
block 原子创建；Explorer 的来源观点可打开原章节相邻正文。完成这些后 Stage 4A–4D 的
**必需剩余项仍为 0**，只有可选的 Stage 4E 全局图一个执行单元。

---

## Stage 5：个人开局库、非引擎答案策略与开局库训练 MVP

执行顺序：**因当前产品优先级后置**。其 Source/Knowledge/Repertoire/Exercise 分层契约
不变；后置不会要求 Stage 4 或 Stage 8 改表重做。

### 目标

把知识编辑器变成可持续使用的训练工具，实现个人选择、四类无需外部二进制的判题、独立复习卡和今日复习。真正的“实战错误 → 新练习”闭环到 Stage 7 才完成。

### 交付物

- `Repertoire`、`RepertoireChoice`：preferred/accepted/inactive/avoid/unreviewed；
- 独立 Repertoire 与 Practice 一级页面；
- `Exercise`、`ReviewCard`，同一局面可有多个独立卡；
- 六类策略的统一协议，并完整实现 `exact`、`repertoire`、`accepted-set`、`play-out`；这里的 `play-out` 严格指人工编排的有限应答图：对手着法来自作者配置，到达目标节点或 `max_plies` 即终止，只按编排边判定学习者着法，不计算最佳应手或胜和负；`engine-threshold` 与 `tablebase` 在本阶段只注册能力需求，Stage 6 才实现；
- FSRS 服务、今日队列、复习统计、提示与来源解释；
- 开局回忆、残局定式、从局面继续下的基础体验；
- 自定义练习集，以及“新导入资料的待掌握局面”队列接口；
- 课程版本、个人库版本、答案策略版本写入每次作答记录；
- 用户时区与“今天”的明确规则。
- SQLite 数据与来源文件清单的备份/恢复命令，为本阶段的恢复验收提供真实工具。

### 自动验收标准

1. 表驱动测试覆盖所有答案分类及边界：首选、可接受、合理但偏库、不推荐、客观错误、未知；
2. 冻结时钟验证 FSRS 首次学习、Again/Hard/Good/Easy、逾期和跨时区边界；
3. 同一局面的两张卡作答后，稳定度/难度/下次日期互不影响；
4. 修改个人开局选择不会篡改历史答案，旧记录可按版本重放解释；
5. `engine-threshold`/`tablebase` 在能力未安装时返回带机器错误码的“暂不可判定”；本项只验收协议和安全降级，不宣称策略已经完成；
6. Playwright 自动完成“课程选入个人库 → 生成练习 → 今日复习 → 作答 → 查看解释 → 下一复习时间更新”；
7. 并发重复提交同一次答题由 idempotency key 收敛为一条记录；
8. 备份临时 SQLite、删除原库再恢复，核心课程/个人库/卡片/复习状态行数和内容哈希一致。
9. `play-out` 表驱动测试覆盖目标节点、对手应答缺失、学习者走出编排、环和 `max_plies`；需要生成对手着法或判断最终胜和负的体验明确返回能力未安装，直到 Stage 6 实现。

---

## Stage 6：Stockfish、Syzygy 与可靠后台任务

实现状态（2026-08-10）：6A–6D 代码与验收脚本已落地；真实 Stockfish、完整异步 SQL 与
Chromium 累计门禁仍需在允许网络和工作线程的正常主机环境执行后，才能标记为最终验收通过。
6E 继续等待 Stage 5。

执行顺序：**核心基础提前到 Stage 8 之前**。先交付不依赖个人库的 6A SQL job 基础，
再按需要交付 6B 引擎分析和 Syzygy/对弈核心。`engine-threshold`、`tablebase` 判题以及
“保存为 Exercise”属于 Stage 5 的集成尾项，在 Stage 5 模型存在后启用；提前阶段不得
用占位表或跨层字段伪造这些依赖。

### 目标

提供实时浅分析、后台深分析、缓存和指定局面对弈，同时建立可复用的 SQL worker 可靠性模型。

### 交付物

- UCI adapter 与进程生命周期管理；
- 默认实时参数 Threads=1、Hash=128MB、MultiPV=4、movetime=800ms、Ponder=false；设置界面
  参照 Lichess 的搜索时间、线路数（1–5）、线程和 Hash 层级；
- MultiPV、score、WDL、引擎版本和完整参数持久化；
- `ImportJob`/通用 job 表、worker、租约、心跳、重试、取消和幂等键；
- 实时浅分析与后台深分析；
- 缓存 key 包含规范局面、完整相关状态、引擎版本和全部参数；
- Syzygy 查询和残局优先路由；
- 提供 `engine-threshold` 与 `tablebase` 的纯分析结果；与 Stage 5 答案分类协议的接线
  作为后置集成尾项；
- WebSocket 只发资源失效通知，SWR 随后重新拉正式数据；
- 从任意局面与引擎继续下；
- 指定局面对弈支持选颜色、强度/资源限制、赛后错误回顾，并把新发现保存为课程草稿；
  Exercise 草稿目标在 Stage 5 存在后接入。

### 自动验收标准

1. fake UCI 覆盖握手、option、超时、非法输出、进程崩溃、取消和清理；
2. 小型真实 Stockfish 集成 job 验证合法 PV、MultiPV 数量和版本记录；
3. 完全相同请求命中缓存，任一关键参数或引擎版本变化都会 miss；
4. 两个 worker 并发 claim 同一任务时只执行一次；
5. worker 在 claim 后崩溃，租约过期可恢复；超过重试上限进入终态并保留最后错误；
6. 取消在排队、运行中和完成后都有确定且幂等的状态转换；
7. WebSocket 断开不影响任务完成和 SQL 数据，重连/普通轮询能取得相同结果；
8. 使用小型 Syzygy fixture 验证 WDL/DTZ 路由；缺表时优雅回退；
9. `engine-threshold` 与 `tablebase` 的纯分析边界有表驱动测试；完整 UI 作答流在 Stage 5
   集成尾项验收；
10. 进程、线程、Hash 和耗时均受配置上限约束，测试后无孤儿 Stockfish 进程；
11. 状态机使用性质测试验证不存在非法跃迁。

---

## Stage 7：Lichess 对局、偏离与错误训练闭环

执行顺序：**整体后置**。7A 本身仍只依赖 4D，但当前不抢占 PDF/OCR/AI 主路径；7B–7D
继续严格等待 Stage 5 训练流和 Stage 6 引擎分析。

### 目标

把个人实战接入已有知识和练习系统，明确区分“偏离个人主线”和“客观错误”。

执行边界：

- **Stage 7A（可与 Stage 6 并行）**：Lichess adapter、筛选同步、幂等存储、Games 列表和原始棋局浏览，不计算客观损失；
- **Stage 7B（必须依赖 Stage 6）**：引擎损失、客观错误、聚类、训练价值排序、趋势和从错误生成练习。

### 交付物

- Lichess API adapter、游标/日期同步、限流与退避；
- 按日期、时间控制、颜色和开局筛选同步与浏览；
- `Game`、`GamePosition`、`GameError`；
- 以 Lichess game ID 幂等导入 PGN、时钟、颜色、结果和 ECO；
- 个人库首次偏离、引擎损失、时间管理等独立信号；
- position key → 最近课程节点 → ECO/前缀 → 兵型/材料的分层匹配；
- 重复错误聚类、课程关联、趋势统计和一键生成练习；
- 完整错误枚举、残局材料/定式匹配，以及“重复程度 × 课程匹配 × 客观损失 × 可解释性 × 可复现性”的训练价值排序；
- Games 列表与单盘复盘页。

### 自动验收标准

1. 全部 PR 测试使用录制后脱敏的 Lichess fixture，断网可运行；
2. 同一 game ID 导入 N 次仍只有一盘，更新策略有明确测试；
3. 分页、429、5xx、中断恢复和过期 cursor 都有 adapter 测试；
4. 预置棋局在指定 ply 得到确定的首次个人库偏离；客观可行的偏离不被标成 blunder；
5. 预置 blunder 即使仍在个人库中，也单独标出客观错误；
6. 同一错误模式跨多盘聚为一类，不相关局面不误聚；
7. 从 GameError 生成练习后能走完 Stage 5 的完整作答流，并保留原对局引用；
8. 重跑分析不重复创建错误/练习，参数版本变化产生可审计的新分析版本；
9. Playwright 完成“同步 fixture 用户 → 打开单盘 → 定位错误 → 查看课程 → 生成并完成练习”。

---

## Stage 8：PDF/OCR/AI 候选导入与人工审核

执行顺序：**Stage 6A 之后优先实施**。Stage 4 的有序正文、局面说明和 SourceSpan 已经
是正式发布目标，因此 8A–8D 不依赖个人开局库；AI 先产出 Course/Knowledge 候选，
Repertoire/Exercise 发布 adapter 等 Stage 5 模型存在后再接入。

在 8A 之前先完成 **8P 可移植识别协议**。ADR 0010 的 CCEF v1 是供应商无关、消费者无关
的交换边界：识别核心输出版本化 JSON，ChessWorkbench 通过独立 ConsumerAdapter 映射为
内部候选。它不是新的微服务，也不改变 Source → Knowledge 的人工审核边界。

### 目标

把 PDF 资料安全、幂等地转成可审核候选（默认进入 `mode="traditional"` 课程）；任何 AI 或 OCR 结果都不能绕过正式发布边界。

### 交付物

- `chess-content-extraction/1.0` 基础 Pydantic 契约，以及在不改变 1.0 工件的前提下增加的
  `chess-content-extraction/1.1` 原子棋谱注释/独立阅读流契约、固定 JSON Schema 和兼容性夹具；
- provider 接收调用者给定的 JSON Schema，默认 DeepSeek V4 Flash，并允许后续增加千问、
  OpenAI 或本地实现；provider 不导入消费者领域模型；
- ChessWorkbench ConsumerAdapter 单向映射 CCEF heading/prose/move tree/figure/unresolved，
  识别核心不反向依赖 Course、KnowledgeNote、SQL 或 Sanic；
- 内容哈希存储、MIME/大小/路径验证、原始与衍生文件分离；
- Sources 一级页中的 PDF 上传、页码范围选择、任务状态和冲突筛选；
- PyMuPDF 页面渲染、OCRmyPDF/PaddleOCR adapter；
- `AI_PROVIDER=mock|deepseek|dashscope|openai|local` adapter；测试只使用 mock transport，
  默认生产配置为 DeepSeek V4 Flash 非思考模式；
- 章节、正文、棋谱、棋盘图、说明和 SourceSpan 候选；连续主谱、局部分支和原子说明分别
  保留棋局拓扑、来源阅读顺序与语义锚点，分支不复制公共前缀；
- 同一 PDF 的长章节可以按连续语义页段顺序追加：每段 run 与模型工件保持不可变，显式
  hash-bound 续接锚点连接跨段棋谱，确定性聚合修订作为 Sources/审核/发布的单一候选身份；
- JSON Schema、python-chess、前后局面和置信度验证；
- 三栏审核页：原文/页图、棋盘、候选变化/警告；
- 批准、修改、拒绝、多来源合并和审计记录；
- 批准时可以产出 Course 与 KnowledgeNote 草稿；AI 合并历史可按版本查看；Exercise
  草稿 adapter 在 Stage 5 完成后追加；
- 未配置 API key 时核心应用完整可用。

### 自动验收标准

1. CCEF JSON Schema 与 Pydantic 生成结果确定性一致；同一 package 可由不含任何
   ChessWorkbench 依赖的消费者解析，未知字段、悬空引用、非拓扑棋步树、重复 sibling
   order 和不支持的 major 被拒绝；
2. provider contract 使用相同输入和 Schema 时，mock/DeepSeek recorded fixture 产生同一
   CCEF 语义；真实外部 API 不进入 PR 测试；
3. 小型合成 PDF fixture 覆盖文本页、扫描页、棋谱、页码和 bbox；
4. 相同字节重复上传复用 Source/file hash，不重复存储；扩展名伪装、超限和路径穿越被拒绝；
5. mock OCR/AI 输出完全确定，契约不允许额外字段和错误类型；
6. 非法 SAN、断裂变化、棋盘方向不确定和低置信度内容只能进入 warning/review，不能发布；
7. 拒绝、修改、批准各自产生不可变审计记录，并能追溯 SourceSpan；
8. 两个来源对同一局面的冲突推荐作为 Knowledge 并存且不覆盖；个人路线选择在 Stage 5
   的 Repertoire 层完成；
9. 任务重试和重复批准保持幂等；发布事务失败时正式知识零部分写入；
10. 在无任意云模型 key、无 OCR 二进制的精简 CI job 中，除相应可选集成外所有测试仍绿；
11. 云模型 adapter 只做 Schema 合约测试和显式手动/定时集成，不在 PR 中花费真实额度。
12. 合成棋书片段能表达“主线走到某步 → 插入原子说明与从更早局面分出的括号变化 → 原
    主线继续”；过滤阅读流必须完整覆盖棋步/注释一次，变化父节点必须指向真实分叉局面。
13. 两个连续合成页段可以顺序追加为一个提取文档；第二段只能绑定前一聚合 hash 中列出的
    合法棋谱锚点，合并后没有重复公共前缀且所有分段证据仍可定位。失败、取消、重放和并发
    追加不得覆盖旧工件或错误推进文档 head。

---

## Stage 9：视频转录、棋盘变化与讲解对齐

### 目标

把视频变成带时间轴和局面引用的可审核知识候选，并复用 Stage 8 的审核/发布边界。

### 交付物

- FFmpeg 音频和关键帧 adapter；
- 带时间戳的转录 provider；
- 场景变化、棋盘区域/方向和局面候选；
- 通过合法着法约束连接连续局面；
- 转录片段与局面对齐；
- 时间轴审核、警告、修改和发布；
- 发布目标同时支持 Course/KnowledgeNote/Exercise 草稿，并保留视频时间引用；
- 衍生文件生命周期与空间配额。

### 自动验收标准

1. 数秒钟固定视频 fixture 可在 CI 重复得到相同时间戳范围和关键帧集合；
2. mock 转录与预期局面对齐在容差窗口内；
3. 连续局面能唯一由合法棋步连接时自动建议该步；多解/无解时必须进入审核警告；
4. 棋盘翻转、遮挡、切镜头和无棋盘片段有固定回归用例；
5. 发布后的 KnowledgeNote/Move occurrence 能反向定位视频时间段；
6. 相同视频重跑不重复正式知识，算法版本变化保留新的候选版本；
7. 取消/失败任务清理可再生临时文件，但不删除原始来源或已发布引用；
8. 超出时长、分辨率、文件大小或磁盘配额的输入在重计算前被拒绝。

---

## Stage 10：生产部署、数据可靠性与安全边界

### 目标

把已验证的本地应用变成可重复部署、可升级、可恢复的服务，而不是只“能构建镜像”。

### 交付物

- API/worker/frontend 镜像、Docker Compose、MySQL/MariaDB；
- Nginx `/`、`/api/`、`/ws/` 路由和上传限制；
- 数据库 migration 发布流程；
- SQLite 本地模式与 MySQL 部署模式的文档化边界；
- 数据库与来源文件的一致性备份、校验和恢复工具；
- 健康/就绪检查、结构化日志、资源上限和基础观测；
- 单用户认证/网络暴露策略；若进入多用户则补 ownership、授权和 secret 模型；
- Markdown 清理、CSRF/CORS、上传隔离、速率限制与依赖/镜像扫描。

### 自动验收标准

1. clean runner 一条 Compose 命令构建并启动全部必需服务；
2. smoke test 验证 Nginx 静态页、API、WebSocket upgrade 和未知路由行为；
3. MySQL 空库升级到 head，旧版本 fixture 升级后领域校验全部通过；
4. 滚动/重启 worker 不丢任务、不双执行；
5. 备份后销毁临时环境，再恢复到新环境；核心表、来源文件清单和内容哈希一致；
6. 恢复演练不依赖原容器可写层；缺失文件和孤儿引用会被一致性检查报告；
7. 非 root 容器、只读文件系统（必要卷除外）、secret 不入镜像/日志；
8. 上传炸弹、路径穿越、恶意 MIME、Markdown XSS、越权访问有自动安全回归；
9. 浏览器 E2E 在部署拓扑而非 dev server 上跑完编辑和训练关键路径；
10. 镜像与依赖扫描结果按严重度策略阻塞发布，波动性网络审计放定时流水线。

---

## Stage 11：实时协作草稿（明确后置）

### 目标

在核心个人闭环和部署稳定之后增加 Yjs/pycrdt/LMDB 协作草稿，不改变 SQL 正式数据权威。

### 交付物

- Yjs 文档、awareness、同步协议和 LMDB 持久化；
- 协作房间与权限；
- 离线编辑/重连的明确范围；
- 草稿校验、预览、冲突呈现和一次性发布到 SQL；
- 发布基线版本与审计记录。

### 自动验收标准

1. 两个浏览器上下文并发编辑后最终文档收敛；
2. 任一客户端断线编辑、重连后收敛且无重复操作；
3. 服务重启后 LMDB 草稿恢复；
4. 未发布草稿不会出现在正式课程、个人库或练习 API；
5. 发布时重新执行 Schema、棋规和基线版本校验；冲突时原子失败，不部分写 SQL；
6. 同一发布请求重复提交只生成一个正式版本；
7. 协作内容不能绕过 Source/Knowledge/Repertoire/Exercise 分层；
8. 故障注入覆盖消息乱序、重复、断连和发布进程崩溃。

---

## 3. 可独立交付的执行单元

一个 Stage 仍可能跨越多周，因此实际开发按下表的字母单元推进。每个单元应对应一个小 PR/变更集、一个唯一验收命令和一组固定夹具；前一个单元未绿，不开始依赖它的后一个单元。

| 单元 | 前置 | 可独立交付结果 | 固定夹具 | 唯一验收命令 |
|---|---|---|---|---|
| 1 | 无 | 工程底座、health、契约、测试、CI | 临时 SQLite、health 成功/失败响应 | `make acceptance` |
| 2A | 1 | position identity/异步 MySQL 驱动 ADR、纯函数与 FEN/棋步错误模型 | FEN/转置/易位/en-passant/升变及数据库 URL 向量 | `make acceptance-stage-2a` |
| 2B | 2A | Position/MoveEdge migration、约束与 repository | 空库、重复/并发插入、非法边夹具 | `make acceptance-stage-2b` |
| 2C | 2B | Position/MoveEdge HTTP 边界，以及 Course/Module/Source/Span/Note 与 occurrence CRUD API | 非法棋步零写入；两课程共享局面但注释不同的夹具 | `make acceptance-stage-2c` |
| 2D | 2C | Course.mode + KnowledgeNote.source_note_id migration、Schema 与 API；双模 CRUD 测试 | 两种 mode 创建/更新/枚举夹具；source_note_id 引用完整性夹具 | `make acceptance-stage-2d` |
| 3A | 2D | 不写库的 PGN parser 与语义树 | 主线、嵌套分支、NAG、Unicode、SetUp/FEN | `make acceptance-stage-3a` |
| 3B | 3A | 原子、幂等的 PGN → graph/course 导入 | 重复导入、非法 ply、转置、超限输入 | `make acceptance-stage-3b` |
| 3C | 3B | graph/course → PGN 导出与语义 round-trip | Stage 3A 黄金 PGN 全集 | `make acceptance-stage-3c` |
| 3D | 3C | 落实 2A 驱动决策，建立 SQLite/MySQL 双库约束测试和 PR 阻塞门禁 | 同一 migration/API fixture | `make acceptance-stage-3d` |
| **3** | **3D** | **Stage 3 聚合验收：contracts → full verify → smoke** | **全部 12 份黄金夹具、CI MySQL service** | **`make acceptance-stage-2`（累积至 2D）+ 3A/3B/3C/3D 全绿** |
| 4A | 3C | Dashboard 基础数据、课程列表、搜索/筛选和一级导航 | 课程/标签/统计 API fixture | `make acceptance-stage-4a` |
| 4B | 4A | 棋盘走子、当前路径、多分支与转置导航 | 两条路径命中同一 Position | `make acceptance-stage-4b` |
| 4C | 4B | Markdown、来源、undo/redo、保存冲突和历史入口 | XSS、断网、500、版本冲突 fixture | `make acceptance-stage-4c` |
| 4D | 4C | 编辑器 MVP 完整 Playwright 流 | 全新临时数据库 | `make acceptance-stage-4` |
| 4E | 4D，可后置 | 高级全局图，不阻塞训练 | 环、孤立点、多转置大图 | `make acceptance-stage-4e` |
| 5A | 4D | Repertoire/Choice 模型、API 和一级页 | 五种 choice 状态 | `make acceptance-stage-5a` |
| 5B | 5A | 六类策略协议与四类非引擎策略 | 答案分类表驱动向量 | `make acceptance-stage-5b` |
| 5C | 5B | FSRS、ReviewCard、今日队列和版本化作答 | 官方参考向量、冻结时钟/时区 | `make acceptance-stage-5c` |
| 5D | 5C | Practice UI、自定义集、备份/恢复与训练 MVP E2E | 临时完整个人库 | `make acceptance-stage-5` |
| 6A | 4D | SQL job 状态机、worker、租约/取消/重试 | 双 worker、崩溃、过期租约 | `make acceptance-stage-6a` |
| 6B | 6A | fake/真实 UCI、MultiPV、缓存和分析版本 | fake UCI transcript、固定局面 | `make acceptance-stage-6b` |
| 6C | 6B | Syzygy 与 engine-threshold/tablebase 纯分析 | 小型表库、阈值边界 | `make acceptance-stage-6c` |
| 6D | 6C | WS 失效通知、指定局面对弈、赛后回顾/课程草稿 | 断连、选色、强度与结束局面 | `make acceptance-stage-6` |
| 6E（后置集成） | 5B、6C | engine/tablebase 判题协议与 Exercise 草稿接线 | 答案边界和完整作答流 | `make acceptance-stage-6e` |
| 7A | 4D | Lichess 筛选同步、幂等 Game 存储和基础 Games UI | 脱敏 API/PGN/429 分页 fixture | `make acceptance-stage-7a` |
| 7B | 5D、6B、7A | 首次偏离、引擎损失与完整错误分类 | 个人库内错误/合理偏离对照棋局 | `make acceptance-stage-7b` |
| 7C | 7B | 课程/残局匹配、聚类、价值排序和生成练习 | 多盘重复/非重复错误集合 | `make acceptance-stage-7c` |
| 7D | 7C | 复盘、趋势和“错误 → 练习 → 复习”E2E | 固定用户历史 | `make acceptance-stage-7` |
| 8P | 4D、6A | CCEF v1、provider port、固定 Schema 与消费者边界 | 合法/非法/悬空/版本漂移 package | `make acceptance-stage-8p` |
| 8A | 8P | 内容哈希存储、Sources 页、PDF 页段与任务 | 文本/扫描/伪 MIME/重复 PDF | `make acceptance-stage-8a` |
| 8B | 8A | 渲染/OCR adapter 与 SourceSpan 候选 | 三页合成 PDF、mock OCR | `make acceptance-stage-8b` |
| 8C | 8B | mock/DeepSeek provider、CCEF/棋规/一致性验证 | 合法、非法、冲突 AI JSON | `make acceptance-stage-8c` |
| 8D | 8C | 三栏审核、审计、多来源合并与 Course/Knowledge 草稿 | 批准/修改/拒绝/重复发布 | `make acceptance-stage-8` |
| 9A | 8D | FFmpeg 音频/关键帧与 mock 转录 | 固定短视频 | `make acceptance-stage-9a` |
| 9B | 9A | 棋盘方向、连续局面和字幕对齐 | 翻转/遮挡/切镜/多解片段 | `make acceptance-stage-9b` |
| 9C | 9B | 时间轴审核、草稿发布和文件生命周期 | 重试/取消/发布失败 fixture | `make acceptance-stage-9` |
| 10A | 7D、8D | 生产 MySQL、镜像与 migration 发布流程 | 旧版本数据库/来源目录 | `make acceptance-stage-10a` |
| 10B | 10A | Nginx 路由、上传/认证/安全边界 | 路径穿越、XSS、越权请求 | `make acceptance-stage-10b` |
| 10C | 10B | 一致性备份、销毁后恢复和观测 | 完整部署快照 | `make acceptance-stage-10c` |
| 10D | 10C | 部署拓扑 Playwright 与发布门禁 | Compose 临时环境 | `make acceptance-stage-10` |
| 11A | 10D | Yjs/pycrdt/LMDB 草稿、awareness、重连收敛 | 双浏览器乱序/重复消息 | `make acceptance-stage-11a` |
| 11B | 11A | 草稿重新校验并原子发布 SQL | 版本冲突/重复发布/崩溃 | `make acceptance-stage-11` |

回退边界：每个字母单元默认只做向后兼容的 additive migration；新读写路径在对应验收绿之前受 feature flag 控制。删除列、收紧约束或停止双写必须推迟至少一个单元，并用旧版本数据库 fixture 证明升级；UI 单元不得偷偷改变前一单元的领域语义。

## 4. 需求追踪矩阵

下表防止原说明中的功能在“大阶段”里静默丢失。测试名是计划中的稳定行为名称，实施时应成为 pytest/Vitest/Playwright 的 marker 或测试标题。

| 原始需求 | 执行单元 | 自动化证据 | 延后理由 |
|---|---|---|---|
| Dashboard 统计、任务进度、快速入口 | 4A；任务进度 6A；导入入口 8A | `dashboard-actions.spec`、`job-progress.spec` | 先等真实 API，拒绝假统计 |
| 课程搜索、标签、排序、列表/卡片 | 4A | `course-catalog.spec` | 编辑器入口 |
| 局面图、转置、多分支、局部候选 | 2A–2C、4B | position vectors + `course-navigation.spec` | 核心 MVP |
| undo/redo、Markdown、来源、历史版本 | 4C；AI/分析历史 8D/6B | reducer tests + `editor-history.spec` | 要先有 occurrence/版本语义 |
| 全局图高级视图 | 4E | 环/孤立点 fixture + `graph-view.spec` | 明确非 MVP |
| 独立 Repertoire 页面与五种选择 | 5A | `repertoire.spec` | 依赖编辑器 MVP |
| 今日复习、自定义集、待掌握局面 | 5C–5D | frozen-clock tests + `practice-queue.spec` | 依赖卡片/FSRS |
| 六类答案策略 | 5B 四类；6C 两类 | answer-policy table tests | 引擎/表库策略不能提前假完成 |
| 选色/强度对弈、赛后回顾、保存发现 | 6D | fake UCI + `play-from-position.spec` | 依赖可靠引擎生命周期 |
| Lichess 日期/时控/颜色/开局筛选 | 7A | recorded adapter fixtures + `game-filters.spec` | 可与引擎部分并行 |
| 完整错误分类、残局匹配、价值排序 | 7B–7C | curated games + deterministic ranking tests | 依赖 Stage 6 分析 |
| 错误 → 练习 → 复习 → 趋势 | 7D | `game-error-learning-loop.spec` | 真正实战学习闭环 MVP |
| PDF 页码范围、OCR、SourceSpan | 8A–8B | synthetic PDF fixtures | 重计算走 SQL job |
| PDF AI 候选、审核、多来源冲突 | 8C–8D | mock structured outputs + publish transaction tests | AI 永不直写正式知识 |
| PDF/视频生成 Course/Knowledge 草稿；Exercise 后接 | 8D、9C；Stage 5 后 adapter | `publish-import-draft.spec` | 与审核发布共用边界，避免倒置分层 |
| 视频关键帧、转录、局面对齐 | 9A–9C | fixed short-video fixtures | 复用 PDF 审核基础 |
| 双模课程（traditional + opening_explorer） | 2D；API 4A；发布 4C | `course-mode.spec`、`note-source-link.spec` | 核心数据模型先行 |
| 传统课程按来源组织（书籍/视频/PGN → 章节，默认主线阅读并保留作者变例） | 2D、3B、4A | `traditional-course-navigation.spec` + PGN RAV fixture | 依赖 Course.mode + 编辑器 UI |
| 开局探索器按问题组织（局面多来源观点聚合） | 2D、4B–4C | `explorer-candidate-navigation.spec` | 依赖 Course.mode + 图导航 |
| 从传统课程发布章节到开局探索器 | 4C | `publish-to-explorer.spec` | 依赖编辑器 + 发布 API |
| 网页笔记与手工来源 | 4C | source CRUD contract + `web-note-source.spec` | 无需等 AI |
| 备份、恢复和来源文件一致性 | 5D 基础；10C 部署 | destroy/restore checksum test | 个人数据从 MVP 起可恢复 |
| 实时协作草稿与发布 | 11A–11B | two-client convergence + atomic publish | 不侵入个人核心闭环 |

## 5. 固定阈值、工具版本与夹具规则

以下是首轮实施基线；如真实数据证明不合理，只能通过 ADR 调整，不能在失败时临时放宽：

- **PGN**：黄金集合必须含至少 12 份棋谱；上限夹具为 5 MiB 或 50,000 个 move occurrence，2 核 CI 中导入在 15 秒内、峰值 RSS 低于 512 MiB；
- **浏览器**：Playwright 固定 Chromium，并测 1280×720、1440×900、1920×1080；核心控件不得在视口外或互相遮挡，axe serious/critical 为 0；
- **API 交互**：不含引擎/OCR 的普通 CRUD 在本地 CI fixture 上 p95 低于 500 ms；测试直接记录分位数，不凭肉眼感受；
- **FSRS**：Stage 5C 开始前锁定实现版本、默认参数和时区规则，并用上游公开参考向量加本项目冻结时钟向量交叉验证；
- **PDF**：基础 fixture 固定为 3 页、2 MiB 以下，覆盖文本、扫描图、棋谱和 bbox；上限/拒绝夹具单独生成，不把大型二进制提交到仓库；
- **视频**：基础 fixture 为 10–20 秒、5 MiB 以下；转录—局面对齐允许误差 ±750 ms，超出即进入人工审核警告；
- **任务**：租约、重试和取消测试使用虚拟时钟；不靠真实 sleep 证明正确，单元测试不得自动重试；
- **重型二进制**：Stockfish、Syzygy fixture、FFmpeg、OCRmyPDF、PaddleOCR 在进入各自单元前写入 `tools-manifest.lock`，记录精确版本、来源、SHA-256 和许可证；CI 安装后先验哈希；
- **MySQL**：Stage 3D 的 CI 使用固定镜像 digest 和 service healthcheck；本地 `acceptance-stage-3d` 可使用一次性容器，生产 Compose 仍到 Stage 10；
- **外部服务**：PR 中真实 Lichess/OpenAI 调用数为 0；fixture 必须脱敏，真实集成只在显式定时/手动 job；
- **安全发布**：依赖/镜像扫描的 Critical/High 未豁免项阻塞 Stage 10 发布；豁免必须有到期日和 ADR/issue；
- **覆盖率**：行覆盖率至少 80%、分支至少 75%；关键领域模块至少 90%。生成代码、声明文件和二进制 adapter 薄壳可以显式排除，但不得排除业务分支。

## 6. 推荐执行节奏与验收方式

当前 AI 棋书优先路线为：**完成 Stage 4 → 完成 Stage 6A–6D → Stage 8 → Stage 9 →
Stage 5 → 6E → Stage 7**。这只是交付顺序调整，
不是层级倒置：Source → Knowledge 先完成，Repertoire → Exercise 后接。2D 作为 ADR 0005
双模课程基础已经先于 Stage 3 落地；Stage 8 与 Stage 9 仍共用审核基础并顺序推进；
Stage 7B–7D 仍必须等待 Stage 6B 引擎分析和 Stage 5D 训练流。Stage 11 不应为了预留
接口提前侵入正式模型。

每个阶段交付时给用户的验收材料固定为：

1. 一条总命令及其退出码；
2. 新增行为测试清单和覆盖率摘要；
3. 对应 Playwright trace/报告（从 Stage 4 开始）；
4. migration 从空库/旧夹具升级的报告；
5. 外部依赖使用 fake 还是真实集成的明确标记；
6. 尚未自动化、确实需要产品判断的最多 3 项人工体验检查。

这样用户不需要通过人工读代码判断正确性，人工注意力只用于“这个产品是否好用、解释是否符合学习习惯”这类机器无法代替的决定。
