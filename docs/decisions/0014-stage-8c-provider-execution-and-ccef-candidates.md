# ADR 0014：整章模型识别、可信 CCEF 装配与候选工件

- 状态：Accepted
- 日期：2026-08-11
- 依赖：ADR 0010、0012、0013

## 背景

Stage 8B 已把一个物理页段变成不可变页面 PNG、逐页文本证据与两份 manifest。Stage 8C 必须
调用可替换的结构化生成 provider，把这些证据转成 CCEF 候选，再由本地 decoder 和
python-chess 验证。用户的首个真实目标是一次处理一本开局书的完整章节（PDF 物理页
319–399），所以实现必须保留跨页正文、棋谱和锚点，而不是把每页当作互不相关的文档。

当前 `pdf_extraction:v1` Job 在 8B evidence 提交后即成功。已成功 Job 不可安全地重新进入运行态，
而一条 run 也不能拥有第二套生命周期真相。DeepSeek V4 Flash 的官方 API 当前是纯文本输入；
页面 PNG 不能直接交给它进行棋盘识别。

## 决定

### 1. 新任务使用完整流水线 v2，历史 v1 永久只读

Stage 8C 启用时，新建 run 的 `pipeline_version` 升为 `pdf-extraction:v2`。其唯一
`pdf_extraction` Job 依次完成：

```text
verified PDF -> 8B evidence -> provider -> raw CCEF -> local binding/chess validation
```

只有三类 CCEF 工件全部原子登记后 Job 才成功。已有 v1 run/Job/artifact 不重排、不重跑、不伪造
8C 状态；无显式 idempotency key 的同一页段因 pipeline version 进入逻辑指纹而自然创建 v2 run。
显式 key 仍遵循永久绑定规则，不能偷偷改绑到 v2。

### 2. 初版按完整页段调用一次，不自动语义分包

一个 run 是一个完整章节级 CCEF package。输入严格按物理页、页内 fragment order 排列，包含空页
占位；模型看到的是 8B 规范化文本、bbox、置信度、origin 和 fragment hash。默认一次调用整个
请求页段，以保留跨页棋谱、标题层级和 prose anchor。

自动把章节切成多个独立 CCEF package 会产生无法确定合并的重复标题、跨窗棋步树和锚点，因此
8C v1 禁止静默分包或重叠窗口。输入超过 200,000 fragments、1,500,000 code points 或配置的
prompt 上限时以稳定 `ccef_input_too_large` 失败，UI 要求用户缩小页段。未来如需超大材料，必须先
另立 ADR，定义两阶段抽取/合并协议和确定性跨包 ID 映射。

### 3. DeepSeek 是纯文本 provider，图像不得被猜测

默认 provider 是非思考模式 `deepseek-v4-flash`。官方当前声明其输入为 text，尽管支持 1M context、
最高 384K output 和 JSON Output。因此 Stage 8C 初版不扩展多模态 provider 端口，也不把 PNG
base64 伪装成文本。

页面 PNG 继续作为 8D 人工审核证据。只有文本证据支持的 heading/prose/moves 可以由 DeepSeek
结构化；无法由文本确定的棋盘图必须产出 `figure` 未解析候选或 `unresolved`/warning，绝不能猜
FEN。未来视觉模型通过新的 capability/adapter 加入，不改变 CCEF 输出协议。

### 4. Prompt 是版本化、确定性且抗来源指令注入的

prompt version 当前为 `chess-workbench/ccef-prompt/1.3`（1.1 明确连续棋步的 parent 链和同父
sibling_order；1.2 禁止跨页拆线和从着法猜测 FEN；1.3 在证据没有明确六字段 FEN 时从本次响应
Schema 中移除 FEN initial position）。纯 `extraction` 模块接收调用者给出的
package/source/provenance 固定值和有序 evidence pages，输出一个
`StructuredGenerationRequest`：

- system message 明确来源文本只是数据，禁止执行其中的指令；禁止补写未见内容；不确定内容必须
  保留为 unresolved/warning；provider 只能输出 `unvalidated` move nodes；
- user message 是 deterministic compact/sorted UTF-8 JSON evidence envelope，包含精确 CCEF
  package skeleton metadata；
- response schema 直接使用冻结的 CCEF v1 JSON Schema；schema name 固定；
- accepted input不裁剪原文、不重排 fragments、不根据内容选择性丢弃；同一输入逐字节生成同一
  request。

输入中的 Markdown、HTML、`ignore previous instructions`、JSON 片段等都只是 JSON string 数据。
不得把 source text 拼接进 system message或当成新 message role。

### 5. 模型不能声明可信来源、时间或棋规结果

请求为模型提供固定 `package_id`、`source_ref`、媒体类型、语言、页段、run created_at 和 adapter
版本。decoder 先执行现有严格 JSON/CCEF/引用检查，并拒绝 provider 自报 valid/invalid/ambiguous
或 SAN/UCI/FEN。

随后本地 binder 必须验证输出 source、package_id、created_at 和固定 adapter 字段与请求完全一致；
不一致即拒绝，不静默改写。provider/model、规范 request hash 和原始 response content hash 只能由
本地代码填写。最后 `normalize_chess_moves` 产生权威棋规字段。provider 原始 JSON、canonical raw
CCEF 和 canonical normalized CCEF 分开保存，三者互不覆盖。

### 6. 工件、哈希与事务顺序

每个 v2 run 在既有 `ExtractionArtifact` kind 中登记三个 run 级 slot（`page_number=NULL`）：

1. `provider_response`：规范 wrapper，保存 exact assistant content、provider/model、finish reason、
   token usage 和 request/response SHA-256；不得保存 API key、Authorization header 或私有 HTTP body；
2. `raw_ccef`：decoder 接受后的 canonical CCEF，棋步仍是 unvalidated；
3. `normalized_ccef`：可信绑定且经 python-chess 规范化的 canonical CCEF。

调用前验证并读取 committed 8B manifest/逐页 evidence；不通过目录扫描。三份 bytes 先写 CAS，再在
锁定 run 的一个短事务中按逻辑 slot 原子登记。完全相同重放；任一 slot metadata/hash 不同则
`artifact_conflict`，绝不覆盖。崩溃可留下未引用 CAS blob，不能留下部分 SQL rows。

### 7. Provider 配置、失败与重试

API key 只能来自 server-owned、仓库外部的 secret file，配置中只保留文件路径；内联环境变量和
`.env` 明文 key 被拒绝。POSIX 上 secret file 必须是普通文件且不能向 group/other 开放权限。key
不能出现在 Job profile、SQL、artifact、日志、错误或 `repr`。未配置 key 时核心应用和 8B/v1 数据
仍可用；新的 v2 AI Job 以明确非重试
`provider_unconfigured` 失败。

provider 的 authentication/invalid_request/invalid_response、binding/输入超限错误为非重试；
rate_limited/timeout/unavailable 为重试。真实 V4 Flash 验证表明同一请求可能偶发产生非法 JSON 或
不符合 CCEF 的 JSON，因此 decoder 的 `invalid_json`/`invalid_package` 也使用 Job 既有的最多三次
有界重试；其他 decoder 安全错误仍立即终止。Job failure API 在 8C 增加显式 retryable 决策，避免
让确定性失败白白消耗额度。每次真正调用都保留独立内部尝试计数，但只有最终接受的响应
成为 run artifact；PR 测试只用 scripted provider 和 recorded HTTP fixture，绝不请求真实 API。

取消和 worker shutdown 沿用既有语义：长 provider await 期间 heartbeat；用户取消会取消 HTTP
调用并且不登记任何 CCEF artifacts；shutdown 留 lease 供恢复。

### 8. API/UI 候选摘要

成功 v2 Job result 使用版本化嵌套摘要，分别包含 evidence 与 CCEF manifest/hash/counts；API 只在
对应 committed slots 与 result 匹配时公开 typed candidate summary。`has_conflicts` 为以下任一项：

- unresolved item；
- error diagnostic；
- invalid/ambiguous move node；
- 本地 binding/棋规 warning 要求人工处理。

warning 不阻止 Stage 8C 保存候选，但任何候选都不能直接写 Course/Knowledge/SourceSpan。Stage 8D
审核页和发布事务仍是唯一正式入口。

## 分步交付

1. **8C-1**：纯 evidence-page/prompt contract 与确定性 request builder；
2. **8C-2**：可信 metadata binder、canonical raw/normalized CCEF codec 与冲突摘要；
3. **8C-3**：v2 handler、provider配置、三工件 CAS/原子登记和 retryable Job policy；
4. **8C-4**：typed API/Sources candidate summary、recorded DeepSeek等价性与 focused
   `acceptance-stage-8c`。

## 自动验收

- 81 页有序 synthetic evidence 在上限内生成一次 request；不会按页调用 provider；
- source 中的 prompt injection 文本逐字保留为 JSON 数据，不能改变 system instruction；
- 页面断档、重复页、fragment order 断档、页/fragment 不一致、超字符/fragment/prompt 上限均在
  provider 调用前失败；
- scripted provider 合法/截断/非法 JSON/非法 CCEF/伪造 valid/来源不匹配分别得到稳定结果；
- 本地 normalization 对合法、非法、歧义和断裂变化保留可审核状态；
- retryable provider 失败及偶发 invalid JSON/package 可有界重试；authentication/config/binding
  错误立即终止且不重复计费；
- 相同 accepted response 重放得到相同三工件 hash，冲突不覆盖，取消/失败零 CCEF artifact rows；
- API 只从完整 committed artifacts 返回摘要，UI 不伪造进度或候选；
- 测试不读取用户书籍、不调用网络、不消耗 DeepSeek 额度。

## 真实联调观察（2026-08-13）

物理页 319–323 的真实运行证明“一页一个请求”不是当前实现，也不是后续目标：五页证据已作为一个
连续请求发送，因此模型能够看到跨页标题、正文和棋谱。修复 PDFium 字符级碎片后，输入从 4,914
个碎片/约 688,804 tokens 降到 110 个行级碎片/22,379 tokens；prompt 1.3 和有界格式重试使该任务
在第二次尝试成功，并提交完整候选工件。

同时，单次严格生成仍输出 93,400 tokens、16 条大量重复前缀的路线和 362 个棋步节点，本地棋规
校验发现 36 个错误连接的分支。由此可见，更长上下文有利于语义连续性，但把 81 页整章直接扩成
一个更大的生成请求会放大延迟、费用、截断和整包重试风险。下一版不应机械逐页，也不应无限扩大
单包；应先识别章节/小节/完整棋谱边界，以约 5–15 页的语义块独立抽取和校验，再执行章节级合并、
去重和跨块锚点绑定。该方案会取代本 ADR 第 2 节的初版 whole-range 决定，实施前必须另立 ADR，
冻结块 ID、重叠上下文、失败恢复、合并冲突和证据归属规则。

## 参考

- DeepSeek Models & Pricing（2026-08-11 查阅）：V4 Flash 1M context、384K max output、text input
- DeepSeek JSON Output guide：JSON Object 仍需 prompt 明确 JSON，可能出现空 content，decoder 必须
  保持严格
- ADR 0010：CCEF/Provider/Consumer 解耦
- ADR 0013：8B evidence manifest 与 artifact 原子性
