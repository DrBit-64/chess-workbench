SHELL := /usr/bin/env bash
.DEFAULT_GOAL := bootstrap

PROJECT_ROOT := $(CURDIR)
UV_CACHE_DIR ?= $(PROJECT_ROOT)/.cache/uv
export UV_CACHE_DIR

STAGE_2C_CONTENT_TEST := $(firstword $(wildcard \
	backend/tests/test_content_api.py \
	backend/tests/test_content_service.py))

STAGE_2D_CONTENT_TEST := $(firstword $(wildcard \
	backend/tests/test_course_mode.py \
	backend/tests/test_note_source_link.py))

.PHONY: check-pnpm bootstrap-backend bootstrap-frontend bootstrap lock dev-api dev-web \
	backend-format backend-lint backend-typecheck backend-static backend-test \
	backend-migration-check backend-check frontend-format frontend-lint \
	frontend-typecheck frontend-test frontend-build frontend-check contracts \
	check-contracts verify smoke acceptance acceptance-stage-2a \
	acceptance-stage-2b acceptance-stage-2c acceptance-stage-2d acceptance-stage-2 \
	acceptance-stage-3a acceptance-stage-3b acceptance-stage-3c acceptance-stage-3d acceptance-stage-3

check-pnpm:
	@if ! command -v pnpm >/dev/null 2>&1; then \
		echo "错误：未找到 pnpm。请安装 Node.js 22，并通过 Corepack 启用仓库锁定的 pnpm 10.14.0。" >&2; \
		echo "示例：corepack enable && corepack prepare pnpm@10.14.0 --activate" >&2; \
		exit 127; \
	fi

bootstrap-backend:
	uv sync --project backend --locked --all-groups

bootstrap-frontend: check-pnpm
	pnpm install --frozen-lockfile

bootstrap: bootstrap-backend bootstrap-frontend

lock: check-pnpm
	uv lock --project backend
	pnpm install

dev-api:
	uv run --project backend --locked python -m chess_workbench

dev-web: check-pnpm
	pnpm --dir frontend dev

backend-format:
	uv run --project backend --locked ruff format --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py --check

backend-lint:
	uv run --project backend --locked ruff check --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py

backend-typecheck:
	uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py

backend-static: backend-format backend-lint backend-typecheck

backend-test:
	uv run --project backend --locked pytest -c backend/pyproject.toml --cov-config=backend/pyproject.toml --cov-report=json:backend/coverage.json backend/tests
	uv run --project backend --locked python scripts/check_backend_coverage.py backend/coverage.json

backend-migration-check:
	uv run --project backend --locked python scripts/check_migrations.py

backend-check: backend-static backend-test backend-migration-check

frontend-format: check-pnpm
	pnpm --dir frontend format:check

frontend-lint: check-pnpm
	pnpm --dir frontend lint

frontend-typecheck: check-pnpm
	pnpm --dir frontend typecheck

frontend-test: check-pnpm
	pnpm --dir frontend test

frontend-build: check-pnpm
	pnpm --dir frontend build

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
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_position_identity.py backend/tests/test_config.py --cov=chess_workbench.domain.position_identity --cov-branch --cov-report=term-missing --cov-fail-under=85
	@test -s docs/decisions/0002-position-identity.md
	@test -s docs/decisions/0003-mysql-async-driver.md
	@test -s docs/decisions/0005-dual-course-mode.md

acceptance-stage-2b: acceptance-stage-2a
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_database.py backend/tests/test_models.py backend/tests/test_graph_repository.py --cov=chess_workbench.store.models.graph --cov=chess_workbench.store.models.mixins --cov=chess_workbench.store.graph_repository --cov-branch --cov-report=term-missing --cov-fail-under=85
	$(MAKE) backend-migration-check

acceptance-stage-2c: acceptance-stage-2b
	@test -n "$(STAGE_2C_CONTENT_TEST)" || { \
		echo "错误：Stage 2C 缺少内容 API/服务验收测试（test_content_api.py 或 test_content_service.py）。" >&2; \
		exit 1; \
	}
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_domain_schemas.py backend/tests/test_graph_api.py $(STAGE_2C_CONTENT_TEST) --cov=chess_workbench.schemas.domain --cov-branch --cov-report=term-missing --cov-fail-under=85
	@test -s docs/decisions/0004-course-context-and-lifecycle.md

acceptance-stage-2d: acceptance-stage-2c
	@test -n "$(STAGE_2D_CONTENT_TEST)" || { \
		echo "错误：Stage 2D 缺少 Course.mode / source_note_id 验收测试。" >&2; \
		exit 1; \
	}
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_course_mode.py backend/tests/test_note_source_link.py $(STAGE_2D_CONTENT_TEST) --cov=chess_workbench.store.models.content --cov=chess_workbench.schemas.domain --cov-branch --cov-report=term-missing --cov-fail-under=89

acceptance-stage-2: acceptance-stage-2d bootstrap-frontend
	$(MAKE) verify
	$(MAKE) smoke

acceptance-stage-3a: acceptance-stage-2d
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_parser.py --cov=chess_workbench.logic.pgn --cov-branch --cov-report=term-missing --cov-fail-under=85

acceptance-stage-3b: acceptance-stage-2d
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_import.py --cov=chess_workbench.logic.pgn_import --cov-branch --cov-report=term-missing --cov-fail-under=85

acceptance-stage-3c: acceptance-stage-2d
	uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_pgn_export.py --cov=chess_workbench.logic.pgn_export --cov=chess_workbench.logic.pgn_compare --cov-branch --cov-report=term-missing --cov-fail-under=85

acceptance-stage-3d:
	@if [ -n "$$CHESS_WORKBENCH_MYSQL_URL" ]; then \
		uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_mysql_compat.py -v --no-cov; \
	else \
		echo "CHESS_WORKBENCH_MYSQL_URL not set; skipping MySQL compat tests (use --container for local Docker)"; \
	fi

acceptance-stage-3: acceptance-stage-3a bootstrap-frontend
	$(MAKE) verify
	$(MAKE) smoke

# CI keeps one stable entry point while inheriting the current stage gate.
acceptance: acceptance-stage-2
