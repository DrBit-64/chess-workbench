"""Allow one immutable semantic extraction manifest artifact per run.

Revision ID: 20260925_0016
Revises: 20260828_0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_0016"
down_revision: str | None = "20260828_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "kind IN ('rendered_page','render_manifest','ocr_fragment','ocr_manifest',"
    "'provider_response','raw_ccef','normalized_ccef')"
)
_NEW = (
    "kind IN ('rendered_page','render_manifest','ocr_fragment','ocr_manifest',"
    "'provider_response','raw_ccef','normalized_ccef','semantic_manifest')"
)


def upgrade() -> None:
    with op.batch_alter_table("extraction_artifacts") as batch:
        batch.drop_constraint(op.f("ck_extraction_artifacts_kind"), type_="check")
        batch.create_check_constraint(op.f("ck_extraction_artifacts_kind"), _NEW)


def downgrade() -> None:
    with op.batch_alter_table("extraction_artifacts") as batch:
        batch.drop_constraint(op.f("ck_extraction_artifacts_kind"), type_="check")
        batch.create_check_constraint(op.f("ck_extraction_artifacts_kind"), _OLD)
