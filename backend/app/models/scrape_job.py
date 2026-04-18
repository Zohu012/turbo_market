from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Index, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduler")
    target_make: Mapped[Optional[str]] = mapped_column(String(100))
    target_model: Mapped[Optional[str]] = mapped_column(String(150))
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255))
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    listings_found: Mapped[int] = mapped_column(Integer, default=0)
    listings_new: Mapped[int] = mapped_column(Integer, default=0)
    listings_updated: Mapped[int] = mapped_column(Integer, default=0)
    listings_deactivated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_scrape_jobs_status", "status"),
        Index("idx_scrape_jobs_created_at", "created_at"),
    )
