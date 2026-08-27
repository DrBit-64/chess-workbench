# ADR 0018：增量 PDF 提取文档、分段续接与不可变聚合修订

- 状态：Accepted
- 日期：2026-08-22
- 依赖：ADR 0010、0012、0014、0015、0016、0017
- 取代：ADR 0014 第 2 节的“一个 run 覆盖完整目标页段”作为新任务的默认方式；历史 run 保持不变

## 背景

物理页 319–323 的真实 CCEF 1.1 提取和浏览器审核已经证明，约五页的语义块能够保留连续
主谱、局部分支、原子注释与来源证据。继续把同一章节扩展到第 328 页时，重新发送
319–328 页会重复付费、放大输出与失败半径；把 324–328 页作为完全独立的 run 又会丢失
跨边界棋谱父节点，并在 Sources 和审核页中形成两个无关条目。

更长章节也不能依赖无限扩大的单次 provider 请求。系统需要允许用户按若干个相邻语义块
顺序处理，在任一块失败时保留此前已验收的结果，并把所有成功分段作为一个可审核条目。
当前需求只涉及提取；翻译、双语工件和自动分块调度均不在本 ADR 范围内。

## 决定

### 1. 提取文档是用户可见身份，run 是不可变执行分段

新增消费者侧 `PDF extraction document` 概念。一个文档固定绑定一个 `PdfAsset`，拥有按
`ordinal` 排列的分段；每个分段引用一个既有的不可变 `ExtractionRun`。资料库以 `PdfAsset`
作为一本书的顶层身份；同一资产下可以同时存在多个独立 run 和多个增量 document，页段相同
也不合并。document 在书籍详情中显示为一个提取结果，其分段 run 只在该结果内部和诊断中显示。

第一版只允许手工顺序追加：

- 第一段可登记一个已经成功并提交 normalized CCEF 的兼容 run，因此页 319–323 的 v12
  工件不重跑、不复制、不覆盖；
- 后续分段必须与当前文档页段严格相邻，不能重叠、跳页或并行分叉；
- 一个 run 最多属于一个文档，文档始终绑定同一个 PDF asset；
- 创建下一分段时固定当前聚合修订 hash 和 expected version。并发追加以 `stale_version`
  拒绝，不能产生两个都自称下一段的 head；
- 分段 Job 失败、取消或只提交部分非候选工件时，文档 head 仍指向上一个成功聚合修订。

自动把任意大范围切成若干任务可以在未来复用同一 append API，但第一版不加入调度器或
并行合并状态机。

### 2. CCEF 1.1 保持不变，增量关系由独立内部协议表达

CCEF 继续描述一个自足的来源候选包，不增加 ChessWorkbench 文档 ID、run ID、前驱 revision
或数据库状态。增量执行使用独立、版本化的消费者协议：

- **continuation context** 绑定前一聚合 normalized CCEF 的精确 SHA-256、package/source/page
  身份，并列出模型可以选择的棋谱续接锚点；
- 每个锚点由该基线包内的 sequence ID、可空的 `after_node_id`、对应规范 full FEN 和最多
  八个最近规范棋步组成；锚点 ID 只在这份 hash-bound context 内有意义；
- 只从本地验证为合法且父链完整的节点生成锚点。转置到相同 FEN 的两个来源路径仍是两个
  不同锚点，不能仅凭 FEN 猜测父节点；
- 下一分段的 provider 响应仍包含一份只引用新页证据的 CCEF 1.1 package，并用独立 binding
  声明某个本地 sequence 应接到哪一个允许的基线锚点；
- binder 必须精确验证基线 hash、锚点成员、sequence 引用、边界 FEN 和新页证据范围。模型
  不能提交任意旧 node ID，也不能把上下文页伪装成新证据。

上下文中可以另外携带前一物理页的有界文本和当前标题，帮助理解跨页句子；这些值标记为
context-only，不进入新 package 的 EvidenceRef。所有锚点都按基线 item/node 来源顺序提供，
每个锚点的 path tail 有固定上限；如果完整目录仍超过 prompt 上限，任务以稳定错误停止，
不得静默删除可能被后页引用的旧分支。

EvidenceRef 采用两阶段信任边界。provider 只负责选择
`physical_page + fragment_sha256`，不负责生成 PDF 几何坐标或文本偏移；`bbox`、
`start_offset` 和 `end_offset` 即使出现在响应里也会在结构校验前被丢弃。本地代码随后以该
页码和摘要精确查找本次 prompt 中的可信 OCR fragment，写回规范的 `[x0, y0, x1, y1]`
归一化坐标，最后才运行完整 CCEF 与棋规校验。缺少或无法匹配的摘要必须拒绝；不得猜测坐标
顺序、按近似 bbox 反查、交换坐标轴或加入针对具体书籍、页码和棋步的修复规则。

### 2.1 已保存失败响应的通用有界修订

完整、非截断且仍能解析为 JSON object 的 provider 响应如果只含规模有限的结构、引用、拓扑、
棋步上下文、metadata、continuation 或证据选择错误，不应重新发送 PDF、全部上下文并重新生成
正文。系统保留原响应，并允许至多一次独立修订调用。JSON 语法已经大面积损坏、内容缺失、
独立诊断超过 32 项或受影响内容项超过 8 个时不进入局部修订，应停止并转为人工检查或完整
重提取。

修订入口把 Pydantic/CCEF 错误、棋谱结构扫描、可信 EvidenceRef 选择检查和后续 pipeline
失败转换为稳定的结构化诊断。每条诊断包含 code、JSON Pointer、简明 invariant、内容项/节点
身份；重复的派生症状由模型结合受影响内容、增量锚点与相应可信 OCR fragments 判断共同根因。
这不是按历史错误类型分别编写专用模型任务，也不把任意原始异常或完整应用状态直接拼入提示。

在付费修订之前先执行极窄的、本地确定性规范化。它只能处理不需要语义判断且不改变来源含义的
规范形式，例如对本来就是集合语义的 NAG 数组按首次出现顺序去重；当 nodes/annotations 与
reading_flow 含有完全相同且唯一的身份集合时，也可以让数组服从显式阅读流顺序，但节点重排后
必须仍然满足父节点先于子节点。不得选择棋谱父节点、改写正文、猜测证据或用书名/页码/棋步做
特判。若规范化后的候选已经通过完整本地执行链，则直接记录规则与路径并跳过 provider。仍失败
时，诊断路径必须先剥离 Pydantic 判别联合的内部标签，变成针对原始 JSON 的真实 Pointer；提示
中的摘录以“真实 Pointer → 原始值”表达，不使用可能被模型误复制进结果的包装对象。提示默认只
携带命中的 item/node/annotation 与相邻 reading flow；拓扑错误可携带完整受影响序列，但只有
continuation binding 错误才携带续接上下文。

上述规范化不是增量流程的特殊补丁。所有 CCEF 1.1 候选必须在严格 Schema、可信 EvidenceRef、
棋规和聚合验证之前调用同一个 `canonicalize_ccef_response` 边界；独立语义提取和增量提取只在
规范化之后分别进入独立候选提交或 continuation binding/文档合并。若发生本地重排，provider
工件必须同时保留原始响应、确定性规则/路径和修复后摘要，不得用规范化内容覆盖原始模型输出。

provider 只返回绑定原响应 SHA-256 的 `chess-workbench/ccef-repair/2.0` 补丁，操作限定为
`add`、`remove`、`replace`。模型可以修改现有内容项内部的小规模字段、现有 reading-flow entry
内的标量引用、父子关系、兄弟顺序和有证据支持的转录字段，也可以恢复 caller-owned metadata；
但不能替换、增删 reading-flow entry，不能替换整个 package、增删 item/node/annotation/evidence
核心集合或引用提示以外的证据。补丁最多 64 个互不重复的路径，序列化后最多 256 KiB，源文本
总长度变化最多 4096 个 code points。

语义提取可以启用模型思考，但不同时强制 DeepSeek 的 JSON Output 传输开关；结构约束仍由提示
中的完整 Schema 和本地验证器执行。HTTP 成功但正式 content 为 null 或纯空白时，原始响应继续
保存用于诊断，错误保持 non-retryable 并明确要求操作者手动重试，系统不得自动重复整次付费请求。

本地应用器验证补丁基线 hash、路径权限、核心内容/证据数量、可信 metadata 精确值及每一个
EvidenceRef 的 `(physical_page, fragment_sha256)`。随后普通增量执行链重新运行 CCEF 1.1、
可信证据几何绑定、metadata、continuation binding、python-chess normalization 和聚合校验；
只有整条链成功才能登记 provider/raw/normalized 工件并推进 document head。修订失败或传输
失败时立即停止，不进行第二次修订。原始响应、确定性修正规则和已收到的模型修订响应都保留
为诊断工件；离线工具可以先重放本地规则，只在仍有歧义时构造、执行或重放模型协议，且不修改
SQL 权威状态。

### 3. 聚合修订是确定性派生，不覆盖任何分段

每次成功追加分段后，系统从“前一聚合修订 + 新 normalized 分段 + 已验证 continuation
bindings”产生新的不可变聚合修订：

- 聚合 package 的来源页段扩展到文档完整连续范围；
- 本地 sequence 节点在选定锚点处接入，棋步由 python-chess 再次验证；未绑定的 sequence
  作为新内容保留；
- item、annotation、reading flow、diagnostic 与 EvidenceRef 做确定性 ID 重映射，所有证据
  仍指向原物理页；
- 相同输入 hash、binding 和聚合算法版本必须产生相同 canonical bytes 与 SHA-256；
- raw/provider/单段 normalized CCEF 永远不修改。聚合失败时不推进 document head；
- 聚合修订保存其有序分段 run ID、每段 normalized hash、前驱聚合 hash 与算法版本，使结果
  可以完全离线重建和审计。

这不是把两个 run 在前端“视觉拼接”。审核、后续续接和最终发布都消费精确的聚合修订。

### 4. 审核身份从单 run 提升为聚合文档修订

ADR 0016 中“每个 extraction run 最多一个 review session”的规则继续适用于历史单段入口；
增量文档的正式审核 session 则绑定文档 ID 和创建时的精确聚合 normalized hash。追加新分段
会产生新的候选修订，不会偷偷改变已经批准或正在编辑的审核基线。

审核页的来源页 URL 以文档 ID + 物理页解析，服务端根据分段 manifest 找到唯一拥有该页的
run，并继续执行媒体类型、大小与 hash 校验。公开响应仍不得披露 provider response、raw CCEF、
CAS 路径、API key 或上下文-only 文本。

### 5. 首个真实检查点

实现先使用无版权合成 fixture 和 scripted provider。真实检查点只允许：

1. 把已验收 v12 run `4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a` 登记为页 319–323 的第一段；
2. 对同一 asset 的页 324–328 发起一个新的增量 provider 请求；
3. 生成并检查覆盖页 319–328 的聚合修订；
4. 在 Sources 中只显示一个文档条目，在审核页验证 Game 13 跨段连续、无重复公共前缀且证据
   页可定位。

未经用户在该检查点单独授权，不得调用真实 provider。真实书籍内容只保存在 gitignored 本地
工件中，不进入提交测试。

## 分步交付

1. **8D-3E1 continuation context：**纯内部严格模型和确定性合法锚点目录；
2. **8D-3E2 document persistence/API：**文档、分段、聚合修订身份以及采用既有 run/顺序追加；
3. **8D-3E3 incremental execution：**context-only 尾页、provider binding、失败恢复与单段工件；
4. **8D-3E4 deterministic composition/read：**跨段 graft、ID/证据重映射和聚合审核读取；
5. **8D-3E5 grouped UI/checkpoint：**Sources 单条目、分段详情、聚合审核页及一次页 324–328
   真实检查点。

8D-3E 已完成；后续 8D-4 review ledger 应以文档 ID + 精确聚合 hash 为审核基线，不再以单 run
身份作为新增审核数据库边界。

### 8D-3E2 持久化细化

`PdfExtractionDocument` 是唯一可变的 head 投影，固定保存 asset、当前连续页段、当前聚合
normalized CCEF hash 和乐观并发 `version`。`PdfExtractionDocumentSegment` 与
`PdfExtractionDocumentRevision` 均为不可变事实：segment 以文档内 ordinal 引用一个成功 run；
revision 以 revision number、前驱 revision、末段、聚合算法和 CAS 元数据描述一个可离线重建的
前缀。首段采用时，revision 1 直接复用该 run 的 verified normalized CCEF CAS，不复制 bytes。

追加请求与正式 segment 分离。`PdfExtractionDocumentAppend` 是不可变尝试收据，绑定请求时的
document version、前驱 revision/hash、新页段、profile、run 和 Job；运行状态继续只读取 Job。
queued/running/succeeded-but-not-composed 的尝试阻止并行下一次追加，failed/cancelled 尝试不推进
head，并允许以后用新 key 重试。增量 worker 已在 8D-3E3 安装；只有在合成工件完整提交后才原子
创建正式 segment/revision 并更新 document head。这样失败输出可保留诊断，但不会占据正式 ordinal。

公开边界在 8D-3E2 冻结为：创建文档时采用一个已成功且可完整读取的 CCEF 1.1 run；列出/读取
文档及其正式 segments/revisions/append attempts；为严格相邻页段登记一个 hash-bound append
attempt。登记只排队新的 `pdf_incremental_extraction` Job，并由独立 handler 领取，避免普通
`pdf_extraction` 路径误处理。所有写入口在 provider 调用前校验 same asset、页界、当前
version、前驱 revision/hash、active attempt 和 idempotency binding。

## 自动验收

- continuation context 对相同 normalized CCEF 和基线 hash 逐字节稳定，不修改输入；
- 非法、歧义、unvalidated、断开父链和非标准 FEN 不能成为续接锚点；合法转置路径不因 FEN
  相同而合并；
- 不连续、重叠、跨 asset、错误前驱 hash、重复 ordinal 和 stale version 在 provider 调用前拒绝；
- scripted provider 只能引用 context 中存在的锚点，且新 package 的全部 EvidenceRef 都在新页段；
- 两段合并后主谱和局部分支接到指定父节点，reading flow、原子注释和全部来源证据保持；
- 相同 append 重放不重复调用 provider、不重复分段、不改变聚合 hash；失败或取消不推进 head；
- 历史单 run 审核 URL 继续可读；文档页图路由只能读取其已登记分段覆盖的物理页；
- 测试不读取用户棋书、不访问网络、不消耗 DeepSeek 额度，生产代码不包含书名、真实页码、
  具体棋步、节点数量或 hash 特判。

## 后果

- ✅ 长章节可以按可控语义块顺序提取，失败成本和重试范围保持有界；
- ✅ 已完成分段可复用，用户在网站中看到一个持续增长的逻辑条目；
- ✅ 跨段棋谱连接是 hash-bound、FEN/棋规验证的显式决定，而不是标题或相同局面的猜测；
- ✅ CCEF 和既有 run 工件保持可移植、不可变，其他消费者可以采用自己的聚合协议；
- ⚠ 新增文档/修订身份、数据库迁移、公开 API 和审核路由，属于 Codex 负责的跨模块工作；
- ⚠ 自动语义分块、并行分段、多来源文档合并和翻译仍需后续独立设计。
