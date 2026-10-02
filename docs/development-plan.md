# ChessWorkbench current roadmap

As of 2026-10-01, the operator accepted v8 PDF extraction, v9 incremental extraction, review and publication for personal use. Extraction is maintained from concrete failed tasks. The broad R5/P6 six-book evaluation and unfinished multi-source Stage 8 work are deferred. Historical task packets, acceptance matrices and the original roadmap are preserved in archive/2026-10-01-before-cleanup/development-plan-historical.md.

## Current capabilities

- Local position graph, PGN import/export, course editing and learning.
- Local engine analysis, tablebase integration points and playable analysis positions.
- PDF source library; independent v8 and incremental v9 extraction; source-linked review, manual corrections, recovery and course publication.
- Older extraction results, review histories and published material remain readable.

The personal repertoire, practice/FSRS and Lichess game sections are not implemented. The operator may use Chessbook.com for the move tree. The workbench's more useful potential contribution is study notes around critical positions, pawn structures, plans and move-order conditions. No feature in that direction is yet scheduled.

## Candidate next work

1. A recoverable local backup of the SQLite database and source files, verified by opening an existing course and review from a copy.
2. A small study workflow that lets the user save plans, critical positions and source explanations from a course, with explicit source links.
3. A small practice loop only after the user has enough study material to identify what needs repetition.
4. Lichess game review, video import and multi-source conflict handling only if actual use calls for them.
5. Deployment and collaboration remain optional, not prerequisites for a single-user local website.

These are candidate directions, not an obligation to build the entire original plan. Preserve the Source → Knowledge → Repertoire → Exercise boundary, legal persisted moves and human approval of AI extraction.

## Verification while developing

Use focused backend tests and frontend tests for changed behavior. Run the matching formatter, lint and type checks. The local Makefile still provides full backend/frontend checks, contract drift checks and smoke tests when a change warrants them. Historical cumulative Stage acceptance and GitHub Actions CI have been retired.

The dated PDF evidence, protocol and implementation reports remain under agent/. Current extraction boundaries are documented in architecture/pdf-extraction-current.md and decisions/0022-source-first-pdf-extraction-redesign.md. Historical project scope is preserved at archive/2026-10-01-before-cleanup/chess-workbench-project-description-historical.md.

## 2026-10-02：课程 → Lichess 研讨

按用户新需求增加课程小节／大章节的单向研讨发布。前端预览展平目录，后端复用 PGN 导出后调用官方创建／导入接口；一次性配置 study:write 令牌文件。不是旧路线图里的 Lichess 实战导入、同步或训练闭环。具体约束见 [ADR 0024](decisions/0024-lichess-study-export.md)。
