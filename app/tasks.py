from datetime import date
import httpx
from .celery_app import celery
from .database import SessionLocal
from .models import User, SalaryMonth
from .config import settings


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
    """Send a Telegram message synchronously. Never raises — failures are silent."""
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        httpx.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5.0)
    except Exception:
        pass
