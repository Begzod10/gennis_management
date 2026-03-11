import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery = Celery(
    "gennis",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"],
)

celery.conf.beat_schedule = {
    "generate-monthly-salaries": {
        "task": "app.tasks.generate_monthly_salaries",
        "schedule": crontab(day_of_month=1, hour=0, minute=0),
    },
}
celery.conf.timezone = "Asia/Tashkent"
