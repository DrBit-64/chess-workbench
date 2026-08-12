# ADR 0012：PDF 原始资产、页段识别任务与衍生工件边界

- 状态：Accepted
- 日期：2026-08-11
- 依赖：ADR 0004、0008、0009、0010

## 背景

Stage 8P 已冻结供应商无关的 CCEF 输出边界，但尚不存在可信 PDF 上传、页段请求或识别任务
持久化。现有通用 `POST /api/source-files` 只登记客户端提交的路径、MIME、大小和哈希，不能用作
二进制上传安全边界；PGN 导入已有一套原子内容寻址写入，但实现私有在 PGN service 内。

8A 必须先建立可复用的原始资产和任务所有权，随后 8B 渲染/OCR、8C 模型调用和 8D 人工发布
才能在不改写来源身份、不把临时状态混入正式 Knowledge 的前提下逐层接入。

## 决定

### 1. 三种身份严格分离

- `PdfAsset` 表示由原始 PDF bytes 决定的全局资产身份，`content_sha256` 全局唯一，并一对一
  引用 `Source(kind="book") → SourceVersion → SourceFile`。
- `ExtractionRun` 是一次不可变的页段识别请求收据，引用 `PdfAsset`，保存 1-based、两端包含的
  `first_page`/`last_page`、pipeline version、逻辑指纹和唯一 `Job`。它不复制 Job 的运行状态。
- `ExtractionArtifact` 是某次 run 产生的不可变衍生工件索引；原始 provider 响应、raw CCEF、
  locally-normalized CCEF、渲染/OCR manifest 分别存放，绝不互相覆盖。

`package_id`、CCEF `source_ref` 和任何 provider ID 都不能直接充当上述 SQL 主键。
正式 Course/Knowledge 发布收据属于 8D；`ExtractionRun` 只证明“请求过什么”，不证明内容已审核。

### 2. 原始与衍生文件使用同一 CAS 原语、不同命名空间

唯一通用写入原语负责计算 SHA-256、生成服务端路径、同目录临时写入、flush/fsync、0600 权限、
size/hash 复核和原子 rename。调用方不能提供相对路径。

固定布局为：

```text
sources/pgn/<sha256[0:2]>/<sha256>.pgn
sources/pdf/<sha256[0:2]>/<sha256>.pdf
derived/extraction/<sha256[0:2]>/<sha256>.<controlled-suffix>
```

namespace 和 suffix 来自代码内白名单；filename、标题、页码、provider 字段均不参与路径。已存在
blob 必须重新核对大小和哈希；不一致时返回 `source_storage_unavailable`，不得覆盖或“修复”。
CAS 成功、SQL 失败可以留下未引用 blob，后续安全 GC 只能删除经数据库证明未引用的工件。

### 3. PDF 验证与资源限制

- 上传入口只接受恰好一个 multipart `file`；可选 metadata 是严格 JSON 对象。
- 显示 filename 必须是单一 basename、以 `.pdf` 结尾且不含 NUL、控制字符、`/` 或 `\\`；
  filename 永远不参与磁盘路径。
- 声明 MIME 只能为空或 `application/pdf`，但它不是真实性依据。服务端必须检查 PDF signature，
  再由 pinned parser adapter 打开完整 bytes、拒绝加密/损坏/零页文档并取得物理页数。
- 页码使用 PDF 文件的物理页序号，从 1 开始；例如用户选择 `319–399` 就持久化这两个整数，
  不把印刷页码标签当成坐标。
- 默认 PDF 上限为 256 MiB，可由 `CHESS_WORKBENCH_PDF_MAX_BYTES` 下调或上调；当前约 16–75 MiB
  的五本本地测试书均在默认值内。请求体上限必须包含有限 multipart 开销。
- 不解压归档、不从 URL 抓取、不执行 PDF 内嵌脚本/附件，也不把解析器异常、绝对路径或 bytes
  写入错误响应。

8A 允许 Sanic multipart 在单用户本地进程中有界地缓冲请求；若未来需要超大文件，必须另写
streaming ADR，不能悄悄移除大小上限。

#### 3.1 解析器许可修订

8A inspection 使用 BSD-3-Clause 的 `pypdf`，不直接引入 AGPL/商业双许可的 PyMuPDF。原因是
识别模块明确需要能接到其他网站，而当前仓库没有许可证；把 AGPL 实现写死为生产依赖会提前
限制未来部署方式。inspection 仍放在可替换 adapter 边界内。

8B 页面渲染继续通过独立 adapter 交付：可以选择宽松许可的 PDFium 实现，或在项目许可证和
部署方式明确后显式选择 PyMuPDF/商业许可。不得因为本修订降低 signature、加密、损坏、页数
或物理页码验证标准。

### 4. 上传和页段 API

8A 新增以下边界：

```http
POST /api/pdf-assets
GET  /api/pdf-assets
GET  /api/pdf-assets/{asset_id}
POST /api/pdf-extractions
GET  /api/pdf-extractions/{run_id}
GET  /api/pdf-extractions?status=&has_conflicts=
```

资产列表端点是 Sources 页面在刷新后恢复已上传 PDF 选择所必需的只读索引；否则尚未创建 run 的
资产只能通过一次性的上传响应访问。列表只返回 `PdfAssetRead`，仍不暴露 CAS 路径。

上传 metadata 可含 `title`、`author`、`edition`；title 缺省为安全 basename。首次新资产返回
`201`，相同 bytes 重放返回原 `PdfAsset`/Source/File 和 `200`。后来的不同显示 metadata 不会
克隆资产或静默改写原记录；用户可走既有 Source 乐观锁编辑显示信息。

创建 extraction 接受 `pdf_asset_id`、`first_page`、`last_page`。页段必须在 `1..page_count`
且 `first_page <= last_page`。显式 `Idempotency-Key` 为 1..128 visible ASCII，只保存其 SHA-256；
没有 header 时使用逻辑指纹。相同 key+相同请求返回原 run/job，不同请求返回
`409 idempotency_conflict` 且零新增 SQL 行。

逻辑指纹为以下规范 JSON 的 SHA-256：asset content hash、页段、pipeline version 和影响输出的
识别 profile。UI 可显示 Job 状态并按状态筛选；`has_conflicts` 在 8C 尚未产出候选前恒为 false，
但查询和控件在 8A 即固定，8C 只补充其数据来源。

### 5. SQL 与事务所有权

新增表使用 UUID、UTC、RESTRICT 外键和数据库约束：

- `pdf_assets(content_sha256, byte_size, page_count, source_id, source_version_id,
  source_file_id)`，hash 和三个来源引用分别唯一；
- `extraction_runs(pdf_asset_id, first_page, last_page, pipeline_version, logical_fingerprint,
  effective_key_hash, job_id)`；有效 key hash 和 job_id 分别唯一，逻辑指纹只建立查询索引；
- `extraction_artifacts(run_id, kind, page_number?, relative_path, media_type, byte_size,
  content_sha256)`，受控 kind，页号若存在必须在 run 范围内由 service 校验。8B 实现后允许不同
  索引行引用同一个内容寻址 relative path/hash（相同空白页 PNG 等情况会自然发生）；逻辑
  `(run, kind, page)` 唯一性和 metadata/hash 一致性由锁定 run 行的注册 service 原子保证。

顺序固定为：事务外完成 bounded PDF 验证并落 CAS；单一 SQL 事务内先 replay/conflict，再创建或
复用 PdfAsset 来源链，最后原子创建 ExtractionRun 与 Job。数据库永不引用缺失文件；任务也
永不指向未提交的 run。

逻辑指纹不设唯一约束：无显式 key 时它本身就是 effective key，因此自动重放；两个不同的显式
key 即使请求内容相同也可以各自绑定一条 run/Job，确保每个用户 key 都能永久检测后续 payload
冲突。这与 ADR 0008 PGN receipt 语义一致，避免“第二个 key 返回第一条 run 却未被实际绑定”。

### 6. Job 是唯一运行状态，worker 只能 claim 已注册 kind

`Job.status` 继续是 queued/running/succeeded/failed/cancelled 的唯一运行状态。不得在
`ExtractionRun` 再维护一份易漂移的副本。worker claim 必须显式限定自身 handlers 的 kind；
Engine worker 不能领取尚未安装 handler 的 PDF job，未来 extraction worker 也不能领取 engine
job。8A 可以安全创建等待 8B handler 的 `pdf_extraction` job，不会被 engine worker误判为失败。

8B 安装 extraction handler 后负责渲染/OCR并写衍生 artifacts；8C 继续同一 run 的 provider、
decoder 和 chess validation；8D 读取不可变 artifacts 进入人工审核/发布。失败重试复用同一 run，
不能新建正式知识或覆盖成功工件。

### 7. Sources 页面

Sources 一级页增加 PDF 上传区、物理页数、页段选择、创建任务、Job 状态和状态/冲突筛选。
页面只轮询或通过既有 invalidation 通知刷新 SQL API；不读取磁盘路径，不在浏览器调用 AI/OCR，
也不伪造进度百分比。8A 只显示真实状态；8B/8C 增加工件与候选摘要时扩展同一 run 卡片。

## 分步交付

1. **8A-1**：提取并验证通用 CAS 原语，PGN 行为保持逐字节兼容。
2. **8A-2**：PDF inspection、PdfAsset/ExtractionRun/Artifact models、migration 和 service。
3. **8A-3**：上传/页段 API、按 handler kind claim 的 worker 隔离和 OpenAPI 类型。
4. **8A-4**：Sources 页面、focused UI tests 和 `acceptance-stage-8a` 累积门禁。

## 自动验收

- 相同 PDF bytes 经重复上传只产生一个 blob、PdfAsset、Source、Version 和 File；不同页段产生
  不同 run，相同页段重放同一 run/job。
- `.pdf` 伪装内容、真实 PDF 错误 MIME、超限、加密、损坏、零页、路径穿越和越界/逆序页段均
  返回稳定错误且零 SQL 引用。
- CAS fault、SQL fault 和同 key 冲突各自证明数据库不引用缺失/错误 hash 文件，正式 Knowledge
  表保持不变。
- engine worker 面前同时排队 engine/PDF job 时只领取 engine；未来 PDF worker只领取 PDF。
- Sources UI 能上传 fixture、选择 `319–399` 形式页段、看到真实 job 状态并跳回该 source；测试
  使用小于 2 MiB 的确定性合成 PDF，不提交用户书籍。
- 8A focused formatter、lint、typecheck、SQLite API/service tests、OpenAPI drift 和前端组件测试
  全绿；MySQL 与完整覆盖率门禁在 8A 收尾执行一次。

## 后果

- 原始来源 bytes、衍生识别工件和正式知识不再共享路径或生命周期。
- Stage 8 的任务可以重试、复现和审核，而不会改变 Source 身份或绕过人工发布。
- BSD-3-Clause `pypdf` 在 8A-2 进入锁文件；渲染实现与 OCRmyPDF/PaddleOCR 仍留到 8B 的
  adapter/工具清单，并单独复核许可证。
- 现有 `POST /api/source-files` 保留给内部/既有手工元数据流程，但不能作为 PDF 上传入口。
