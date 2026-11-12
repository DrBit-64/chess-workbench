"""Index the dates actually played and retain upstream game start time across sync steps."""

import sqlalchemy as sa
from alembic import op
from chess_workbench.store.catalog_backfill import backfill_catalog
from sqlalchemy.dialects import mysql

revision = "20261112_0022"
down_revision = "20261112_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    stamp = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.add_column("personal_games", sa.Column("order_at", stamp))
    op.add_column("personal_games", sa.Column("started_at", stamp))
    op.add_column("personal_games", sa.Column("time_control", sa.Text()))
    op.add_column("notebook_account_games", sa.Column("started_at", stamp))
    op.create_index(
        "ix_personal_games_chronology", "personal_games", ["order_at", "created_at", "id"]
    )
    if not op.get_context().as_sql:
        backfill_catalog(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_personal_games_chronology", table_name="personal_games")
    op.drop_column("notebook_account_games", "started_at")
    op.drop_column("personal_games", "time_control")
    op.drop_column("personal_games", "started_at")
    op.drop_column("personal_games", "order_at")
