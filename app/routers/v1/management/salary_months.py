from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
from app.database import get_db
from app.models import SalaryMonth
from app.schemas import SalaryMonthCreate, SalaryMonthUpdate, SalaryMonthOut

router = APIRouter(prefix="/salary-months", tags=["Salary Months"])


@router.post("/", response_model=SalaryMonthOut, status_code=201)
def create_salary_month(data: SalaryMonthCreate, db: Session = Depends(get_db)):
    record = SalaryMonth(
        salary=data.salary,
        user_id=data.user_id,
        date=data.date,
        taken_salary=0,
        remaining_salary=data.salary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/", response_model=List[SalaryMonthOut])
def list_salary_months(
    user_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(SalaryMonth).filter(SalaryMonth.deleted == False)
    if user_id:
        query = query.filter(SalaryMonth.user_id == user_id)
    if date_from:
        query = query.filter(SalaryMonth.date >= date_from)
    if date_to:
        query = query.filter(SalaryMonth.date <= date_to)
    if month:
        query = query.filter(SalaryMonth.date.between(
            date(year or date.today().year, month, 1),
            date(year or date.today().year, month, 28),
        ))
    if year and not month:
        query = query.filter(SalaryMonth.date >= date(year, 1, 1)).filter(
            SalaryMonth.date <= date(year, 12, 31)
        )
    return query.order_by(SalaryMonth.date.desc()).all()


@router.get("/{record_id}", response_model=SalaryMonthOut)
def get_salary_month(record_id: int, db: Session = Depends(get_db)):
    record = db.query(SalaryMonth).filter(
        SalaryMonth.id == record_id, SalaryMonth.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary month not found")
    return record


@router.patch("/{record_id}", response_model=SalaryMonthOut)
def update_salary_month(record_id: int, data: SalaryMonthUpdate, db: Session = Depends(get_db)):
    record = db.query(SalaryMonth).filter(
        SalaryMonth.id == record_id, SalaryMonth.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary month not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(record, field, value)
    # recalculate remaining when salary changes
    if data.salary is not None:
        record.remaining_salary = record.salary - record.taken_salary
    db.commit()
    db.refresh(record)
    return record


@router.delete("/{record_id}", status_code=204)
def delete_salary_month(record_id: int, db: Session = Depends(get_db)):
    record = db.query(SalaryMonth).filter(
        SalaryMonth.id == record_id, SalaryMonth.deleted == False
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Salary month not found")
    record.deleted = True
    db.commit()
