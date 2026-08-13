from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = PROJECT_ROOT / "Makefile"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
MYSQL_SCRIPT = PROJECT_ROOT / "scripts" / "check_mysql.py"

PINNED_MYSQL_IMAGE = (
    "mysql:8.4@sha256:b3b90af2a6552ae30c266fdb7d5dd55f3afb72404bb78d37fe8a23eb857fd3fb"
)


def _target_prerequisites(makefile: str, target: str) -> tuple[str, ...]:
    match = re.search(rf"^{re.escape(target)}:\s*(.*)$", makefile, re.MULTILINE)
    assert match is not None, f"missing Make target: {target}"
    return tuple(match.group(1).split())


def _target_recipe(makefile: str, target: str) -> str:
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n(?P<recipe>(?:\t[^\n]*(?:\n|$))+)",
        makefile,
        re.MULTILINE,
    )
    assert match is not None, f"missing recipe for Make target: {target}"
    return match.group("recipe")


def test_mysql_image_is_digest_pinned_and_shared() -> None:
    script = MYSQL_SCRIPT.read_text(encoding="utf-8")
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    image_pattern = re.compile(r"mysql:8\.4@sha256:[0-9a-f]{64}")

    script_images = image_pattern.findall(script)
    workflow_images = image_pattern.findall(workflow)

    assert script_images == [PINNED_MYSQL_IMAGE]
    assert workflow_images == [PINNED_MYSQL_IMAGE]


def test_stage_3_make_targets_are_cumulative() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "acceptance-stage-3a") == ("acceptance-stage-2d",)
    assert _target_prerequisites(makefile, "acceptance-stage-3b") == ("acceptance-stage-3a",)
    assert _target_prerequisites(makefile, "acceptance-stage-3c") == ("acceptance-stage-3b",)
    assert _target_prerequisites(makefile, "acceptance-stage-3d") == ("acceptance-stage-3c",)
    assert _target_prerequisites(makefile, "acceptance-stage-3") == (
        "acceptance-stage-3d",
        "bootstrap-frontend",
    )


def test_stage_4_make_targets_are_cumulative() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "acceptance-stage-4a") == (
        "acceptance-stage-3d",
        "bootstrap-frontend",
    )
    assert _target_prerequisites(makefile, "acceptance-stage-4b") == ("acceptance-stage-4a",)
    assert _target_prerequisites(makefile, "acceptance-stage-4c") == ("acceptance-stage-4b",)
    assert _target_prerequisites(makefile, "acceptance-stage-4") == ("acceptance-stage-4c",)


def test_stage_6_make_targets_are_cumulative() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "acceptance-stage-6a") == ("acceptance-stage-4c",)
    assert _target_prerequisites(makefile, "acceptance-stage-6b") == (
        "acceptance-stage-6a",
        "install-stockfish",
    )
    assert _target_prerequisites(makefile, "acceptance-stage-6c") == ("acceptance-stage-6b",)
    assert _target_prerequisites(makefile, "acceptance-stage-6d") == ("acceptance-stage-6c",)
    assert _target_prerequisites(makefile, "acceptance-stage-6") == ("acceptance-stage-6d",)
    assert _target_prerequisites(makefile, "acceptance") == ("acceptance-stage-6",)


def test_development_api_upgrades_the_database_before_starting() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "migrate") == ("bootstrap-backend",)
    assert _target_prerequisites(makefile, "dev-api") == ("migrate",)
    assert "alembic -c backend/alembic.ini upgrade head" in _target_recipe(makefile, "migrate")


def test_stage_3d_uses_safe_script_without_silent_skip() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-3d")

    assert "MYSQL_ACCEPTANCE_URL ?= $(CHESS_WORKBENCH_MYSQL_URL)" in makefile
    assert "scripts/check_mysql.py" in recipe
    assert "MYSQL_ACCEPTANCE_URL" in recipe
    assert "--container" in recipe
    assert "test_mysql_compat.py" not in recipe
    assert "skip" not in recipe.lower()


def test_ci_uses_only_the_cumulative_acceptance_entry() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("run: make acceptance") == 1
    assert "MYSQL_ACCEPTANCE_URL:" in workflow
    assert "test_mysql_compat.py" not in workflow
    assert "CHESS_WORKBENCH_DATABASE_URL:" not in workflow
    assert "CHESS_WORKBENCH_MYSQL_URL:" not in workflow


PORTABLE_BOUNDARY_SUITES = (
    "backend/tests/test_extraction_contract.py",
    "backend/tests/test_extraction_provider.py",
    "backend/tests/test_extraction_deepseek.py",
    "backend/tests/test_extraction_decoder.py",
    "backend/tests/test_extraction_validation.py",
    "backend/tests/test_ccef_consumer_proof.py",
)

STAGE_8A_SUITES = (
    "backend/tests/test_source_storage.py",
    "backend/tests/test_pdf_prepare.py",
    "backend/tests/test_pdf_inspection.py",
    "backend/tests/test_stage8_models.py",
    "backend/tests/test_pdf_persistence.py",
    "backend/tests/test_pdf_schemas.py",
    "backend/tests/test_pdf_api.py",
    "backend/tests/test_stage6_jobs.py",
)

STAGE_8B_SUITES = (
    "backend/tests/test_extraction_evidence.py",
    "backend/tests/test_pdfium_renderer.py",
    "backend/tests/test_paddleocr_adapter.py",
    "backend/tests/test_source_storage.py",
    "backend/tests/test_stage8_models.py",
    "backend/tests/test_stage8_pdf_extraction.py",
    "backend/tests/test_pdf_schemas.py",
    "backend/tests/test_pdf_api.py",
)

STAGE_8C_SUITES = (
    "backend/tests/test_config.py",
    "backend/tests/test_extraction_prompting.py",
    "backend/tests/test_extraction_candidates.py",
    "backend/tests/test_extraction_deepseek.py",
    "backend/tests/test_stage8c_execution.py",
    "backend/tests/test_pdf_schemas.py",
    "backend/tests/test_pdf_api.py",
)


def _pytest_lines(recipe: str) -> list[str]:
    return [
        line
        for line in recipe.splitlines()
        if line.strip().startswith("uv run --project backend --locked pytest")
    ]


def test_stage_8_make_target_prerequisites_are_frozen() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "acceptance-stage-8p") == ("acceptance-stage-6a",)
    assert _target_prerequisites(makefile, "acceptance-stage-8a") == (
        "acceptance-stage-8p",
        "bootstrap-frontend",
    )
    assert _target_prerequisites(makefile, "acceptance-stage-8b") == (
        "bootstrap-backend",
        "bootstrap-frontend",
    )
    assert _target_prerequisites(makefile, "acceptance-stage-8c") == (
        "bootstrap-backend",
        "bootstrap-frontend",
    )


def test_stage_8_targets_are_declared_phony() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    phony_block = re.search(r"^\.PHONY:(?:[^\n]*\\\n)*[^\n]*", makefile, re.MULTILINE)
    assert phony_block is not None
    assert "acceptance-stage-8p" in phony_block.group(0)
    assert "acceptance-stage-8a" in phony_block.group(0)
    assert "acceptance-stage-8b" in phony_block.group(0)
    assert "acceptance-stage-8c" in phony_block.group(0)


def test_stage_8p_recipe_runs_exactly_the_portable_boundary_suites() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-8p")

    pytest_lines = _pytest_lines(recipe)
    assert len(pytest_lines) == 1
    pytest_line = pytest_lines[0]
    assert "-o addopts=''" in pytest_line
    assert "--cov" not in pytest_line
    assert len(re.findall(r"backend/tests/[\w.]+\.py", pytest_line)) == len(
        PORTABLE_BOUNDARY_SUITES
    )
    positions = [pytest_line.index(suite) for suite in PORTABLE_BOUNDARY_SUITES]
    assert positions == sorted(positions)

    assert "@test -s docs/decisions/0010-portable-ai-extraction-contract.md" in recipe
    assert "@test -s docs/architecture/ccef-v1.md" in recipe
    assert "@test -s contracts/chess-content-extraction-v1.schema.json" in recipe


def test_stage_8a_recipe_runs_exactly_the_8a_suites_and_commands() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-8a")

    pytest_lines = _pytest_lines(recipe)
    assert len(pytest_lines) == 1
    pytest_line = pytest_lines[0]
    assert "-o addopts=''" in pytest_line
    assert "--cov" not in pytest_line
    assert len(re.findall(r"backend/tests/[\w.]+\.py", pytest_line)) == len(STAGE_8A_SUITES)
    positions = [pytest_line.index(suite) for suite in STAGE_8A_SUITES]
    assert positions == sorted(positions)

    required = [
        "$(MAKE) backend-static",
        "$(MAKE) backend-migration-check",
        "@test -s docs/decisions/0012-stage-8a-pdf-assets-and-extraction-runs.md",
        "$(MAKE) check-contracts",
        "$(MAKE) frontend-format frontend-lint frontend-typecheck",
        "vitest run src/app/WorkbenchPages.test.tsx --coverage=false",
    ]
    assert [recipe.index(item) for item in required] == sorted(
        recipe.index(item) for item in required
    )


def test_stage_8a_recipe_inherits_the_portable_boundary_gate() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-8a")

    for suite in PORTABLE_BOUNDARY_SUITES:
        assert suite not in recipe


def test_stage_8b_recipe_is_focused_and_uses_exact_stage_8b_suites() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-8b")

    pytest_lines = _pytest_lines(recipe)
    assert len(pytest_lines) == 1
    pytest_line = pytest_lines[0]
    assert "-o addopts=''" in pytest_line
    assert "--cov" not in pytest_line
    assert len(re.findall(r"backend/tests/[\w.]+\.py", pytest_line)) == len(STAGE_8B_SUITES)
    assert [pytest_line.index(suite) for suite in STAGE_8B_SUITES] == sorted(
        pytest_line.index(suite) for suite in STAGE_8B_SUITES
    )
    assert "acceptance-stage-8a" not in recipe
    assert "acceptance-stage-8p" not in recipe
    assert "$(MAKE) backend-static" not in recipe
    assert "$(MAKE) verify" not in recipe
    assert "$(MAKE) smoke" not in recipe
    for required in (
        "ruff format --check",
        "ruff check",
        "mypy --config-file",
        "@test -s docs/decisions/0013-stage-8b-rendering-ocr-and-source-evidence.md",
        "$(MAKE) check-contracts",
        "prettier --check src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx",
        "eslint src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx",
        "tsc --noEmit",
        "vitest run src/app/WorkbenchPages.test.tsx --coverage=false",
    ):
        assert required in recipe


def test_stage_8c_recipe_is_focused_and_uses_exact_stage_8c_suites() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    recipe = _target_recipe(makefile, "acceptance-stage-8c")

    pytest_lines = _pytest_lines(recipe)
    assert len(pytest_lines) == 1
    pytest_line = pytest_lines[0]
    assert "-o addopts=''" in pytest_line
    assert "--cov" not in pytest_line
    assert len(re.findall(r"backend/tests/[\w.]+\.py", pytest_line)) == len(STAGE_8C_SUITES)
    assert [pytest_line.index(suite) for suite in STAGE_8C_SUITES] == sorted(
        pytest_line.index(suite) for suite in STAGE_8C_SUITES
    )
    assert "acceptance-stage-8b" not in recipe
    assert "acceptance-stage-8a" not in recipe
    assert "acceptance-stage-8p" not in recipe
    assert "$(MAKE) verify" not in recipe
    assert "$(MAKE) smoke" not in recipe
    for required in (
        "test_extraction_deepseek.py",
        "test_stage8c_execution.py",
        "ruff format --check",
        "ruff check",
        "mypy --config-file",
        "@test -s docs/decisions/0014-stage-8c-provider-execution-and-ccef-candidates.md",
        "$(MAKE) check-contracts",
        "prettier --check src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx",
        "eslint src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx",
        "tsc --noEmit",
        "vitest run src/app/WorkbenchPages.test.tsx --coverage=false",
    ):
        assert required in recipe


def test_acceptance_stable_entry_remains_stage_6_and_excludes_stage_8() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert _target_prerequisites(makefile, "acceptance") == ("acceptance-stage-6",)
    acceptance_line = next(line for line in makefile.splitlines() if line.startswith("acceptance:"))
    assert "acceptance-stage-6" in acceptance_line
    assert "acceptance-stage-8p" not in acceptance_line
    assert "acceptance-stage-8a" not in acceptance_line

    stage_6_recipe = _target_recipe(makefile, "acceptance-stage-6")
    assert "$(MAKE) verify" in stage_6_recipe
    assert "$(MAKE) smoke" in stage_6_recipe
    assert "bash scripts/stage6_e2e.sh" in stage_6_recipe
