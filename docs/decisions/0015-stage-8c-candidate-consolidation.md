# ADR 0015：Stage 8C 候选棋谱的确定性规范化与去重

- 状态：Accepted
- 日期：2026-08-13
- 依赖：ADR 0010、0014

## 背景

真实 PDF 页 319–323 已能生成严格 CCEF，但 DeepSeek 把少量编号变例重复输出成 16 个
`move_sequence`、362 个节点。同一变化最多出现四次，每条变化又重复从起始局面开始的公共前缀。
本地证据审计确认叙述性计划正文仍是 `prose`；问题不是 OCR 或正文分类，而是模型输出缺少确定性
的路线去重、前缀共享和错误分支隔离。

Stage 8D 审核页面不能承担数据修复职责。页面开始前，normalized CCEF 必须已经是可解释、可播放、
可离线验收的候选文件；原始 provider JSON 和 raw CCEF 仍保持不可变，便于追溯。

## 决定

### 1. Raw 与 consolidated normalized 分离

`raw_ccef` 永远保存 decoder 接受且绑定可信元数据后的原始模型结构，不去重、不覆盖。候选装配先用
python-chess 独立重建每个 source sequence，再进行确定性 consolidation，最后再次用 python-chess
验证合并树。`normalized_ccef` 保存 consolidation 后的结果。

因此相同 raw bytes、相同算法版本必然产生相同 normalized bytes/hash；审核和发布只消费 normalized，
但始终能回到 raw/provider response 查证。

### 2. 合并边界是标题作用域，不是整包全局

扫描 source-order items 时，以最近出现的 heading ID 作为当前作用域。仅当以下值全部相同时，多个
`move_sequence` 才能进入同一个合并组：

- 当前 heading 作用域；
- initial position；
- sequence title；
- sequence extensions。

这能让 Introduction 中的示例线与后续 Game 13 保持为不同内容块，同时允许 Game 13 内分散在正文
之间的编号变例合成一个变化树。未来若模型提供更精确的 section ID，可替换 heading 作用域，不改变
CCEF 协议。

### 3. 只用本地棋规身份去重

每个已经合法重建的节点以从组内 initial position 开始的 UCI path 作为身份。同一 path 只保留一个
节点；相同 parent position 下相同 UCI move 只保留一条 edge。首次出现顺序决定节点和 sibling 顺序，
不使用随机值、数据库 ID 或模型置信度打破平局。

输出 `move_text` 使用本地 canonical SAN；原始 `!`、`?`、`!!`、`??`、`!?`、`?!` 转为标准 NAG
1–6，并与模型显式 NAG 去重。重复节点的 evidence 取稳定并集，因此压缩结构不会丢失来源。

在提供完整 evidence pages 的 PDF 候选管线中，还要对“可播放棋谱”采用更保守的
证据门槛：仅当一个独立排版片段以回合号开头，且除回合号外全部是可解析 SAN 棋着时，
才把它接入该标题作用域的正式棋谱。含普通句子的段落即使出现 `Nf3`、`...e5` 等词形，
也不会被转成 timeline move；它们保持为 `prose`。这项判定仅使用片段结构与棋规，
不使用书名、页码、章节名、特定棋着或预期节点数。没有 evidence pages 的纯 CCEF 消费者
则继续使用上述 UCI trie 合并，保持可移植合约的独立性。
模型树中即使棋规合法、但不在正式证据线上的分支也不会被静默丢弃：其未被其他内容项覆盖的
证据必须转成 `prose` 或 `unresolved`，才能从可播放树中移除。

### 4. 非法节点不得进入可播放树

只有 validation status 为 `valid` 且祖先均可重建的节点进入合并树。非法、歧义或断裂节点及其后代：

- 如果所有 evidence 已被非棋谱 item（通常是原文 prose）覆盖，则从可播放树移除，正文仍是完整审计
  依据；
- 如果存在未被非棋谱 item 覆盖的 evidence，则生成 `unresolved` item，保存原始 move text、证据和
  固定原因，不猜测父局面或 FEN。

不得通过在所有已知局面中试走棋子来“猜一个能走通的 parent”；这种修复可能制造书中没有表达的
路线。人工审核之后才能决定如何重新连接 unresolved 内容。

### 5. 引用、顺序与兼容性

合并组以其首个正式棋谱证据的位置出现。提供完整 evidence pages 时，所有 item 按最早 fragment 的
物理页/页内 order 稳定排序，而不信任模型给出的 item 数组顺序；没有精确 fragment 的消费者继续
保持原始相对顺序。已有 prose move-node anchor 和 diagnostic 引用若指向保留节点，则映射到新节点；若指向
被隔离节点，则降级为未锚定内容并增加确定性 warning，禁止留下悬空引用。

CCEF v1 Schema、provider 端口和 raw artifact 格式不变。此步骤是 ChessWorkbench consumer-side 的
确定性派生，不要求其他网站采用相同合并策略。
识别逻辑指纹在引入该派生算法时升级，使同一 PDF/页范围的新请求不会回放旧版
normalized artifact；旧的 raw/provider artifact 仍保持不可变。

## 五页验收标准

对已存页 319–323 raw CCEF 进行纯离线重算，不再次调用 DeepSeek：

- 用户指出的 Introduction 计划段仍只属于 prose，不产生 move node；
- Introduction 示例线和 Game 13 为两个独立 `move_sequence`；
- 每个组内不存在重复 UCI path 或同 parent 下重复 UCI；
- 所有输出 move node 均为 `valid`，非法/歧义计数为零；
- 标题、正文、图片及其 evidence 保留；raw CCEF 已引用的所有 fragment hash 均仍可从
  normalized CCEF 追溯；
- 输出节点量应接近唯一棋图 edge 数，而非模型重复线总和；精确数量由算法和真实证据报告，不在实现
  前硬编码；
- pretty inspection JSON 可以独立阅读，并附机器生成的计数报告；在这些条件通过前不开始 Stage 8D
  图形审核页面。

## 测试策略

使用 synthetic CCEF 证明重复线、共享前缀、NAG、标题作用域、非法节点隔离、unresolved fallback、
anchor/diagnostic remap 和输入不变性。真实书籍只用于本地离线验收，不提交版权文本为测试 fixture，
不调用 provider，不运行全项目 acceptance。
