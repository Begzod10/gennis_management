"""Accountant student list — table view for one Gennis location or Turon branch.

Mirrors the columns shown on the Buxgalteriya `O'quvchilar` screen:
F.I.Sh, Sinf, Oylik, Chegirma, Holat, Amal.

GET /api/v1/accountant/students
    ?system=gennis&location_id=4
    &month=5&year=2026
    &search=...
    &status=all|active|partial|debtor
    &offset=0&limit=50

`system=turon` uses `branch_id` instead of `location_id`. `month`/`year`
default to today.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import Session

from app.database import get_gennis_db, get_turon_db
from app.external_models import gennis as G
from app.external_models import turon as T


router = APIRouter(prefix="/accountant", tags=["Accountant"])


# ── Response shape ────────────────────────────────────────────────────────────

class StudentRow(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    class_label: Optional[str] = None
    monthly: int        # total billable for the month (Oylik)
    payment: int        # paid so far this month
    remaining_debt: int
    discount: int       # discount amount in soum
    discount_pct: int   # 0-100, derived from discount/monthly when monthly > 0
    status: Literal["active", "partial", "debtor"]


class _Pagination(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool


class StudentsOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    month: int
    year: int
    students: List[StudentRow]
    totals: dict
    pagination: _Pagination


# ── Status derivation ─────────────────────────────────────────────────────────

def _derive_status(total_debt: int, remaining_debt: int) -> str:
    """Map (total_debt, remaining_debt) → 'active' | 'partial' | 'debtor'.

    - active : nothing owed this month (debt fully cleared or month has no charge)
    - partial: some paid, some still owed
    - debtor : nothing paid and there is unpaid debt
    """
    if remaining_debt <= 0:
        return "active"
    paid = max(0, total_debt - remaining_debt)
    if paid > 0:
        return "partial"
    return "debtor"


def _filter_by_status(rows: list[StudentRow], status: str) -> list[StudentRow]:
    if status == "all":
        return rows
    return [r for r in rows if r.status == status]


# ── Gennis ────────────────────────────────────────────────────────────────────

def _gennis_month_year_ids(db: Session, month: int, year: int) -> tuple[int, int]:
    year_obj = datetime.strptime(str(year), "%Y")
    month_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")

    year_row = db.query(G.CalendarYear).filter(G.CalendarYear.date == year_obj).first()
    if not year_row:
        raise HTTPException(status_code=404, detail=f"Calendar year {year} not found")
    month_row = db.query(G.CalendarMonth).filter(
        G.CalendarMonth.date == month_obj,
        G.CalendarMonth.year_id == year_row.id,
    ).first()
    if not month_row:
        raise HTTPException(status_code=404, detail=f"Calendar month {year}-{month} not found")
    return month_row.id, year_row.id


def _gennis_students(
    db: Session,
    location_id: int,
    month: int,
    year: int,
    search: Optional[str],
    status: str,
    offset: int,
    limit: int,
) -> StudentsOut:
    month_id, year_id = _gennis_month_year_ids(db, month, year)

    # Aggregate per student across all their groups for the month.
    agg = (
        db.query(
            G.AttendanceHistoryStudent.student_id.label("sid"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.total_debt), 0).label("total_debt"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.payment), 0).label("payment"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.remaining_debt), 0).label("remaining_debt"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.total_discount), 0).label("discount"),
            func.string_agg(G.Groups.name, ", ").label("group_names"),
        )
        .outerjoin(G.Groups, G.Groups.id == G.AttendanceHistoryStudent.group_id)
        .filter(
            G.AttendanceHistoryStudent.location_id == location_id,
            G.AttendanceHistoryStudent.calendar_month == month_id,
            G.AttendanceHistoryStudent.calendar_year == year_id,
        )
        .group_by(G.AttendanceHistoryStudent.student_id)
        .subquery()
    )

    q = (
        db.query(
            G.Students.id.label("student_id"),
            G.Users.name.label("user_name"),
            G.Users.surname.label("user_surname"),
            agg.c.total_debt,
            agg.c.payment,
            agg.c.remaining_debt,
            agg.c.discount,
            agg.c.group_names,
        )
        .join(G.Users, G.Users.id == G.Students.user_id)
        .join(agg, agg.c.sid == G.Students.id)
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            G.Users.name.ilike(like),
            G.Users.surname.ilike(like),
        ))

    rows = q.order_by(G.Users.surname.asc(), G.Users.name.asc()).all()

    students: list[StudentRow] = []
    for r in rows:
        total_debt = int(r.total_debt or 0)
        payment = int(r.payment or 0)
        remaining_debt = int(r.remaining_debt or 0)
        discount = int(r.discount or 0)
        # discount %: ratio of discount to original monthly fee (before discount applied)
        original = total_debt + discount
        discount_pct = round(discount * 100 / original) if original > 0 else 0
        students.append(StudentRow(
            id=r.student_id,
            name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            phone=None,
            class_label=r.group_names,
            monthly=total_debt,
            payment=payment,
            remaining_debt=remaining_debt,
            discount=discount,
            discount_pct=discount_pct,
            status=_derive_status(total_debt, remaining_debt),
        ))

    students = _filter_by_status(students, status)
    total = len(students)
    page = students[offset : offset + limit]

    return StudentsOut(
        system="gennis",
        scope_id=location_id,
        month=month,
        year=year,
        students=page,
        totals=_totals(students),
        pagination=_Pagination(
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < total,
        ),
    )


# ── Turon ─────────────────────────────────────────────────────────────────────

def _turon_students(
    db: Session,
    branch_id: int,
    month: int,
    year: int,
    search: Optional[str],
    status: str,
    offset: int,
    limit: int,
) -> StudentsOut:
    # Aggregate AttendancePerMonth per student for the given month/year, restricted to branch.
    agg = (
        db.query(
            T.AttendancePerMonth.student_id.label("sid"),
            func.coalesce(func.sum(T.AttendancePerMonth.total_debt), 0).label("total_debt"),
            func.coalesce(func.sum(T.AttendancePerMonth.payment), 0).label("payment"),
            func.coalesce(func.sum(T.AttendancePerMonth.remaining_debt), 0).label("remaining_debt"),
            func.coalesce(func.sum(T.AttendancePerMonth.discount), 0).label("discount"),
        )
        .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .filter(
            T.CustomUser.branch_id == branch_id,
            extract("month", T.AttendancePerMonth.month_date) == month,
            extract("year", T.AttendancePerMonth.month_date) == year,
        )
        .group_by(T.AttendancePerMonth.student_id)
        .subquery()
    )

    q = (
        db.query(
            T.Student.id.label("student_id"),
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
            T.CustomUser.phone.label("user_phone"),
            T.ClassNumber.number.label("class_number"),
            agg.c.total_debt,
            agg.c.payment,
            agg.c.remaining_debt,
            agg.c.discount,
        )
        .select_from(T.Student)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .outerjoin(T.ClassNumber, T.ClassNumber.id == T.Student.class_number_id)
        .join(agg, agg.c.sid == T.Student.id)
        .filter(T.CustomUser.branch_id == branch_id)
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            T.CustomUser.name.ilike(like),
            T.CustomUser.surname.ilike(like),
            T.CustomUser.phone.ilike(like),
        ))

    rows = q.order_by(T.CustomUser.surname.asc(), T.CustomUser.name.asc()).all()

    students: list[StudentRow] = []
    for r in rows:
        total_debt = int(r.total_debt or 0)
        payment = int(r.payment or 0)
        remaining_debt = int(r.remaining_debt or 0)
        discount = int(r.discount or 0)
        original = total_debt + discount
        discount_pct = round(discount * 100 / original) if original > 0 else 0
        students.append(StudentRow(
            id=r.student_id,
            name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            phone=r.user_phone,
            class_label=str(r.class_number) if r.class_number is not None else None,
            monthly=total_debt,
            payment=payment,
            remaining_debt=remaining_debt,
            discount=discount,
            discount_pct=discount_pct,
            status=_derive_status(total_debt, remaining_debt),
        ))

    students = _filter_by_status(students, status)
    total = len(students)
    page = students[offset : offset + limit]

    return StudentsOut(
        system="turon",
        scope_id=branch_id,
        month=month,
        year=year,
        students=page,
        totals=_totals(students),
        pagination=_Pagination(
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < total,
        ),
    )


# ── Totals helper ─────────────────────────────────────────────────────────────

def _totals(rows: list[StudentRow]) -> dict:
    return {
        "count": len(rows),
        "monthly": sum(r.monthly for r in rows),
        "payment": sum(r.payment for r in rows),
        "remaining_debt": sum(r.remaining_debt for r in rows),
        "discount": sum(r.discount for r in rows),
        "active": sum(1 for r in rows if r.status == "active"),
        "partial": sum(1 for r in rows if r.status == "partial"),
        "debtor": sum(1 for r in rows if r.status == "debtor"),
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/students", response_model=StudentsOut)
def accountant_students(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Defaults to current month"),
    year: Optional[int] = Query(None, ge=2000, description="Defaults to current year"),
    search: Optional[str] = Query(None, description="Filter by name/surname/phone"),
    status: Literal["all", "active", "partial", "debtor"] = Query("all"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    today = date.today()
    month = month or today.month
    year = year or today.year

    if system == "gennis":
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id is required when system=gennis")
        return _gennis_students(gennis_db, location_id, month, year, search, status, offset, limit)
    else:
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required when system=turon")
        return _turon_students(turon_db, branch_id, month, year, search, status, offset, limit)
