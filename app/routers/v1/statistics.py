from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import Optional

from ...database import get_gennis_db, get_turon_db
from ...external_models import gennis as G
from ...external_models import turon as T

router = APIRouter(prefix="/statistics", tags=["Statistics"])


# ─── helpers ──────────────────────────────────────────────────────────────────

def _month_year_filter_gennis(q, model, month, year):
    """Join CalendarMonth and apply month/year extract filters."""
    if month or year:
        q = q.join(G.CalendarMonth, G.CalendarMonth.id == model.calendar_month)
        if month:
            q = q.filter(extract("month", G.CalendarMonth.date) == month)
        if year:
            q = q.filter(extract("year", G.CalendarMonth.date) == year)
    return q


def _month_year_filter_turon(q, date_col, month, year):
    if month:
        q = q.filter(extract("month", date_col) == month)
    if year:
        q = q.filter(extract("year", date_col) == year)
    return q


# ─── Gennis ───────────────────────────────────────────────────────────────────

@router.get("/gennis/payments")
def gennis_payments(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_gennis_db),
):
    """Student payments in Gennis — total + breakdown by payment type."""
    rows = (
        db.query(
            G.PaymentTypes.name,
            func.coalesce(func.sum(G.StudentPayments.payment_sum), 0).label("total"),
        )
        .join(G.PaymentTypes, G.PaymentTypes.id == G.StudentPayments.payment_type_id)
    )
    rows = _month_year_filter_gennis(rows, G.StudentPayments, month, year)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/teacher-salaries")
def gennis_teacher_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_gennis_db),
):
    """Teacher salary transactions in Gennis — total + breakdown by payment type."""
    rows = (
        db.query(
            G.PaymentTypes.name,
            func.coalesce(func.sum(G.TeacherSalaries.payment_sum), 0).label("total"),
        )
        .join(G.PaymentTypes, G.PaymentTypes.id == G.TeacherSalaries.payment_type_id)
    )
    rows = _month_year_filter_gennis(rows, G.TeacherSalaries, month, year)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/staff-salaries")
def gennis_staff_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_gennis_db),
):
    """Staff salary transactions in Gennis — total + breakdown by payment type."""
    rows = (
        db.query(
            G.PaymentTypes.name,
            func.coalesce(func.sum(G.StaffSalaries.payment_sum), 0).label("total"),
        )
        .join(G.PaymentTypes, G.PaymentTypes.id == G.StaffSalaries.payment_type_id)
    )
    rows = _month_year_filter_gennis(rows, G.StaffSalaries, month, year)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/overheads")
def gennis_overheads(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_gennis_db),
):
    """Overhead expenses in Gennis — total + breakdown by overhead item name + by payment type."""
    # by item name
    item_rows = (
        db.query(
            G.Overhead.item_name,
            func.coalesce(func.sum(G.Overhead.item_sum), 0).label("total"),
        )
    )
    item_rows = _month_year_filter_gennis(item_rows, G.Overhead, month, year)
    item_rows = item_rows.group_by(G.Overhead.item_name).all()

    # by payment type
    type_rows = (
        db.query(
            G.PaymentTypes.name,
            func.coalesce(func.sum(G.Overhead.item_sum), 0).label("total"),
        )
        .join(G.PaymentTypes, G.PaymentTypes.id == G.Overhead.payment_type_id)
    )
    type_rows = _month_year_filter_gennis(type_rows, G.Overhead, month, year)
    type_rows = type_rows.group_by(G.PaymentTypes.name).all()

    grand_total = sum(r.total for r in item_rows)

    return {
        "total": grand_total,
        "by_item": [{"item": r.item_name, "total": r.total} for r in item_rows],
        "by_payment_type": [{"payment_type": r.name, "total": r.total} for r in type_rows],
    }


@router.get("/gennis/summary")
def gennis_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_gennis_db),
):
    """Full Gennis summary: payments, teacher salaries, staff salaries, overheads, remaining."""
    payments = gennis_payments(month, year, db)
    teacher_salaries = gennis_teacher_salaries(month, year, db)
    staff_salaries = gennis_staff_salaries(month, year, db)
    overheads = gennis_overheads(month, year, db)

    total_expenses = teacher_salaries["total"] + staff_salaries["total"] + overheads["total"]
    remaining = payments["total"] - total_expenses

    return {
        "payments": payments,
        "teacher_salaries": teacher_salaries,
        "staff_salaries": staff_salaries,
        "overheads": overheads,
        "total_expenses": total_expenses,
        "remaining": remaining,
    }


# ─── Turon ────────────────────────────────────────────────────────────────────

@router.get("/turon/payments")
def turon_payments(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_turon_db),
):
    """Student payments in Turon — total + breakdown by payment type."""
    rows = (
        db.query(
            T.PaymentTypes.name,
            func.coalesce(func.sum(T.StudentPayment.payment_sum), 0).label("total"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.StudentPayment.payment_type_id)
        .filter(T.StudentPayment.deleted == False, T.StudentPayment.status == True)
    )
    rows = _month_year_filter_turon(rows, T.StudentPayment.date, month, year)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/teacher-salaries")
def turon_teacher_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_turon_db),
):
    """Teacher salary payments in Turon — total + breakdown by payment type."""
    rows = (
        db.query(
            T.PaymentTypes.name,
            func.coalesce(func.sum(T.TeacherSalaryList.salary), 0).label("total"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.TeacherSalaryList.payment_id)
        .filter(T.TeacherSalaryList.deleted == False)
    )
    rows = _month_year_filter_turon(rows, T.TeacherSalaryList.date, month, year)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/staff-salaries")
def turon_staff_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_turon_db),
):
    """Staff (user) salary payments in Turon — total + breakdown by payment type."""
    rows = (
        db.query(
            T.PaymentTypes.name,
            func.coalesce(func.sum(T.UserSalaryList.salary), 0).label("total"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.UserSalaryList.payment_types_id)
        .filter(T.UserSalaryList.deleted == False)
    )
    rows = _month_year_filter_turon(rows, T.UserSalaryList.date, month, year)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/overheads")
def turon_overheads(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_turon_db),
):
    """Overhead expenses in Turon — total + breakdown by overhead type + by payment type."""
    # by overhead type
    type_rows = (
        db.query(
            T.OverheadType.name,
            func.coalesce(func.sum(T.Overhead.price), 0).label("total"),
        )
        .join(T.OverheadType, T.OverheadType.id == T.Overhead.type_id)
        .filter(T.Overhead.deleted == False)
    )
    type_rows = _month_year_filter_turon(type_rows, T.Overhead.created, month, year)
    type_rows = type_rows.group_by(T.OverheadType.name).all()

    # by payment type
    pay_rows = (
        db.query(
            T.PaymentTypes.name,
            func.coalesce(func.sum(T.Overhead.price), 0).label("total"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.Overhead.payment_id)
        .filter(T.Overhead.deleted == False)
    )
    pay_rows = _month_year_filter_turon(pay_rows, T.Overhead.created, month, year)
    pay_rows = pay_rows.group_by(T.PaymentTypes.name).all()

    grand_total = sum(r.total for r in type_rows)

    return {
        "total": grand_total,
        "by_overhead_type": [{"type": r.name, "total": r.total} for r in type_rows],
        "by_payment_type": [{"payment_type": r.name, "total": r.total} for r in pay_rows],
    }


@router.get("/turon/summary")
def turon_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_turon_db),
):
    """Full Turon summary: payments, teacher salaries, staff salaries, overheads, remaining."""
    payments = turon_payments(month, year, db)
    teacher_salaries = turon_teacher_salaries(month, year, db)
    staff_salaries = turon_staff_salaries(month, year, db)
    overheads = turon_overheads(month, year, db)

    total_expenses = teacher_salaries["total"] + staff_salaries["total"] + overheads["total"]
    remaining = payments["total"] - total_expenses

    return {
        "payments": payments,
        "teacher_salaries": teacher_salaries,
        "staff_salaries": staff_salaries,
        "overheads": overheads,
        "total_expenses": total_expenses,
        "remaining": remaining,
    }


# ─── Combined overview ────────────────────────────────────────────────────────

@router.get("/overview")
def overview(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    """Director dashboard: combined stats from both systems."""
    g = gennis_summary(month, year, gennis_db)
    t = turon_summary(month, year, turon_db)

    total_payments = g["payments"]["total"] + t["payments"]["total"]
    total_teacher_salaries = g["teacher_salaries"]["total"] + t["teacher_salaries"]["total"]
    total_staff_salaries = g["staff_salaries"]["total"] + t["staff_salaries"]["total"]
    total_overheads = g["overheads"]["total"] + t["overheads"]["total"]
    total_expenses = total_teacher_salaries + total_staff_salaries + total_overheads
    remaining = total_payments - total_expenses

    return {
        "period": {"month": month, "year": year},
        "gennis": g,
        "turon": t,
        "combined": {
            "total_payments": total_payments,
            "total_teacher_salaries": total_teacher_salaries,
            "total_staff_salaries": total_staff_salaries,
            "total_overheads": total_overheads,
            "total_expenses": total_expenses,
            "remaining": remaining,
        },
    }

