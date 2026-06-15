import logging
from datetime import date
import httpx
from .celery_app import celery
from .database import SessionLocal
from .models import User, SalaryMonth
from .config import settings

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.generate_monthly_salaries")
def generate_monthly_salaries():
    db = SessionLocal()
    try:
        period = date.today().replace(day=1)

        users = db.query(User).filter(
            User.deleted == False,
            User.is_active == True,
            User.salary != None,
            User.salary > 0,
        ).all()

        created = 0
        for user in users:
            exists = db.query(SalaryMonth).filter(
                SalaryMonth.user_id == user.id,
                SalaryMonth.date == period,
                SalaryMonth.deleted == False,
            ).first()
            if not exists:
                db.add(SalaryMonth(
                    user_id=user.id,
                    salary=user.salary,
                    taken_salary=0,
                    remaining_salary=user.salary,
                    date=period,
                ))
                created += 1

        db.commit()
        return {"created": created, "period": str(period)}
    finally:
        db.close()


@celery.task(name="app.tasks.send_telegram_notification", max_retries=2)
def send_telegram_notification(chat_id: int, text: str):
    """Send a Telegram message synchronously. Logs failures, never raises."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("telegram skip: TELEGRAM_BOT_TOKEN is empty")
        return
    if not chat_id:
        logger.warning("telegram skip: chat_id is empty")
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    proxy = settings.TELEGRAM_PROXY or None
    try:
        with httpx.Client(timeout=5.0, proxy=proxy) as client:
            resp = client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        if resp.status_code != 200:
            snippet = resp.text[:300].replace("\n", " ")
            logger.warning(
                "telegram send failed chat_id=%s status=%s body=%s",
                chat_id, resp.status_code, snippet,
            )
        else:
            logger.info("telegram sent chat_id=%s len=%s", chat_id, len(text))
    except Exception as exc:
        logger.warning("telegram transport error chat_id=%s err=%s", chat_id, exc)
