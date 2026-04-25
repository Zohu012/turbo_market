import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.crud.scrape_job import get_jobs, get_job, create_job
from app.schemas.scrape_job import ScrapeJobOut, ScrapeJobListResponse, TriggerRequest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/scrape/trigger", response_model=ScrapeJobOut)
async def trigger_scrape(
    body: TriggerRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.scraper.tasks import (
        on_demand_scan,
        daily_full_scan,
        lifecycle_check_task,
        listing_parallel_task,
        details_full_parallel_task,
        details_update_parallel_task,
    )

    job = await create_job(
        db,
        job_type=body.job_type,
        triggered_by="admin",
        target_make=body.target_make,
        target_model=body.target_model,
    )

    if body.job_type == "lifecycle_check":
        celery_result = lifecycle_check_task.apply_async(
            args=[[]], kwargs={"job_id": job.id}, queue="listing"
        )
    elif body.job_type == "full_scan":
        celery_result = daily_full_scan.apply_async(queue="listing")
    elif body.job_type == "listing_parallel":
        celery_result = listing_parallel_task.apply_async(
            args=[job.id],
            kwargs={"target_make": body.target_make},
            queue="listing",
        )
    elif body.job_type == "details_full_parallel":
        celery_result = details_full_parallel_task.apply_async(
            args=[job.id],
            kwargs={"target_make": body.target_make},
            queue="listing",
        )
    elif body.job_type == "details_update_parallel":
        celery_result = details_update_parallel_task.apply_async(
            args=[job.id], queue="listing",
        )
    else:
        celery_result = on_demand_scan.apply_async(
            args=[job.id],
            kwargs={"target_make": body.target_make, "target_model": body.target_model},
            queue="listing",
        )

    job.celery_task_id = celery_result.id
    job.status = "queued"
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/scrape/jobs", response_model=ScrapeJobListResponse)
async def list_jobs(
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    jobs, total = await get_jobs(db, page=page, page_size=page_size, status=status)
    return ScrapeJobListResponse(
        items=jobs, total=total, page=page,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/scrape/jobs/{job_id}", response_model=ScrapeJobOut)
async def get_job_detail(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM vehicles WHERE status = 'active') AS active,
            (SELECT COUNT(*) FROM vehicles) AS total,
            (SELECT MAX(created_at) FROM scrape_jobs WHERE job_type = 'full_scan' AND status = 'done') AS last_full_scan,
            (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size
    """))
    row = result.one()
    return {
        "active_vehicles": row.active,
        "total_vehicles": row.total,
        "last_full_scan": row.last_full_scan,
        "db_size": row.db_size,
    }
