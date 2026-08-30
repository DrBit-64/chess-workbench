"""Add recoverable archival state for durable Jobs.

Revision ID: 20260828_0015
Revises: 20260828_0014
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260828_0015"
down_revision: str | None = "20260828_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_datetime() -> sa.DateTime:
    return sa.DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.add_column("jobs", sa.Column("archived_at", _utc_datetime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "archived_at")
