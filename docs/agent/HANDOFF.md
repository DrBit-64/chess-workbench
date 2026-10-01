# Current agent handoff

2026-10-01. The operator accepted independent v8 and incremental v9 PDF extraction for personal use. Future extraction work should start from a concrete saved failure. R5/P6 broad six-book evaluation, incomplete multi-source scope and Chinese endgame book remain deferred.

## README and Git privacy review (2026-10-01)

- README now focuses on installation and running the site: required runtimes, two-terminal startup, optional Stockfish/model setup, data backup/update, remote access through SSH, and startup troubleshooting. Removed developer verification commands from the README.
- Documented actual limits: the Stockfish installer downloads Linux x64 only; scanned text needs a separately supplied OCR runner; no login/access isolation or one-command production deployment is provided.
- Checked tracked working files plus pending archive additions and all 32 locally reachable Git commits: 411 text files and 1,019 historical text blobs at the time of the scan. The two binary fixtures are Syzygy tables. No apparent real API credential/private key was found; matches were synthetic test credentials and examples. Runtime PDF/database/key files are absent from reachable tracked history; .env.example is a template.
- Privacy findings remain: Git author/committer metadata contains a personal QQ email address; historical PDF reports and archived handoffs contain account balances, spending/authorization details and task/source identifiers. Moving those documents into an archive does not make them private. No identity values were copied into this handoff, and no Git history was rewritten.
- Validation: checked setup instructions against Makefile/settings/installers, Make dry-run, README relative links, shell block syntax and git diff --check. No application code changes, dependency install, service startup or paid API call for this documentation task.

## Current repository cleanup

- GitHub Actions workflow and cumulative Stage acceptance targets were removed at the operator's request. Local Make targets for backend/frontend checks, contracts and smoke remain.
- The browser and PDF extraction POST now create v8 source-relation runs only. A legacy flag is rejected at the API schema boundary. Older extraction runs remain readable.
- Existing v2/v3/v4 candidate generation was moved from services/pdf_extraction.py to services/pdf_legacy_extraction.py. Existing v5 incremental generation was moved from services/pdf_incremental_extraction.py to services/pdf_legacy_incremental.py. Shared evidence rendering, immutable artifacts, review, publication, old job replay and old document continuation remain available.
- Historical plans and the original project proposal were copied to docs/archive/2026-10-01-before-cleanup/. Old PDF experiment scripts and DeepCode tools are archived. The tracked temporary PDFium probe, unused topology repair module and CI-wiring test were removed.
- PLANS.md, docs/development-plan.md, README.md, AGENTS.md and the current PDF architecture note describe the active state. The dated reports under docs/agent/ remain historical evidence, not current work instructions.

## Verification recorded during this cleanup

- Backend PDF schema/API/old job: 66 passed. Incremental extraction/document: 9 passed. Historical review reads: 28 passed. Publication: 1 passed.
- Changed Python files pass Ruff lint and format. Six owning source modules pass mypy.
- OpenAPI and TypeScript types were regenerated; make check-contracts passed.
- Frontend Prettier/ESLint on changed files and production build passed. The two directly affected Sources page tests (new extraction and retrying a historical run into v8) passed.
- The entire older WorkbenchPages test file still has 17 failing assertions. At least one expects wording that did not exist in the committed Sources page before this cleanup; the remaining failures were not individually audited. This does not block the two changed interaction paths but local full frontend-check is not yet green.
- Archive copies of the old plans/project proposal match the previous Git versions byte-for-byte; all 25 moved experiment scripts match their previous tracked contents. git diff --check passed.

No full repository test suite, six-book quality evaluation or paid model run was needed for this maintenance change.

## Current product priorities

The user has little time for chess study and may use Chessbook.com for opening-tree browsing. The workbench's next likely value is source-linked study notes around critical positions, pawn breaks, plans and move-order conditions. Basic local backup is also a candidate. Training, FSRS, Lichess, video, deployment and collaboration require a fresh priority decision.

The 8,211-line former handoff is preserved at docs/archive/2026-10-01-before-cleanup/HANDOFF-historical.md. No committed user data under data/ was changed. No paid model call was made for cleanup. Do not commit without explicit instruction.
