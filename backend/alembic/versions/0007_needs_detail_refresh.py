"""add needs_detail_refresh flag for the Listing → Details Update queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # needs_detail_refresh: TRUE on rows that need a detail-page fetch.
    # Set by Listing runs (new / reactivated / date_updated_turbo bumped /
    # delist-suspect). Cleared by Details Update after the row processes.
    # Partial index keeps the flagged-set lookup cheap.
    op.add_column(
        "vehicles",
        sa.Column(
            "needs_detail_refresh",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_index(
        "idx_vehicles_needs_detail_refresh",
        "vehicles",
        ["needs_detail_refresh"],
        postgresql_where=sa.text("needs_detail_refresh = TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_vehicles_needs_detail_refresh", table_name="vehicles"
    )
    op.drop_column("vehicles", "needs_detail_refresh")
