from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScrapeSweep(Base):
    """One logical pass over all queued makes for a Listing run.

    A sweep can span many sessions (CF blocks, Ctrl-C, connection drops).
    Phase 2 delist classification only fires when the sweep is complete —
    every queued make has hit `done` status in the per-make sidecar AND the
    user did not stop the run. This is what kills the multi-session false-
    positive trap that the per-session `last_seen_at` comparison used to fall
    into.
    """

    __tablename__ = "scrape_sweeps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_make: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="running"
    )
    makes_total: Mapped[Optional[int]] = mapped_column(Integer)
    makes_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    scanned_makes: Mapped[Optional[list]] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_scrape_sweeps_status", "status"),
        Index(
            "ix_scrape_sweeps_running_scope",
            "job_type",
            "target_make",
            postgresql_where="status = 'running'",
        ),
    )
