from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scrape_job import ScrapeJob


async def get_jobs(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
) -> tuple[list[ScrapeJob], int]:
    filters = []
    if status:
        filters.append(ScrapeJob.status == status)

    count_q = select(func.count()).select_from(ScrapeJob)
    if filters:
        count_q = count_q.where(*filters)
    total = await db.scalar(count_q) or 0

    q = select(ScrapeJob).order_by(ScrapeJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    if filters:
        q = q.where(*filters)

    result = await db.execute(q)
    return list(result.scalars().all()), total


async def get_job(db: AsyncSession, job_id: int) -> Optional[ScrapeJob]:
    result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
    return result.scalar_one_or_none()


async def create_job(db: AsyncSession, job_type: str, triggered_by: str,
                     target_make: Optional[str] = None, target_model: Optional[str] = None) -> ScrapeJob:
    job = ScrapeJob(
        job_type=job_type,
        status="queued",
        triggered_by=triggered_by,
        target_make=target_make,
        target_model=target_model,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job
