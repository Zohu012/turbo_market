from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ScrapeJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    triggered_by: str
    target_make: Optional[str]
    target_model: Optional[str]
    celery_task_id: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    listings_found: int
    listings_new: int
    listings_updated: int
    listings_deactivated: int
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TriggerRequest(BaseModel):
    job_type: str = "full_scan"  # full_scan | make_scan | lifecycle_check
    target_make: Optional[str] = None
    target_model: Optional[str] = None


class ScrapeJobListResponse(BaseModel):
    items: list[ScrapeJobOut]
    total: int
    page: int
    pages: int
