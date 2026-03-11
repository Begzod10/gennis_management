from datetime import date
from .celery_app import celery
from .database import SessionLocal
from .models import User, SalaryMonth


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
