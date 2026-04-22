"""detail fields, history tables, features/labels M2M

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── vehicles: new columns ────────────────────────────────────────────────
    op.add_column("vehicles", sa.Column("hp", sa.SmallInteger(), nullable=True))
    op.add_column("vehicles", sa.Column("condition", sa.String(120), nullable=True))
    op.add_column("vehicles", sa.Column("market_for", sa.String(80), nullable=True))
    op.add_column(
        "vehicles",
        sa.Column("date_updated_turbo", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("is_on_order", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "vehicles",
        sa.Column("view_count_base", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vehicles",
        sa.Column("last_scraped_view_count", sa.Integer(), nullable=True),
    )
    op.create_index(
        "idx_vehicles_date_updated_turbo", "vehicles", ["date_updated_turbo"]
    )

    # Replace the generated days_to_sell column with a plain int so it can
    # accumulate across relistings. active_days_accumulated tracks the sum of
    # prior active windows; last_activated_at anchors the current window.
    op.execute("ALTER TABLE vehicles DROP COLUMN days_to_sell")
    op.add_column("vehicles", sa.Column("days_to_sell", sa.Integer(), nullable=True))
    op.add_column(
        "vehicles",
        sa.Column(
            "active_days_accumulated",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "vehicles",
        sa.Column("last_activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Backfill last_activated_at from date_added so existing rows behave sanely.
    op.execute("UPDATE vehicles SET last_activated_at = date_added")

    # ── sellers: normalized registration date ────────────────────────────────
    op.add_column("sellers", sa.Column("regdate", sa.Date(), nullable=True))

    # ── features / labels (M2M dimension + join) ─────────────────────────────
    op.create_table(
        "features",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
    )
    op.create_table(
        "vehicle_features",
        sa.Column(
            "vehicle_id",
            sa.BigInteger(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_id",
            sa.Integer(),
            sa.ForeignKey("features.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "idx_vehicle_features_feature", "vehicle_features", ["feature_id"]
    )

    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
    )
    op.create_table(
        "vehicle_labels",
        sa.Column(
            "vehicle_id",
            sa.BigInteger(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            sa.Integer(),
            sa.ForeignKey("labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # ── odometer + view_count history (mirror price_history shape) ──────────
    op.create_table(
        "odometer_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "vehicle_id",
            sa.BigInteger(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("odometer", sa.Integer(), nullable=False),
        sa.Column("odometer_type", sa.String(5), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_odo_history_vehicle_date",
        "odometer_history",
        ["vehicle_id", "recorded_at"],
    )

    op.create_table(
        "view_count_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "vehicle_id",
            sa.BigInteger(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_viewc_history_vehicle_date",
        "view_count_history",
        ["vehicle_id", "recorded_at"],
    )

    # ── seller.total_listings correction ─────────────────────────────────────
    # Old code incremented total_listings on every detail-fetch update (not per
    # unique vehicle), so existing values are over-counted. Recompute from the
    # current vehicles table. Going forward, pipeline increments only on new.
    op.execute(
        "UPDATE sellers s SET total_listings = "
        "COALESCE((SELECT COUNT(*) FROM vehicles v "
        "          WHERE v.seller_id = s.id AND v.status = 'active'), 0)"
    )


def downgrade() -> None:
    op.drop_index("idx_viewc_history_vehicle_date", table_name="view_count_history")
    op.drop_table("view_count_history")
    op.drop_index("idx_odo_history_vehicle_date", table_name="odometer_history")
    op.drop_table("odometer_history")

    op.drop_table("vehicle_labels")
    op.drop_table("labels")
    op.drop_index("idx_vehicle_features_feature", table_name="vehicle_features")
    op.drop_table("vehicle_features")
    op.drop_table("features")

    op.drop_column("sellers", "regdate")

    op.drop_column("vehicles", "last_activated_at")
    op.drop_column("vehicles", "active_days_accumulated")
    op.drop_column("vehicles", "days_to_sell")
    op.execute(
        "ALTER TABLE vehicles ADD COLUMN days_to_sell INTEGER "
        "GENERATED ALWAYS AS ("
        "  CASE WHEN date_deactivated IS NOT NULL "
        "  THEN EXTRACT(DAY FROM date_deactivated - date_added)::INTEGER "
        "  END"
        ") STORED"
    )

    op.drop_index("idx_vehicles_date_updated_turbo", table_name="vehicles")
    op.drop_column("vehicles", "last_scraped_view_count")
    op.drop_column("vehicles", "view_count_base")
    op.drop_column("vehicles", "is_on_order")
    op.drop_column("vehicles", "date_updated_turbo")
    op.drop_column("vehicles", "market_for")
    op.drop_column("vehicles", "condition")
    op.drop_column("vehicles", "hp")
