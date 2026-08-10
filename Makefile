SHELL := /usr/bin/env bash
.DEFAULT_GOAL := bootstrap

PROJECT_ROOT := $(CURDIR)
UV_CACHE_DIR ?= $(PROJECT_ROOT)/.cache/uv
export UV_CACHE_DIR
PNPM ?= $(shell if command -v pnpm >/dev/null 2>&1; then printf '%s' pnpm; elif command -v corepack >/dev/null 2>&1; then printf '%s' 'corepack pnpm'; fi)

# Keep the real-MySQL acceptance URL scoped to the Stage 3D recipe. CI sets this
# variable for its disposable service; local runs fall back to a disposable container.
MYSQL_ACCEPTANCE_URL ?= $(CHESS_WORKBENCH_MYSQL_URL)

STAGE_2C_CONTENT_TESTS := $(wildcard \
	backend/tests/test_content_api.py \
	backend/tests/test_content_service.py \
	backend/tests/test_source_note_api.py)

STAGE_2D_CONTENT_TESTS := $(wildcard \
	backend/tests/test_domain_schemas.py \
	backend/tests/test_course_mode.py \
	backend/tests/test_note_source_link.py \
	backend/tests/test_occurrence_invariants.py)

.PHONY: check-pnpm bootstrap-backend bootstrap-frontend bootstrap lock migrate dev-api dev-web install-stockfish \
	backend-format backend-lint backend-typecheck backend-static backend-test \
	backend-migration-check backend-check frontend-format frontend-lint \
	frontend-typecheck frontend-test frontend-build frontend-check contracts \
	check-contracts verify smoke acceptance acceptance-stage-2a \
	acceptance-stage-2b acceptance-stage-2c acceptance-stage-2d acceptance-stage-2 \
	acceptance-stage-3a acceptance-stage-3b acceptance-stage-3c acceptance-stage-3d acceptance-stage-3 \
	acceptance-stage-4a acceptance-stage-4b acceptance-stage-4c acceptance-stage-4 \
	acceptance-stage-6a acceptance-stage-6b acceptance-stage-6c acceptance-stage-6d acceptance-stage-6

install-stockfish:
	uv run --project backend --locked python scripts/install_stockfish.py

check-pnpm:
	@if [ -z "$(PNPM)" ]; then \
		echo "错误：未找到 pnpm 或 corepack。请安装仓库 .node-version 指定的 Node.js 22。" >&2; \
		exit 127; \
	fi
	@$(PNPM) --version >/dev/null

bootstrap-backend:
	uv sync --project backend --locked --all-groups

bootstrap-frontend: check-pnpm
	$(PNPM) install --frozen-lockfile

bootstrap: bootstrap-backend bootstrap-frontend

lock: check-pnpm
	uv lock --project backend
	$(PNPM) install

migrate: bootstrap-backend
	uv run --project backend --locked alembic -c backend/alembic.ini upgrade head

dev-api: migrate
	uv run --project backend --locked python -m chess_workbench

dev-web: check-pnpm
	$(PNPM) --dir frontend dev

backend-format:
	uv run --project backend --locked ruff format --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py --check

backend-lint:
	uv run --project backend --locked ruff check --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py

backend-typecheck:
	uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py

backend-static: backend-format backend-lint backend-typecheck

backend-test:
	uv run --project backend --locked pytest -c backend/pyproject.toml --cov-config=backend/pyproject.toml --cov-report=json:backend/coverage.json backend/tests
	uv run --project backend --locked python scripts/check_backend_coverage.py backend/coverage.json

backend-migration-check:
	uv run --project backend --locked python scripts/check_migrations.py

backend-check: backend-static backend-test backend-migration-check

frontend-format: check-pnpm
	$(PNPM) --dir frontend format:check

frontend-lint: check-pnpm
	$(PNPM) --dir frontend lint

frontend-typecheck: check-pnpm
	$(PNPM) --dir frontend typecheck

frontend-test: check-pnpm
	$(PNPM) --dir frontend test

frontend-build: check-pnpm
	$(PNPM) --dir frontend build

frontend-check: frontend-format frontend-lint frontend-typecheck frontend-test frontend-build

contracts: check-pnpm
	uv run --project backend --locked python scripts/contracts.py --write

check-contracts: check-pnpm
	uv run --project backend --locked python scripts/contracts.py --check

verify: backend-check check-contracts frontend-check

smoke:
	bash scripts/smoke.sh

# Stage 2 unit gates are cumulative: running a later target proves every earlier
# unit before checking the current slice. Only the aggregate target needs pnpm.
acceptance-stage-2a: bootstrap-backend backend-static
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_position_identity.py backend/tests/test_config.py --cov=chess_workbench.domain.position_identity --cov-branch --cov-report=term-missing --cov-fail-under=90
	@test -s docs/decisions/0002-position-identity.md
	@test -s docs/decisions/0003-mysql-async-driver.md
	@test -s docs/decisions/0005-dual-course-mode.md

acceptance-stage-2b: acceptance-stage-2a
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_database.py backend/tests/test_models.py backend/tests/test_graph_repository.py --cov=chess_workbench.store.models.graph --cov=chess_workbench.store.models.mixins --cov=chess_workbench.store.graph_repository --cov-branch --cov-report=term-missing --cov-fail-under=90
	$(MAKE) backend-migration-check

acceptance-stage-2c: acceptance-stage-2b
	@test "$(words $(STAGE_2C_CONTENT_TESTS))" -eq 3 || { \
		echo "错误：Stage 2C 缺少内容、来源或知识笔记验收测试。" >&2; \
		exit 1; \
	}
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_domain_schemas.py backend/tests/test_graph_api.py $(STAGE_2C_CONTENT_TESTS) --cov=chess_workbench.schemas.domain --cov-branch --cov-report=term-missing --cov-fail-under=90
	@test -s docs/decisions/0004-course-context-and-lifecycle.md

acceptance-stage-2d: acceptance-stage-2c
	@test "$(words $(STAGE_2D_CONTENT_TESTS))" -eq 4 || { \
		echo "错误：Stage 2D 缺少 Course.mode / source_note_id 验收测试。" >&2; \
		exit 1; \
	}
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' $(STAGE_2D_CONTENT_TESTS) --cov=chess_workbench.store.models.content --cov=chess_workbench.schemas.domain --cov-branch --cov-report=term-missing --cov-fail-under=90

acceptance-stage-2: acceptance-stage-2d bootstrap-frontend
	$(MAKE) verify
	$(MAKE) smoke

acceptance-stage-3a: acceptance-stage-2d
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_parser.py --cov=chess_workbench.logic.pgn --cov-branch --cov-report=term-missing --cov-fail-under=90

acceptance-stage-3b: acceptance-stage-3a
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_import.py backend/tests/test_pgn_api.py --cov=chess_workbench.logic.pgn_import --cov=chess_workbench.services.pgn --cov=chess_workbench.api.pgn --cov=chess_workbench.store.models.pgn --cov-branch --cov-report=term-missing --cov-fail-under=90

acceptance-stage-3c: acceptance-stage-3b
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_export.py --cov=chess_workbench.logic.pgn_export --cov=chess_workbench.logic.pgn_compare --cov-branch --cov-report=term-missing --cov-fail-under=90

acceptance-stage-3d: acceptance-stage-3c
	@if [ -n "$(MYSQL_ACCEPTANCE_URL)" ]; then \
		CHESS_WORKBENCH_MYSQL_URL="$(MYSQL_ACCEPTANCE_URL)" \
			uv run --project backend --locked python scripts/check_mysql.py; \
	else \
		uv run --project backend --locked python scripts/check_mysql.py --container; \
	fi

acceptance-stage-3: acceptance-stage-3d bootstrap-frontend
	$(MAKE) verify
	$(MAKE) smoke

acceptance-stage-4a: acceptance-stage-3d bootstrap-frontend
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_content_blocks.py backend/tests/test_dashboard_api.py
	$(PNPM) --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx --coverage=false

acceptance-stage-4b: acceptance-stage-4a
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_content_blocks.py
	$(PNPM) --dir frontend exec vitest run src/app/CourseEditor.test.tsx --coverage=false

acceptance-stage-4c: acceptance-stage-4b
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_stage4_authoring.py
	$(PNPM) --dir frontend exec vitest run src/app/CourseEditor.test.tsx src/app/editorDraft.test.ts --coverage=false
	$(MAKE) check-contracts

acceptance-stage-4: acceptance-stage-4c
	$(MAKE) verify
	$(MAKE) smoke
	bash scripts/stage4_e2e.sh

acceptance-stage-6a: acceptance-stage-4c
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_stage6_jobs.py
	@test -s docs/decisions/0009-sql-jobs-and-local-engine-runtime.md

acceptance-stage-6b: acceptance-stage-6a install-stockfish
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_stage6_engine.py backend/tests/test_stage6_real_stockfish.py backend/tests/test_stage6_tool_manifest.py
	$(PNPM) --dir frontend exec vitest run src/app/AnalysisPage.test.tsx --coverage=false

acceptance-stage-6c: acceptance-stage-6b
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_stage6_analysis_policy.py backend/tests/test_stage6_api.py

acceptance-stage-6d: acceptance-stage-6c
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_stage6_engine.py::test_play_review_and_save_course_draft_use_existing_knowledge_layer
	$(PNPM) --dir frontend exec vitest run src/app/AnalysisPage.test.tsx --coverage=false
	$(MAKE) check-contracts

acceptance-stage-6: acceptance-stage-6d
	$(MAKE) verify
	$(MAKE) smoke
	bash scripts/stage6_e2e.sh

# CI keeps one stable entry point while inheriting the current stage gate.
acceptance: acceptance-stage-6
