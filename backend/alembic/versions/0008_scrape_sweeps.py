"""scrape_sweeps + vehicles.last_seen_sweep_id + scrape_jobs.sweep_id

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-29

A Sweep is one logical pass over all queued makes. It can span many sessions
(CF blocks, Ctrl-C, connection drops). Phase 2 (delist classification) only
fires when the sweep is complete, so an interrupted sweep cannot mass-flag
cards seen in earlier sessions of the same sweep.

`vehicles.last_seen_sweep_id` replaces the per-session `last_seen_at`
comparison. A delist-suspect at sweep end is any active row in the scanned
makes whose last_seen_sweep_id != current sweep id.

Legacy columns (`missing_scan_count`, `last_seen_at`) stay until V2 is
verified across two clean sweeps; they get dropped in a follow-up migration.
"""
import sqlalchemy as sa
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scrape_sweeps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("target_make", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        sa.Column("makes_total", sa.Integer(), nullable=True),
        sa.Column(
            "makes_done",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "scanned_makes",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.create_index("ix_scrape_sweeps_status", "scrape_sweeps", ["status"])
    op.create_index(
        "ix_scrape_sweeps_running_scope",
        "scrape_sweeps",
        ["job_type", "target_make"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.add_column(
        "vehicles",
        sa.Column(
            "last_seen_sweep_id",
            sa.Integer(),
            sa.ForeignKey("scrape_sweeps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_vehicles_last_seen_sweep",
        "vehicles",
        ["last_seen_sweep_id"],
    )

    op.add_column(
        "scrape_jobs",
        sa.Column(
            "sweep_id",
            sa.Integer(),
            sa.ForeignKey("scrape_sweeps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("scrape_jobs", "sweep_id")
    op.drop_index("ix_vehicles_last_seen_sweep", table_name="vehicles")
    op.drop_column("vehicles", "last_seen_sweep_id")
    op.drop_index("ix_scrape_sweeps_running_scope", table_name="scrape_sweeps")
    op.drop_index("ix_scrape_sweeps_status", table_name="scrape_sweeps")
    op.drop_table("scrape_sweeps")
