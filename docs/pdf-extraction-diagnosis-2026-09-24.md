# 棋书 PDF 提取：诊断、评测集与替代流程设计

日期：2026-09-24。状态：**诊断与设计提案，尚未实施或验收**。

本轮按操作者要求先分析，不修改产品实现、配置或测试，不重跑付费模型，不改变历史任务。
分析对象包括当前 dirty worktree；它包含上一轮尚未提交的结构补全与 annotation-window 改动，
不能把历史失败全部归因于现在的代码，也不能把现在的局部测试通过当成历史样本已修好。

## 结论

项目的本地单体、不可变来源、Position/MoveEdge、人工审核和发布边界总体合理。
主要问题集中在 **从有噪声的书页到严格候选对象之间的职责分配**：模型承担了太多本应由程序
完成的装配工作；一些启发式质量检查又拥有终止整段提取的权力。继续叠加通用 JSON 修复，
无法系统解决这两点。

建议保留现有 CCEF 作为审核/交换格式，引入内部、带来源的中间表示，让模型判断局部语义，
由本地编译器生成最终结构。把“证据提取成功”“可审核”“可发布”分开衡量。任何未识别内容
都必须显式保留，不能通过全变成 prose 或 unresolved 来制造成功率。

## 1. 本次证据与局限

- 只读 SQLite，检查 68 次提取：23 succeeded、39 failed、6 cancelled。
  这是不同 pipeline/prompt/config 版本下的历史运行台账，包含重试及重复页段，**不是当前准确率**。
- 检查 31 份失败 sidecar，涉及 23 个 run；对应原始响应全部重新校验 SHA-256。
  不是每次历史失败都保存了 sidecar，同一 run 可能包含多个阶段的报告。
- 对其中 19 份含 items 的完整响应运行当前 deterministic canonicalizer + strict decoder：
  6 份可以解码、13 份仍失败。这只是结构重放，**不包含完整证据绑定、棋规、增量组合或模型补全**。
- 对 `data/books` 7 本书共 3,493 页扫描嵌入文本统计；抽查导言、正文、变例和图示页，
  对 Catalan p7、Scandinavian p224、Attacking Chess p20、中文残局 p20 查看实际渲染图。
  文本量统计不等于 OCR 准确率，也不是逐页人工审读。
- 用当前函数重现两处真实 coverage 误报和三种记谱漏检；已有 coverage 测试 3/3 通过。
  这说明当前测试没有覆盖这些语义反例，不说明整个测试体系无效。
- 未调用远程模型，未测新流程质量；未运行 OCR runner 或全书棋盘识别；未更换模型或工具。

本地可复查材料：`data/debug/extraction-audit-20260924/`（gitignored）。
`books.json` 保存书籍 hash、页数与逐页文本量；`runs.json`、`failures.json`、`replay.json`
保存只读统计与重放结果；脚本及抽样页图/文本只留本地。初次探针有一个 decoder 函数名写错，
纠正后重放完成，没有修改产品代码。

### 书籍覆盖

以下页码都是 **PDF 物理页，1 起算**。

| 书 | 总页数 | 无嵌入文本页 | 已观察特征 | 评测角色 |
| --- | ---: | ---: | --- | --- |
| Smerdon’s Scandinavian | 672 | 5 | 无点回合号 `1 e4`、主谱穿插说明、跨页例局 | 普通开局、长变例、跨段 |
| The Catalan – Move By Move | 209 | 2 | 双栏、问答、棋盘字体成为字母串、断词、备选着法 | 布局、计划/变例判别 |
| The Makogonov Variation | 320 | 1 | 单栏、内嵌及嵌套变化、较长说明 | 注释和分支归属 |
| Endgame Strategy | 678 | 1 | 从图示中途局面开始、行棋方图注、同一步重述 | 起始局面、重复与新例局 |
| 1.d4 – The Chess Bible | 548 | 2 | 开局目录、plan、方括号变化、图示问题 | 新书迁移、嵌套变化 |
| Attacking Chess for Club Players | 545 | 1 | Unicode 棋子、`…`、战术图与教材叙述 | 字形规范化、图示续着 |
| 从入门到大师：国际象棋残局大全 | 521 | 520 | 扫描中文、浅色字、图注、图上虚线 | OCR、图文关联、非普通棋盘图 |

另有数据库历史来源 *Magnus Wins With White*，PDF 在 `data/sources/pdf`，不在当前
`data/books` 的七本中。其失败也计入历史台账，不混称为这七本书的评测结果。

## 2. 当前流程与准确的故障边界

```text
PDF asset + page range
  → PDFium 页面图 / 文本行
  → 文本量不足则整页 OCR
  → 本地棋盘识别及 operational FEN → 统一 evidence
  → 整个请求页段的一次模型生成：完整 CCEF
  → deterministic canonicalization
  → 缺失内容 structural supplement（必要时一次模型调用）
  → strict decode / evidence binding / metadata / 棋规 / consolidation
     失败则至多一次 generic scalar patch，再验证
  → regex move coverage → 至多一次 additive supplement → 再验证
  → 工件登记 / 增量组合 → 审核 → 批准后发布草稿课程
```

关键实现：

- `extraction/pdfium.py::_embedded_fragments` 使用 PDF 文本顺序和换行；保留 bbox，
  但没有显式列、字体、粗体、颜色、段落角色模型。双栏不必然读错，但关键视觉语义未保留。
- `services/pdf_extraction.py` 用非空白字符数量选择 embedded text 或 OCR，
  不能据此判断字体乱码、布局质量；空白/封面也可能触发不必要 OCR。
- `extraction/prompting.py` 要求模型同时生成结构、原子注释、证据选择和关系；
  `deepseek.py` 把 Schema 放入提示，JSON mode 也只是 JSON 对象模式，非关系约束证明。
- `extraction/contracts.py::_check_sequence` 同时验证 parent-before-child、连续 sibling_order、
  annotation 身份、两种 reading_flow exact-order projection。
- `extraction/candidates.py` 已经由本地按 fragment hash 重建 bbox/offset，方向正确。
  但来源引用存在不等于内容忠实；当前 complete 只证明返回的引用都能绑定，不证明所有原文被覆盖。
- `extraction/validation.py` 明确把非法/歧义棋步保留为带 warning 的结果；
  `consolidation.py` 能把不可播放部分保留为 unresolved/prose。因此不能概括成“棋规严格就会失败”。
- `extraction/recovery.py` 的 coverage 阶段仍要求补全后零 gap；任何失败都阻止这次候选完成。
  人工审核已有能力承接不确定内容，却常常拿不到前面结构门槛拒绝的结果。

## 3. Failure taxonomy

每条 issue 应分别记录 `stage / root_cause / symptom / scope / evidence / recoverability`。
终态的 `repair_failed` 只是症状，不能当成根因分类。以下是本次观察，不是互斥数量分桶。

| 类别 | 证据与表现 | 正确处理层级 |
| --- | --- | --- |
| F1 运行与传输 | OCR runner 不可用、secret 配置、HTTP 400/限流、空正式 content | 调用前能力检查；保留证据；局部重试/明确停止 |
| F2 证据识别与布局 | 中文扫描无文本；Catalan 棋盘字母串、断词；字形/列信息丢失 | 区域质量判断、OCR/字体规范化、布局证据 |
| F3 输出预算 | Catalan `6d4b9bc2…` finish=length，128,000 output tokens，JSON 截断 | 缩小生成单位和输出对象；不修补截断大 JSON |
| F4 表达和引用装配 | `page/physical_page` 混用、额外 kind、重复 ID/NAG、sibling_order、flow 顺序 | 本地生成机械字段；局部严格 proposal |
| F5 内容缺失 | Catalan `73fb52a5…`：128 nodes、45 个缺失注释 body、n128 无 flow；Scandinavian `0aec19b4…`：224 nodes、27 个缺失注释 body | 原文先落地，局部分类/注释切分；缺失不抹去其他内容 |
| F6 棋谱语义/上下文 | 分支父节点、同一步重述、从图起局、切在例局中段 | 来源约束 + 局面候选 + python-chess；多解留待审 |
| F7 错误质量判据 | coverage 把 alternatives/plan 合并成强制连续路径，且漏掉别的记谱形式 | 带类型的覆盖检查；启发式只能提出 issue |
| F8 修复能力不匹配 | 缺 evidence 时补丁试图替换集合被拒；不存在的 JSON Pointer；漏改 trusted metadata | 路由到有明确输入输出的局部任务；取消通用修复升级循环 |
| F9 增量与错误隔离 | 新独立例局曾因无 continuation 被拒（现已修）；单处异常阻止 segment/head | 连续性与独立例局分开；保留各块状态 |
| F10 可观测性与评测 | 成功中间 supplement 在后续失败时未完整落盘；root error 常只剩 `<root>:value_error` | 每步立即落不可变 stage receipt，脱敏 issue code；真实评测 |

历史 39 个 failed 的终态码：`ccef_invalid_package` 13，`ccef_repair_failed` 6，
`invalid_response` 3，`invalid_request` 3，`provider_secret_invalid` 3，`unavailable` 2，
`ccef_coverage_repair_failed` 2；invalid_json、invalid_job_payload、ocr_unavailable、unknown、
rate_limited、truncated、structural_repair_failed 各 1。不能用这些数推算 F1–F10 的占比。

### 两个可确定重现的 coverage 反例

1. Catalan p7 的选择题列出 `9...dxe4, 9...Na6`。当前 `_notation_candidates` 把它们合并，
   ply delta 是 **0**；`_path_covers` 却要求父子连续。原响应已有 n84、n104，均以 n17 为父。
   原书列出的是同一局面的备选着法，不能要求模型将它们变成同一路径。
2. p9 的计划包含 `17...Nc4 and 18...Nxe3`。ply delta 是 **2**，中间白方着法未给出。
   保留计划文字才忠实；自动发明白方着法才能满足错误的连续覆盖要求。

`_CONNECTOR` 接受逗号/and 等连接词，但没有检查连续 ply。两例都直接使用已保存、hash 验证的
原文重现，无需改动原始候选。另一方面，`1 e4 d5 2 exd5 Nf6`、`3.♕xd8+!!`、
`3…♕xd8 4.♗xe6#` 都产生零 coverage candidate。**零 gap 既不等于完整，也不等于正确。**
此外 coverage 达到 16 个 gap 后会跳过后续候选、没有 sequence 时也跳过；未来必须报告
`not_assessed / scan_truncated`，不能把未检查当作通过。

最新 Catalan `1a948782…` 主响应 146 nodes、32 annotations，仅 n12 无 flow；
最终失败的 coverage 调用返回空 content，8,192 completion tokens 全标为 reasoning。
最新 Scandinavian `0aec19b4…` structural 调用同样空 content，16,384 tokens 全标为 reasoning。
这些是保存响应中的事实；历史实际 outbound request 未完整保存，**不能确定是旧进程配置还是上游
兼容行为**，也不能仅凭本地 `none` 设置断言供应商必然关闭思考。

## 4. 架构判断

### 应保留

- Source → Knowledge → Repertoire → Exercise；PDF/CCEF 不成为正式 Position 图的替代品。
- 不可变 PDF/CAS、来源 hash、版本化工件、短事务、取消/幂等/乐观并发。
- python-chess 拥有持久化着法合法性；模型无权声称 authoritative FEN/UCI。
- 阅读顺序与棋局拓扑分开；从图示起局与文本起局共用证据入口。
- 独立于模型的人工审核及原子发布；未知证据、损坏工件不进入可信候选。

### 应改变

1. **CCEF 适合作为编译结果，不适合作为大模型直接填写的唯一工作格式。**
   nodes/annotations/reading_flow 三份互相引用的数据要求模型同步维护，相当于让生成器承担
   数据库约束。让模型只给出内容判定，编译器生成 ID、hash、metadata、顺序与引用。
2. **不确定性需要在解析层可表达。** `extra="forbid"` 保持；新中间表示用明确的 unknown、
   alternatives、missing_context 等判别类型，而不是放宽 Schema 或默默丢字段。
3. **审核入口与质量完备性解耦。** 证据绑定或来源损坏必须阻止对应工件被信任；语义不确定、
   缺失注释与启发式疑点应保留为局部 issue。错误引用不能降级成“可接受的引用”，应隔离该 proposal，
   从可信原文构造待审条目。语义失败不扩散到整本书。
4. **更少、明确、局部的模型职责。** 已有 structural recovery 的“选 span、本地复制文字”值得沿用，
   但应放到正向提取流程，避免先生成几十个悬空 annotation ID 再反推缺失正文。
5. **完备性要分类计量。** 每个来源区间都要有去向；文字保留、可播放棋步、计划引用和 unresolved
   分别计分。仅统计 hash 覆盖、合法率或 job 成功，会奖励遗漏和过度拒识。

## 5. 建议的新 extraction pipeline

```text
immutable PDF
  → PageEvidence（文本/区域/图示/原始像素）
  → SourceBlocks（列、段落、棋谱行、图注、页眉等；可含 unknown）
  → Semantic chunks（例局/小节 + 有界只读上下文）
  → 局部语义 proposal（来源 span、score/prose/plan/variation 等判定）
  → 本地棋谱解析与候选父节点解析
  → 本地 CCEF compiler（已解析内容 + 显式 unresolved + issues）
  → 独立质量报告 / 审核
  → 既有人工批准与发布
```

### A. Evidence first

保留现有 PDFium、OCR、diagram 端口，先不引入大框架。为页面区域保留稳定 span ID、bbox、列、
可取得的字体/样式、原始文本和规范化文本之间的 offset map。已知 Unicode 棋子、ellipsis、
软断词等可以做可逆规范化；字体映射未知就标 unknown，不能任意把棋盘字母串当着法。

按区域判断 embedded text 是否可用，扫描区域走 OCR；空页/页眉/棋盘字体区域有独立角色。
原图和原文总在，不为减少噪声永久删除内容。中文棋盘中的虚线等教学标记应能成为普通 figure，
不能强制识别成完整可操作棋局。棋子摆放、行棋方、易位权和 en-passant 的已知程度分开记录；
diagram 的 operational 假设不能被展示为书中明确给出的事实。

### B. 语义分块与上下文

以例局、理论小节、图示题为主要边界，页数只作为预算保护。先从 1–4 页的局部任务试验，
具体 token/span 上限由评测决定，不承诺固定页数通吃。较长例局允许续接块，但不能丢弃主线栈。

每块有 `owned_spans` 和 `context_spans`：前者唯一归属、后者只读，可引用已验证的 continuation
catalog。上下文以例局身份、尾部位置和必要变例为单位，不反复复制全部历史内容。
若页段从中途开始，找不到可信前驱或图示，明确 `missing_context`，不猜 FEN。
块身份绑定 PDF/evidence hash、来源区间和算法版本；断点恢复复用已完成块。

### C. 模型生成语义 proposal，本地生成机械结构

内部 IR 至少区分：`heading / narrative / score_span / variation_span / annotation_span /
move_mention / diagram / unknown`。每条保留来源 span、阅读次序和判定依据的来源引用。
原子注释通过来源子区间表达，文字由本地复制，不要求模型重新抄整段。

模型只回答：这是什么内容、属于哪个例局、这里是否切换分支、注释可能指向哪个局部锚点。
父节点选择只允许当前块/显式前驱目录中的候选；可以返回 ambiguous，不允许编造前缀。
输出无需复制完整 schema 元数据、长 SHA、bbox、FEN、重复 reading_flow，短 ID 映射由本地保存。
每个 proposal 本身仍是 bounded strict schema；坏 JSON 隔离为该块失败，原文进入 unknown。

本地 tokenizer 支持样本中的点号/无点号/Unicode 记谱，保留原始 token；python-chess 验证
候选路径。合法只证明走得通，不证明是书的主线；最终选择还必须满足回合、局面、例局、来源顺序
和分支提示。多个合法父节点不能随便取第一个。

### D. 编译、问题隔离与增量

从唯一来源事件序列派生 node ID、annotation ID、sibling_order 和 reading_flow，避免让模型
分别输出三份平行集合。同一着法在书中重述时保留多个 mention，而非复制棋局路径；与现有 CCEF
的“每节点一次 flow”不兼容的重述先保留为带来源 prose，不能丢掉原书展示。

已解析内容编译到现有 CCEF 1.1；局部无法解析的真实文字编译为明确 unresolved/prose + issue，
不会伪造节点或静默忽略坏引用。若来源顺序无法满足现行 CCEF 的 parent-before-child/order 约束，
显式保留待审，而不是强行重排原书；只有评测证实必要才另立 CCEF 升版 ADR。

结构正确的部分候选可审核，但 unresolved score、未知起局与未处理缺失仍阻止发布。
质量状态建议 `complete / needs_review / partial / unavailable`，与 Job 的执行生命周期分离。
全 unresolved 是 extraction failure/partial，不计为高质量成功。
需设计 partial 的 API/工件与 review issue 映射，不能只修改前端标签。

跨块仍使用 hash-bound continuation，保留 occurrence/例局身份，不因为 FEN 相同就把两局合并。
首次迭代继续顺序执行，无需分布式或并行任务系统。

### E. 有预算的局部修复与可观测性

结构字段错误由编译器消除；OCR 字形、注释归属、分支歧义分别成为具体局部任务。
每块先至多一次额外模型判定，失败保留 unresolved，不自动升级为重抽整页段。
扫描总预算、最大调用数、超时/取消必须在调用前可检查；不通过增加总 token 掩盖根因。

每步完成立即保存 receipt：输入工件 hash、输出 hash、版本、有效模型/参数、finish reason、
reported input/output/reasoning tokens、耗时、issue、局部重试关系。保存失败链的成功中间产物。
本地保存实际请求的脱敏快照和正文引用；不记录认证头/密钥，不把 provider reasoning 文本作为必需
调试数据。只有最终发布使用原子 SQL 事务；中间工件可独立审计与重放。

## 6. Evaluation set 设计

配套 `pdf-extraction-evaluation-set-v0.json` 是 **待标注 manifest，不是完成的 gold set**。
21 个核心窗口：每本书 2 个 development + 1 个 holdout。所有旧失败页段另列 replay bank，
不得混入 holdout。固定物理页与书 hash；人工确认窗口是否跨例局时，可追加只读上下文，
不悄悄改变被评分的 owned 页段。相邻段/同一例局必须归于同一个 split。

当前已检查过七本书的版式，因此这只是“未调参的页段留出”，不声称是未知书籍泛化测试。
后续需要未知书测试时再单独冻结未用于设计的书；不要不断查看 holdout 后继续叫它 holdout。

### 三层评测

1. **离线历史重放：**31 sidecar、原响应和可信 evidence；区分 raw / canonicalized /
   recovered / normalized 的结果。只验证现有模型输出能否正确消费，不能评估新 prompt 的生成能力。
2. **核心 gold 窗口：**每窗人工标主要正文区、章节/例局边界、主线 UCI 路径、变例父节点、
   注释来源区间/锚点、图示摆放与已知局面字段、plan/alternative、允许保持 unresolved 的部分。
   不要求逐页逐字重录：完整标棋谱结构，正文通过 span 对齐；OCR 则单独抽取确定区域做转录 gold。
   模型可以辅助预标，但 gold 不能直接取当前 parser 或修复后的输出。
3. **无版权小反例：**无点记谱、Unicode、同 ply alternatives、非连续 plan、跨行、重复印刷、
   分支切换、图示缺行棋方、整页空白；从真实机制抽象，CI 不包含用户书籍或网络调用。

### 度量和分母

| 指标 | 定义 | 防止的假进步 |
| --- | --- | --- |
| 来源保留率 | gold 正文字符区间被 preserved/resolved/unresolved 覆盖的比例；furniture 单列 | 静默丢正文 |
| OCR/字形错误 | 已标区域的 CER + 棋步 token 错误率，按书/扫描与否分组 | 英文正文掩盖棋子误识 |
| 棋步 precision/recall | source occurrence 对齐后 UCI 正确的节点 / 输出节点、gold 节点 | 全变 prose、合法但幻觉 |
| 主线 exact match | 起始局面、完整主线路径均匹配的 gold 序列比例 | 高逐步正确率掩盖一处断线 |
| 分支归属 | gold variation root 接在正确 parent occurrence 的比例 | 走得通但挂错树 |
| 注释保留与锚点 | 原文区间覆盖率；在确有 gold anchor 的注释上计锚点准确率 | 抄回注释却贴错位置 |
| 图示 | 已标图的检测召回、placement exact match；其他 FEN 字段按已知度计分 | 用缺省 FEN 冒充识别 |
| 重复/幻觉/次序 | 重复来源事件、无证据内容、阅读关系逆序的数量 | 以多生成提高召回 |
| validator FP/FN | gold 正确候选被硬拒、gold 缺失未报警，按规则分组 | 错误 oracle 驱动修复 |
| 用户成本 | 每窗可审核比例、实际人工修订分钟/操作数、调用次数、reported token、耗时 | 用无限修复换成功 |

按窗口、书籍类型做 macro 汇总，同时给出分子/分母；不只报大量简单主线主导的 micro 平均。
`not_assessed`、依赖缺失、partial、cancelled 单列。固定版本、输入证据和调用预算；保存全部尝试，
不能选最好一次。线上采样若获授权，对固定小窗口按预先规定次数比较，不按结果无限重试。

### 首个验收目标（提议，尚无实测）

- 两个已证实 coverage 反例不再产生“必须补成连续路径”的硬拒；完整变例 gold 仍能发现遗漏。
- 21 窗口均可打开来源与问题报告；依赖不可用如 OCR 未安装时清楚标 unavailable，不计提取通过。
- 可信来源丢失、模型伪造权威 FEN/UCI、未批准发布、历史工件覆盖：在评测中零容忍。
- 对已明确 gold 的正文 span 保留率目标 ≥99%；主线 exact-match 目标 ≥95%；变例父节点准确率
  目标 ≥95%；hallucinated playable moves 为 0。小样本必须同时报计数，不能把百分比当统计保证。
- playable recall、注释保留率不低于冻结基线；同时硬失败和人工修订成本下降。
  全 unresolved 即使可打开也不能通过该质量门。
- 在固定质量门通过后比较 token/耗时，目标先减半；预算与 OCR 启动成本分别核算。
  当前没有证据保证这些目标能达到；首轮基线负责校准，不事后移动 gold 迎合实现。

## 7. 实现顺序与决策点

本轮到设计为止。下一轮不先继续追加第 N 种 repair exception。

1. **先冻结诊断和评测：**完成 6 个代表窗口的人工 gold（Catalan、Scandinavian、Makogonov、
   Endgame、Unicode、中文），建立本地只读 runner 和质量报告。补足其余窗口前不宣称覆盖全书。
2. **最小纵向试验：**用固定证据在 Catalan/Scandinavian 上比较旧完整 CCEF 生成与
   span proposal + 本地 compiler；真实新生成另行使用明确的调用预算。先证明注释保留、变例父节点
   和可审核结果，不动课程模型，不上 OCR 大改。
3. **验证可行后写 Accepted ADR：**明确新 IR、stage artifact、partial 状态与迁移边界；
   提案涉及 ADR 0014（生成粒度）、0018（分块/续接）、0021（恢复策略），不能假装只是 parser 修 bug。
   若纵向试验失败，则保留证据并调整职责划分，不扩散改动。
4. **接入共享后端：**新 pipeline version，复用现有 PDF/CAS、review 与 publication。
   旧 run 不重写；离线先验，之后再接 API/UI。按 slice 跑相关检查，结束阶段才跑较大验收。
5. **扩展证据质量与全样本验收：**扫描中文、双栏/字体、棋盘特殊标记；冻结 holdout 后统一评估。
   选 OCR/多模态工具必须由这组样本的 CER、棋谱质量和成本决定，当前不预先指定新框架或供应商。

未解决的事实问题：历史调用的实际有效 thinking 参数、真实新 proposal 的模型质量、中文 OCR
表现、图示识别在七书上的准确率、人工审核时间。这些各有独立实验，不能再混成一个
“提取是否 succeeded”的信号。
