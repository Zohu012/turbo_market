"""add last_seen_at to vehicles for per-session delist classification

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # last_seen_at: updated to the current scrape session's started_at every
    # time a listing card is observed. Phase 2 classifies any active vehicle
    # whose last_seen_at is older than the session start as a delist-suspect.
    # Default now() so existing rows are treated as "seen as of the migration
    # moment" — they'll be re-stamped on the next scan anyway.
    op.add_column(
        "vehicles",
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_vehicles_last_seen_at", "vehicles", ["last_seen_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_vehicles_last_seen_at", table_name="vehicles")
    op.drop_column("vehicles", "last_seen_at")
