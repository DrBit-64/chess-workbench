SHELL := /usr/bin/env bash

PROJECT_ROOT := $(CURDIR)
UV_CACHE_DIR ?= $(PROJECT_ROOT)/.cache/uv
export UV_CACHE_DIR

.PHONY: bootstrap lock dev-api dev-web backend-format backend-lint backend-typecheck backend-test backend-migration-check backend-check frontend-format frontend-lint frontend-typecheck frontend-test frontend-build frontend-check contracts check-contracts verify smoke acceptance

bootstrap:
	uv sync --project backend --locked --all-groups
	pnpm install --frozen-lockfile

lock:
	uv lock --project backend
	pnpm install

dev-api:
	uv run --project backend --locked python -m chess_workbench

dev-web:
	pnpm --dir frontend dev

backend-format:
	uv run --project backend --locked ruff format --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py --check

backend-lint:
	uv run --project backend --locked ruff check --config backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py

backend-typecheck:
	uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src backend/tests scripts/contracts.py scripts/assert_health.py scripts/check_backend_coverage.py

backend-test:
	uv run --project backend --locked pytest -c backend/pyproject.toml --cov-config=backend/pyproject.toml --cov-report=json:backend/coverage.json backend/tests
	uv run --project backend --locked python scripts/check_backend_coverage.py backend/coverage.json

backend-migration-check:
	CHESS_WORKBENCH_DATABASE_URL=sqlite+aiosqlite:///:memory: uv run --project backend --locked alembic -c backend/alembic.ini current

backend-check: backend-format backend-lint backend-typecheck backend-test backend-migration-check

frontend-format:
	pnpm --dir frontend format:check

frontend-lint:
	pnpm --dir frontend lint

frontend-typecheck:
	pnpm --dir frontend typecheck

frontend-test:
	pnpm --dir frontend test

frontend-build:
	pnpm --dir frontend build

frontend-check: frontend-format frontend-lint frontend-typecheck frontend-test frontend-build

contracts:
	uv run --project backend --locked python scripts/contracts.py --write

check-contracts:
	uv run --project backend --locked python scripts/contracts.py --check

verify: backend-check check-contracts frontend-check

smoke:
	bash scripts/smoke.sh

acceptance: bootstrap
	$(MAKE) verify
	$(MAKE) smoke
