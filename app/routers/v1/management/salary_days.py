from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models import SalaryMonth, SalaryDay
from app.schemas import SalaryDayCreate, SalaryDayUpdate, SalaryDayOut

router = APIRouter(prefix="/salary-days", tags=["Salary Days"])


def _recalculate_month(month: SalaryMonth, db: Session):
    """Recalculate taken_salary and remaining_salary from non-deleted salary days."""
    total = db.query(func.sum(SalaryDay.amount)).filter(
        SalaryDay.salary_month_id == month.id,
        SalaryDay.deleted == False,
    ).scalar() or 0
    month.taken_salary = total
    month.remaining_salary = month.salary - total


@router.post("/", response_model=SalaryDayOut, status_code=201)
def create_salary_day(data: SalaryDayCreate, db: Session = Depends(get_db)):
    month = db.query(SalaryMonth).filter(
        SalaryMonth.id == data.salary_month_id, SalaryMonth.deleted == False
    ).first()
    if not month:
        raise HTTPException(status_code=404, detail="Salary month not found")

    record = SalaryDay(**data.model_dump())
    db.add(record)
    db.flush()
    _recalculate_month(month, db)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[SalaryDayOut])
def list_salary_days(user_id: int = None, salary_month_id: int = None, db: Session = Depends(get_db)):
    query = db.query(SalaryDay).filter(SalaryDay.deleted == False)
    if user_id:
        query = query.filter(SalaryDay.user_id == user_id)
    if salary_month_id:
        query = query.filter(SalaryDay.salary_month_id == salary_month_id)
    return query.all()


@router.get("/{record_id}", response_model=SalaryDayOut)
def get_salary_day(record_id: int, db: Session = Depends(get_db)):
    record = db.query(SalaryDay).filter(
        SalaryDay.id == record_id, SalaryDay.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary day not found")
    return record


@router.patch("/{record_id}", response_model=SalaryDayOut)
def update_salary_day(record_id: int, data: SalaryDayUpdate, db: Session = Depends(get_db)):
    record = db.query(SalaryDay).filter(
        SalaryDay.id == record_id, SalaryDay.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary day not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(record, field, value)

    month = db.query(SalaryMonth).filter(SalaryMonth.id == record.salary_month_id).first()
    if month:
        _recalculate_month(month, db)

    db.commit()
    db.refresh(record)
    return record


@router.delete("/{record_id}", status_code=204)
def delete_salary_day(record_id: int, db: Session = Depends(get_db)):
    record = db.query(SalaryDay).filter(
        SalaryDay.id == record_id, SalaryDay.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary day not found")

    record.deleted = True
    db.flush()

    month = db.query(SalaryMonth).filter(SalaryMonth.id == record.salary_month_id).first()
    if month:
        _recalculate_month(month, db)

    db.commit()
