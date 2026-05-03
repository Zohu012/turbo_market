"""analytics dashboards: partial index for days-to-sell queries

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-02

The Days-to-Sell dashboard runs aggregates over inactive rows with
`days_to_sell IS NOT NULL`, often filtered by deactivation date. A partial
index on those rows keeps the percentile / histogram queries fast.
"""
import sqlalchemy as sa
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_vehicles_inactive_dts",
        "vehicles",
        ["date_deactivated", "days_to_sell"],
        postgresql_where=sa.text("status = 'inactive' AND days_to_sell IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_vehicles_inactive_dts", table_name="vehicles")
