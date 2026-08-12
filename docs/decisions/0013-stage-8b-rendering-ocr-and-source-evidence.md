# ADR 0013：PDF 页面渲染、OCR 与来源证据候选

- 状态：Accepted
- 日期：2026-08-11
- 依赖：ADR 0004、0009、0010、0012

## 背景

Stage 8A 已能可信地保存原始 PDF、创建物理页段 `ExtractionRun` 和排队
`pdf_extraction` Job，但 worker 尚未处理这种 Job。Stage 8B 必须把所选物理页稳定地转成
可供 Stage 8C 模型识别的页面图和文本证据，同时满足以下边界：

- 数字 PDF 应优先保留嵌入文本，扫描 PDF 才调用昂贵 OCR；
- 页面、bbox、文本、置信度和内容哈希必须可追溯，不能提前降格为正式 `SourceSpan`；
- OCR/渲染实现可以替换，不能把 PaddleOCR、云服务或某个网站领域模型写入核心契约；
- 精简 CI 没有 OCR 模型、GPU 或云 key，仍必须确定性验收；
- 任何衍生结果仍是未审核证据，不能创建 Course、KnowledgeNote 或正式引用。

## 决定

### 1. 8B 只产出不可变证据，不产出正式知识

8B 为每个 run 产出三类已有 `ExtractionArtifact`：

1. 每页一个 `rendered_page` PNG；
2. 每页一个 `ocr_fragment` JSON，内容是该页有序的文本片段；
3. run 级唯一的 `render_manifest` 与 `ocr_manifest` JSON。

名称 `ocr_fragment` 是 8A 已冻结的工件 kind；其中的 `origin` 明确区分
`embedded_text` 与 `ocr`，因此数字 PDF 的嵌入文本不会被伪装成 OCR 结果。Stage 8C 只读取
manifest 中列出的工件，不通过目录扫描发现输入。

这些 JSON 中的片段同时是 `SourceSpanCandidate`：保存物理页、归一化 bbox、原文、来源方式、
置信度和 `fragment_sha256`。8B 不创建 `source_spans` 行，因为现有正式表不能同时无损保存
page+bbox、文本 offset 和 fragment hash；8D 审核/发布时再把可表达部分物化为 `SourceSpan`，并在
不可变审核收据中保留完整候选。

### 2. 内部可移植工件契约

所有 manifest 使用严格、版本化、未知字段拒绝的 JSON：

- `artifact_schema = "chess-workbench/pdf-evidence/1.0"`；
- `run_id`、`pdf_asset_id`、PDF 内容 SHA-256、请求页段和 rendering/OCR profile；
- 页面编号始终是 1-based 的 PDF 物理页；
- bbox 固定为 `[x0, y0, x1, y1]`，坐标归一化到页面左上原点的 `[0,1]`，且
  `x0 < x1`、`y0 < y1`；整页回退框是 `[0,0,1,1]`；
- 片段按阅读器或 OCR adapter 给出的稳定顺序编号，空白文本拒绝，文本逐字保留；
- confidence 是有限 `0..1`；嵌入文本使用 `null`，不得伪造 `1.0`；
- `fragment_sha256` 对规范 JSON
  `(physical_page, bbox, text, origin, engine_name, engine_version)` 计算；
- manifest 记录每个子工件的 hash、media type、尺寸/像素和相对页码，但不含绝对路径。

JSON 以 UTF-8、sorted keys、紧凑分隔符和末尾换行写入 CAS。相同 PDF、页段、profile 和已固定
工具版本必须生成逐字节相同的 manifest；工具版本或影响输出的参数变化必须进入 extraction
profile，从而得到新的 run，不能覆盖旧工件。

### 3. 渲染端口与默认实现

核心端口接收 PDF bytes、一个已验证的物理页码和显式 render profile，返回：PNG bytes、
width/height、DPI，以及可选的嵌入文本片段。它不接收任意路径，不写 SQL/CAS，也不知道 Job。

默认实现使用固定版本的 `pypdfium2`/PDFium，而不是把 AGPL/商业双许可的 PyMuPDF 写死为依赖。
`pypdfium2` 本身为 Apache-2.0/BSD-3-Clause，PDFium 为 BSD-style；发布二进制时仍须携带 wheel
中的第三方许可证。Pillow 只负责将内存 bitmap 编码为确定性 PNG。

默认 profile：150 DPI、白色背景、RGB PNG、无时间/路径 metadata。单页最大边长 10,000 px、
最大 40,000,000 pixels、PNG 最大 64 MiB；在编码或分配前检查。只打开 8A 已验证的原始 bytes，
页码越界、PDFium 错误、像素上限或输出上限映射为稳定的 `PdfEvidenceError`，不得暴露 bytes、
绝对路径或底层异常文本。

### 4. 文本层优先与 OCR 决策

渲染器同时尝试 PDFium 文本页，输出其可确定的文本与 bbox。页面去除 Unicode 空白后达到
profile 的 `embedded_text_min_chars`（默认 32）时，使用 `embedded_text` 片段并跳过 OCR；否则
把 PNG 交给 OCR adapter。决策逐页进行，因此混合型 PDF 可以一部分走文本层、一部分走 OCR。

不得把整本书或任意未选择页面送入 OCR。不得为达到阈值拼接相邻页。空白页允许产出零片段，
并在 manifest 中记录 `empty_page` warning，留给 8C/8D 审核。

### 5. OCR 端口、PaddleOCR 和测试替身

OCR 端口只接收一张 PNG、像素尺寸、物理页码和显式语言/profile，返回有序文本、像素 bbox、
有限置信度及 engine name/version。端口不接触 PDF、SQL、CAS、网络或消费者模型。

Stage 8B 提供：

- `ScriptedOcrAdapter`：FIFO 深拷贝测试替身，精简 CI 的唯一自动调用实现；
- `PaddleOcrJsonAdapter`：把固定的 PaddleOCR 3.x `rec_texts`、`rec_scores`、`rec_polys` JSON
  规范化到内部端口。模型进程可运行在受支持的独立 Python 环境，通过本地受控 runner 产生
  JSON；主后端不导入 PaddlePaddle，也不启动 HTTP 微服务；
- 未配置 runner 时返回稳定 `ocr_unavailable`，而不是静默生成空文本或调用云端。

PaddleOCR 模型名、版本、语言、device 和 runner protocol version 必须写入 profile/manifest。
生产工具下载属于显式安装命令；测试不自动下载模型。OCRmyPDF 可作为以后新增的 adapter，但
仅有 sidecar 纯文本不足以无损生成 bbox，因此不是 8B 默认实现。

### 6. Job handler、CAS 与事务顺序

`pdf_extraction` handler 使用短事务和现有 handler-kind 隔离：

1. 短只读事务加载 run、asset、source file 和已有 artifacts；严格校验 Job payload 与 run；
2. 在事务外安全解析 server-owned relative path，确认位于 storage root 内，并重新核对 PDF
   size/hash；
3. 逐页渲染、按策略提取/OCR，将页面和规范 JSON 写入 `derived/extraction` CAS；
4. 单一短事务注册全部 `ExtractionArtifact` 并提交；
5. 返回只含 run id、manifest hashes、page/fragment/warning counts 的 Job result。

数据库写入前所有被引用 blob 必须已存在且 hash/size 匹配。崩溃可以留下未引用 CAS blob，但
不能留下部分 artifact rows。重试遇到完全相同的工件集合时 replay；同一 run/kind/page 已绑定
不同 hash 时以 `artifact_conflict` 失败，不覆盖。`render_manifest`/`ocr_manifest` 每 run 逻辑唯一，
每页 `rendered_page`/`ocr_fragment` 逻辑唯一。

CAS blob 可以被多个 artifact index 引用：同一 run 的两个空白页可能产生相同 PNG，不同显式
idempotency key 的 run 也可能得到相同衍生 bytes。因此 `relative_path` 和
`(run_id, kind, content_sha256)` 不能作为 SQL 唯一键。注册事务先锁定 `ExtractionRun`，再按逻辑
slot `(kind, page_number)` 比较完整 path/hash/size/media type；完全相同则 replay，任何差异均冲突。
迁移 0011 移除 8A 提前设置的两个不正确唯一约束。

本地 API 进程启用既有 worker 开关时显式注册 `pdf_extraction` handler；Stockfish 是否存在只决定
是否同时注册 `engine_analysis`，不再阻止纯 PDF evidence Job 被领取。生产 OCR runner 只能来自
server-owned `paddle_ocr_runner_path` 设置，Job profile 永远不能提供可执行 argv。

处理器每页之间检查取消；`SqlWorker` 继续负责 lease heartbeat 和最终 Job 状态。运行期异常使用
稳定 error code；用户取消/worker shutdown 的既有语义不变。

### 7. 安全与资源边界

- 只读取数据库绑定的 `SourceFile.relative_path`，经 `resolve()` 后必须仍位于 storage root；
- 不执行 PDF 内脚本、附件、链接或字体程序，不把页面文本当 HTML/Markdown 渲染；
- adapter 输出先经过严格模型和数量/长度上限，再写 CAS；
- 每页最多 20,000 fragments，单片段最多 100,000 code points，run 总片段最多 200,000；
- subprocess runner 使用 argv（无 shell）、固定超时、受控临时目录和有界 stdout/stderr；
- 日志和公共错误不得包含 OCR 原文、原始 bytes、密钥、绝对路径或底层 parser stderr。

## 分步交付

1. **8B-1**：严格 evidence contracts、render/OCR ports、错误模型与 scripted fake；
2. **8B-2**：PDFium renderer、文本层提取、确定性三页合成 PDF 和资源上限测试；
3. **8B-3**：PaddleOCR recorded-JSON normalizer 与受控 runner adapter；
4. **8B-4**：artifact CAS/注册 service、`pdf_extraction` handler、取消/重试/冲突测试；
5. **8B-5**：run API 增加真实 evidence summary、Sources 状态展示与 `acceptance-stage-8b`。

## 自动验收

- 三页合成 PDF（文本页、扫描页、空白页）只处理所选物理页，PNG 尺寸/hash 和 manifest
  byte-for-byte 稳定；
- 文本页不调用 OCR，扫描页恰好调用一次 scripted OCR，空白结果产生 warning；
- bbox 归一化、页码、顺序、confidence、hash 和未知字段有正反例；
- 超像素、超 PNG、超片段、越界页、损坏 CAS、路径逃逸、runner timeout/invalid JSON 均以稳定
  code 失败，零 artifact SQL 行且不泄露底层内容；
- retry 复用相同 CAS/artifacts，冲突不覆盖；engine worker 不领取 PDF job，PDF worker 不领取
  engine job；
- 成功 Job 的 result 与 GET summary 来自已提交 artifacts，不伪造进度；
- 测试不读取 `data/books`、不下载模型、不调用网络/云 provider，也不要求 PaddlePaddle。

## 参考

- pypdfium2 文档：https://pypdfium2.readthedocs.io/en/stable/readme.html
- PaddleOCR 3.x OCR 文档：https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/OCR.html
- ADR 0012：原始 PDF、ExtractionRun、Job 与衍生工件所有权
- ADR 0010 / `docs/architecture/ccef-v1.md`：Stage 8C 的供应商无关输出边界
