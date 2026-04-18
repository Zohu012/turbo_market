"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sellers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("turbo_seller_id", sa.String(100), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("seller_type", sa.String(20), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("profile_url", sa.String(500), nullable=True),
        sa.Column("first_seen", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("total_listings", sa.BigInteger(), default=0, nullable=False, server_default="0"),
        sa.Column("total_sold", sa.BigInteger(), default=0, nullable=False, server_default="0"),
        sa.Column("avg_days_to_sell", sa.Numeric(6, 1), nullable=True),
    )

    op.create_table(
        "seller_phones",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("seller_id", sa.BigInteger(), sa.ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("normalized", sa.String(30), nullable=False),
    )
    op.create_index("idx_seller_phones_normalized", "seller_phones", ["normalized"], unique=True)
    op.create_index("idx_seller_phones_seller_id", "seller_phones", ["seller_id"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("turbo_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("make", sa.String(100), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("price_azn", sa.Numeric(12, 2), nullable=True),
        sa.Column("odometer", sa.Integer(), nullable=True),
        sa.Column("odometer_type", sa.String(5), nullable=True),
        sa.Column("color", sa.String(80), nullable=True),
        sa.Column("engine", sa.String(100), nullable=True),
        sa.Column("body_type", sa.String(80), nullable=True),
        sa.Column("transmission", sa.String(80), nullable=True),
        sa.Column("fuel_type", sa.String(80), nullable=True),
        sa.Column("drive_type", sa.String(80), nullable=True),
        sa.Column("doors", sa.SmallInteger(), nullable=True),
        sa.Column("vin", sa.String(50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("date_added", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("date_updated", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("date_deactivated", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("seller_id", sa.BigInteger(), sa.ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("raw_detail_json", JSONB(), nullable=True),
    )
    # Computed days_to_sell column
    op.execute(
        "ALTER TABLE vehicles ADD COLUMN days_to_sell INTEGER "
        "GENERATED ALWAYS AS ("
        "  CASE WHEN date_deactivated IS NOT NULL "
        "  THEN EXTRACT(DAY FROM date_deactivated - date_added)::INTEGER "
        "  END"
        ") STORED"
    )

    op.create_index("idx_vehicles_turbo_id", "vehicles", ["turbo_id"], unique=True)
    op.create_index("idx_vehicles_make", "vehicles", ["make"])
    op.create_index("idx_vehicles_make_model", "vehicles", ["make", "model"])
    op.create_index("idx_vehicles_year", "vehicles", ["year"])
    op.create_index("idx_vehicles_status", "vehicles", ["status"])
    op.create_index("idx_vehicles_price_azn", "vehicles", ["price_azn"])
    op.create_index("idx_vehicles_odometer", "vehicles", ["odometer"])
    op.create_index("idx_vehicles_color", "vehicles", ["color"])
    op.create_index("idx_vehicles_fuel_type", "vehicles", ["fuel_type"])
    op.create_index("idx_vehicles_transmission", "vehicles", ["transmission"])
    op.create_index("idx_vehicles_seller_id", "vehicles", ["seller_id"])
    op.create_index("idx_vehicles_date_added", "vehicles", ["date_added"])
    op.create_index("idx_vehicles_make_model_year_status", "vehicles", ["make", "model", "year", "status"])
    op.execute(
        "CREATE INDEX idx_vehicles_active ON vehicles(turbo_id) WHERE status = 'active'"
    )

    op.create_table(
        "vehicle_images",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.BigInteger(), sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), default=0, server_default="0"),
        sa.Column("is_primary", sa.Boolean(), default=False, server_default="false"),
    )
    op.create_index("idx_vehicle_images_vehicle_id", "vehicle_images", ["vehicle_id"])

    op.create_table(
        "price_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.BigInteger(), sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_azn", sa.Numeric(12, 2), nullable=True),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_price_history_vehicle_date", "price_history", ["vehicle_id", "recorded_at"])

    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("triggered_by", sa.String(30), nullable=False, server_default="scheduler"),
        sa.Column("target_make", sa.String(100), nullable=True),
        sa.Column("target_model", sa.String(150), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("listings_found", sa.Integer(), default=0, server_default="0"),
        sa.Column("listings_new", sa.Integer(), default=0, server_default="0"),
        sa.Column("listings_updated", sa.Integer(), default=0, server_default="0"),
        sa.Column("listings_deactivated", sa.Integer(), default=0, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_scrape_jobs_status", "scrape_jobs", ["status"])
    op.create_index("idx_scrape_jobs_created_at", "scrape_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_table("scrape_jobs")
    op.drop_table("price_history")
    op.drop_table("vehicle_images")
    op.drop_table("vehicles")
    op.drop_table("seller_phones")
    op.drop_table("sellers")
