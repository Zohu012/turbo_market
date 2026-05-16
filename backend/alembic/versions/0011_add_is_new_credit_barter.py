"""feat: add is_new, is_credit, is_barter boolean columns to vehicles

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-16

Adds three nullable boolean flags scraped from turbo.az listing detail pages:
- is_new:    vehicle is brand new (never registered / zero odometer)
- is_credit: seller offers credit payment option
- is_barter: seller accepts barter
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("is_new", sa.Boolean(), nullable=True))
    op.add_column("vehicles", sa.Column("is_credit", sa.Boolean(), nullable=True))
    op.add_column("vehicles", sa.Column("is_barter", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "is_barter")
    op.drop_column("vehicles", "is_credit")
    op.drop_column("vehicles", "is_new")
