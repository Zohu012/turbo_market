from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "turbo_market",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.scraper.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.scraper.tasks.fetch_detail": {"queue": "detail"},
        "app.scraper.tasks.scrape_make_task": {"queue": "listing"},
        "app.scraper.tasks.daily_full_scan": {"queue": "listing"},
        "app.scraper.tasks.on_demand_scan": {"queue": "listing"},
        "app.scraper.tasks.lifecycle_check_task": {"queue": "listing"},
    },
    beat_schedule={
        "daily-full-scan": {
            "task": "app.scraper.tasks.daily_full_scan",
            "schedule": crontab(
                hour=settings.full_scan_hour,
                minute=settings.full_scan_minute,
            ),
        },
    },
)
