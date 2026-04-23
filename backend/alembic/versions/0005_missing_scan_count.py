"""add missing_scan_count to vehicles for two-miss sold detection

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column(
            "missing_scan_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "missing_scan_count")
