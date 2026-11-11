"""Remember public accounts, resumable ranges and already seen game IDs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "20261107_0019"
down_revision = "20261107_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False
        ),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("username", sa.String(40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("cursor_ms", sa.BigInteger(), nullable=False),
        sa.Column("target_ms", sa.BigInteger()),
        sa.Column("last_synced_ms", sa.BigInteger()),
        sa.UniqueConstraint("platform", "username", name="uq_notebook_account_name"),
        mysql_engine="InnoDB",
    )
    op.create_table(
        "notebook_account_games",
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("notebook_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "external_id",
            sa.String(40).with_variant(
                mysql.VARCHAR(40, charset="ascii", collation="ascii_bin"), "mysql"
            ),
            primary_key=True,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("checked_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.String(256), nullable=False),
        sa.Column("pending_pgn", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")),
        sa.Column("error", sa.Text()),
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_notebook_account_game_work",
        "notebook_account_games",
        ["account_id", "state", "checked_ms"],
    )


def downgrade() -> None:
    op.drop_table("notebook_account_games")
    op.drop_table("notebook_accounts")
