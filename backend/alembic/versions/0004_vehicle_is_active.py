"""add is_active generated column to vehicles

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-23
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vehicles ADD COLUMN is_active BOOLEAN "
        "GENERATED ALWAYS AS (status = 'active') STORED"
    )


def downgrade() -> None:
    op.drop_column("vehicles", "is_active")
