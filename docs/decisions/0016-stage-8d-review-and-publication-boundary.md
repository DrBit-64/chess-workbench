# ADR 0016：Stage 8D 人工审核与草稿发布边界

- 状态：Accepted
- 日期：2026-08-13
- 依赖：ADR 0006、0010、0014、0015

## 背景

Stage 8C 已能保存不可变 raw CCEF、规范化 CCEF 和证据页。模型输出仍然只是候选；审核页面不能
直接修改这些工件，也不能把前端显示状态当成正式审核记录。Stage 8D 需要同时满足可阅读、可修改、
可追溯和原子发布，并继续保持 Source → Knowledge 的人工边界。

## 决定

### 1. 分成检查、审核修订和发布三个层次

1. **检查层**纯读取 normalized CCEF，确定性生成 issue 列表、阻断原因和证据定位，不写 SQL；
2. **审核层**以 normalized CCEF hash 为基线，保存消费者自己的审核 session、不可变修订和审计事件；
3. **发布层**只接受已批准的精确修订，在一个事务中生成 traditional Course/Module、有序正文、
   occurrence、KnowledgeNote、SourceSpan 和幂等 receipt。

任何层都不得覆盖 raw/normalized/provider artifact。修改后的内容是新的审核修订，不是假装 AI 原来
就输出了该内容。

### 2. 只读检查先于 UI

检查顺序遵循 CCEF item/node/diagnostic 的来源顺序，至少识别：item/node warning、非法或歧义棋步、
unresolved、error diagnostic、超过内部限制的标题、多 NAG、无法唯一定位的 position anchor，以及
尚未解决的 figure。检查结果只说明候选是否存在发布阻断；即使零 issue，也仍必须由人明确批准。

检查逻辑位于后端消费者层。React 只能显示后端结果，不能重新计算棋规、阻断条件或冲突计数。

### 3. 浏览器读取面最小披露

后续只读审核 API 仅返回：已验证的 normalized CCEF、检查结果、候选 hash、页码列表，以及受控的
rendered-page 内容 URL。它不得返回 provider response、raw CCEF、CAS 相对/绝对路径、API key 或
任意服务器文件读取接口。每张页图必须由 run ID + 物理页解析到已登记的 `rendered_page` artifact，
并在读取时复核大小、媒体类型和 hash。

第一版审核页采用来源页图、棋盘、候选内容/变化与 issue 三个主区域；宽屏可把内容目录拆成窄栏，
窄屏按页图 → 棋盘 → 内容顺序堆叠。棋谱节点、正文锚点和证据片段可以互相定位。先完成只读浏览，
再加入修改操作。

### 4. 审核修订与审计

每个 extraction run 最多有一个 review session，并固定绑定创建时的 normalized CCEF SHA-256。
session 使用 expected-version 乐观并发。每次修改、批准、拒绝或重新打开都创建不可变 revision/event，
记录父版本、操作种类、修改后 canonical review package hash、结构化决定和 UTC 时间；不存聊天思维链。

审核修订仍必须通过 CCEF Schema、引用完整性和 python-chess 校验。拒绝内容必须是显式决定；不允许
通过从 JSON 删除 item/node 来隐式消失。批准要求所有 warning 已被确认，所有 blocking issue 已通过
可审计修改或拒绝决定解决。

#### 8D-4 持久化细化（2026-08-24）

审核 session 绑定二元组“目标身份 + 创建时精确 normalized CCEF hash”。目标恰为一个 extraction run
或一个增量 `PdfExtractionDocument`；后者继续增长后，以新聚合 hash 打开新 session，不把旧审核基线
静默推进。session 是唯一可变 head（`status`、`version`、UTC timestamps），revision 与 event 都是
不可变追加事实。revision number 与 resulting session version 一致，event 明确记录 parent/resulting
version、操作类型和有限结构化决定。

创建 session 时先经过既有只读审核加载器完整验证 CCEF、证据页和 CAS 绑定，再让 revision 1 直接引用
已验证 normalized CCEF 的 content-addressed object；不会覆盖或复制 raw/provider 工件。创建事件为
`created`，父版本为 0、结果版本为 1。8D-4 只开放创建/复用和读取账本；edit/acknowledge/approve/
reject/reopen 的状态机和 expected-version 命令由 8D-5 实现。

为避免大型候选和服务器路径泄露，公开账本只包含目标、baseline hash、状态/version、revision 的 hash
与序号以及结构化 event；不返回 revision CAS 路径或 CCEF 正文。现有审核文档 API 仍负责返回经过验证的
候选正文与页图。

#### 8D-5 命令与棋谱交互细化（2026-08-24）

审核页面不提供任意 CCEF JSON 编辑器。前端提交带 expected-version 的语义命令，后端在当前不可变
revision 的副本上执行、重新规范化并写入新的 CAS revision。棋盘录入一串合法 UCI：当前局面没有
后续时成为主线，已有其他后续时成为最后一个变招，已存在相同 UCI 时只进入既有分支而不创建重复节点。
用户新增棋步明确采用当前显示的物理页作为页级 EvidenceRef；后端生成本地 ID、SAN、回合/行棋方与
前后 FEN。

棋谱菜单采用 Lichess 式语义：`delete_subtree` 从选中棋步开始显式排除整棵子树；
`promote_variation` 只在同父候选中向前提升一级；`make_mainline` 把通向选中节点的每一层候选提升为
主线。结构修改后，节点保持父先于子并同步重建 exact-cover reading flow；与被删节点绑定的谱内注释
随显式删除决定移除，旧 revision 继续保存完整历史。heading、prose 与谱内 annotation 使用受控文字
命令，NAG 必须明确选择零个或一个。

`acknowledge` 只确认当前非阻断 issue；任何后续 edit 都使旧确认失效。`approve` 要求当前没有 blocking
issue 且所有非阻断 issue 已确认。`reject` 与 `reopen` 是显式状态转换。所有成功命令——包括只改变
状态的命令——都追加一条 revision/event，绝不覆盖提取工件或旧审核内容。

### 5. 既有映射阻断的处理

- `EvidenceRef` 始终完整保留在审核修订。发布所需的 SourceSpan fidelity 通过 Stage 8D migration
  增加 fragment hash，并允许 page/bbox 与成对 text offsets 共存；不得塞进不透明 context 冒充映射。
- 多个 NAG 不自动取第一个；审核者必须明确选择零个或一个，选择记录在修订中。
- position anchor 只在候选模块中恰好匹配一个规范 full FEN 时自动解析；零个或多个匹配都阻断并要求
  人工选择。
- chessboard figure 只作证据且必须解析局面；其他 figure 必须显式拒绝，第一版不发布媒体块。
- 超长 heading 必须编辑，不能截断。plain prose 在发布时使用固定 literal-to-Markdown escaping，
  markdown prose 继续走现有 sanitizer。

### 6. 发布目标与幂等性

第一版发布创建或追加到用户明确选择的 `mode="traditional"` 草稿课程，绝不直接设为 published，
也不写 Repertoire/Exercise。两个来源对同一局面的说明作为独立、带引用的 Knowledge 候选并存，不互相
覆盖。发布 receipt 由 review session + 精确 revision + mapping version + 目标组合唯一确定；重放返回
既有结果，任何校验、版本冲突或写入失败均为零部分写入。

## Stage 8D 顺序

1. 纯 CCEF review inspection；
2. 受控只读审核文档/页图 API；
3. 只读浏览器审核页；
4. review session/revision/event 与 evidence migration；
5. 修改、确认、批准、拒绝 API；
6. Course/Knowledge 草稿映射和原子发布；
7. 交互编辑 UI、多来源合并与 Stage 8 总验收。

## 后果

- UI 可以尽早展示真实五页数据，但不会成为数据修复器或业务规则来源；
- 所有 AI 原文、规范化结果、人工修改和正式草稿均有独立身份与 hash；
- Stage 9 可以复用审核 session/event/publish 边界；
- 第一版实现步骤较多，但避免把候选状态、正式知识和供应商输出混在一张表或一个 JSON 中。
