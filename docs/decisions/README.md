# Architecture Decision Records

ADR 记录会长期影响数据兼容性、模块边界或运维方式的决定。新 ADR 使用 `NNNN-short-title.md`，包含背景、决定、后果和状态；已接受的 ADR 不静默改写，变化通过新 ADR 取代旧决定。

- [0001：从本地优先模块化单体开始](0001-local-first-modular-monolith.md)
- [0002：局面身份、完整状态与棋步规范化](0002-position-identity.md)
- [0003：异步 MySQL 驱动选择](0003-mysql-async-driver.md)
- [0004：课程语境、来源定位与生命周期](0004-course-context-and-lifecycle.md)
- [0005：双模课程：传统课程与开局探索器](0005-dual-course-mode.md)
- [0006：章节内容块格式](0006-chapter-content-block-format.md)
- [0007：来源有序课程中的 PGN 变例树](0007-source-ordered-pgn-variation-trees.md)
- [0008：PGN 语义、来源资产、幂等导入与 HTTP 边界](0008-pgn-import-export-contract.md)
- [0009：SQL 任务与本地引擎运行时](0009-sql-jobs-and-local-engine-runtime.md)
- [0010：可移植 AI 识别交换格式与双向适配边界](0010-portable-ai-extraction-contract.md)
- [0011：Codex 主控的 DeepCode 有界任务委派](0011-codex-led-deepcode-delegation.md)
- [0012：Stage 8A PDF 来源、资产与提取任务边界](0012-stage-8a-pdf-assets-and-extraction-runs.md)
- [0013：Stage 8B 页面渲染、OCR 与来源证据](0013-stage-8b-rendering-ocr-and-source-evidence.md)
- [0014：Stage 8C provider 执行与 CCEF 候选](0014-stage-8c-provider-execution-and-ccef-candidates.md)
- [0015：Stage 8C 候选棋谱确定性规范化与去重](0015-stage-8c-candidate-consolidation.md)
- [0016：Stage 8D 人工审核与草稿发布边界](0016-stage-8d-review-and-publication-boundary.md)
- [0017：带原子注释的棋谱树与独立阅读流](0017-annotated-move-tree-and-reading-flow.md)
