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
    assert _target_prerequisites(makefile, "acceptance") == ("acceptance-stage-4",)


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
