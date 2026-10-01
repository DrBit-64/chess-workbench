SHELL := /usr/bin/env bash
.DEFAULT_GOAL := bootstrap

PROJECT_ROOT := $(CURDIR)
UV_CACHE_DIR ?= $(PROJECT_ROOT)/.cache/uv
export UV_CACHE_DIR
PNPM ?= $(shell if command -v pnpm >/dev/null 2>&1; then printf '%s' pnpm; elif command -v corepack >/dev/null 2>&1; then printf '%s' 'corepack pnpm'; fi)

.PHONY: check-pnpm bootstrap-backend bootstrap-frontend bootstrap lock migrate dev-api dev-web install-stockfish install-chess-diagram-model backend-format backend-lint backend-typecheck backend-static backend-test backend-migration-check backend-check frontend-format frontend-lint frontend-typecheck frontend-test frontend-build frontend-check contracts check-contracts verify smoke

install-stockfish:
	uv run --project backend --locked python scripts/install_stockfish.py

install-chess-diagram-model:
	uv run --project backend --locked python scripts/install_chess_diagram_model.py

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
	uv run --project backend --locked ruff format --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py scripts/install_chess_diagram_model.py --check

backend-lint:
	uv run --project backend --locked ruff check --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py scripts/install_chess_diagram_model.py

backend-typecheck:
	uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py scripts/check_migrations.py scripts/install_stockfish.py scripts/install_chess_diagram_model.py

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
