"""Accountant salary list — Ish haqi screen.

KPI cards + per-employee table for one Gennis location or Turon branch.

GET /api/v1/accountant/salaries
    ?system=gennis&location_id=4
    &month=5&year=2026
    &search=...
    &role=all|teacher|assistent|staff
    &status=all|pending|partial|paid
    &offset=0&limit=50

KPI cards:
- Jami hisoblangan : sum(total_salary)            for the month
- Bonuslar         : sum(bonus) + employee_count  (bonus = black_salary in Gennis,
                                                   not tracked in Turon → 0)
- Avans            : sum(taken_salary) for the month
- Qolgan           : sum(remaining_salary) for the month

Hours and hourly rate are NOT tracked in either source DB, so both come back as
None — frontend should render "-" in those columns.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, extract, func, literal, or_, union_all
from sqlalchemy.orm import Session

from app.database import get_gennis_db, get_turon_db
from app.external_models import gennis as G
from app.external_models import turon as T


router = APIRouter(prefix="/accountant", tags=["Accountant"])


# ── Response shape ────────────────────────────────────────────────────────────

RoleKind = Literal["teacher", "assistent", "staff"]
StatusKind = Literal["pending", "partial", "paid"]


class SalaryRow(BaseModel):
    id: int                       # source-system salary record id
    employee_id: int              # source-system user/teacher/assistant/staff id
    name: str
    role: RoleKind
    position: Optional[str]       # subject for teachers, profession for staff
    hours: Optional[int] = None   # not tracked in either DB
    rate_per_hour: Optional[int] = None
    base_salary: int
    bonus: int
    advance: int                  # money already taken
    total: int                    # base + bonus
    remaining: int
    status: StatusKind


class _Pagination(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool


class _KpiCards(BaseModel):
    accrued: int
    bonus_total: int
    bonus_employee_count: int
    advance: int
    remaining: int


class SalariesOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    month: int
    year: int
    kpis: _KpiCards
    rows: List[SalaryRow]
    pagination: _Pagination


# ── Status derivation ─────────────────────────────────────────────────────────

def _derive_status(total: int, advance: int) -> StatusKind:
    if total <= 0:
        return "paid"
    if advance >= total:
        return "paid"
    if advance > 0:
        return "partial"
    return "pending"


# ── Gennis ────────────────────────────────────────────────────────────────────

def _gennis_month_year_ids(db: Session, month: int, year: int) -> Optional[tuple[int, int]]:
    year_obj = datetime.strptime(str(year), "%Y")
    month_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")
    year_row = db.query(G.CalendarYear).filter(G.CalendarYear.date == year_obj).first()
    if not year_row:
        return None
    month_row = db.query(G.CalendarMonth).filter(
        G.CalendarMonth.date == month_obj,
        G.CalendarMonth.year_id == year_row.id,
    ).first()
    if not month_row:
        return None
    return month_row.id, year_row.id


def _gennis_teacher_rows(db: Session, location_id: int, month_id: int, year_id: int) -> List[SalaryRow]:
    # Black-salary bucket per teacher for the month
    black = (
        db.query(
            G.TeacherBlackSalary.teacher_id.label("tid"),
            func.coalesce(func.sum(G.TeacherBlackSalary.total_salary), 0).label("bonus"),
        )
        .filter(
            G.TeacherBlackSalary.location_id == location_id,
            G.TeacherBlackSalary.calendar_month == month_id,
            G.TeacherBlackSalary.calendar_year == year_id,
        )
        .group_by(G.TeacherBlackSalary.teacher_id)
        .subquery()
    )

    rows = (
        db.query(
            G.TeacherSalary,
            G.Users.name.label("user_name"),
            G.Users.surname.label("user_surname"),
            black.c.bonus,
        )
        .join(G.Teachers, G.Teachers.id == G.TeacherSalary.teacher_id)
        .join(G.Users, G.Users.id == G.Teachers.user_id)
        .outerjoin(black, black.c.tid == G.Teachers.id)
        .filter(
            G.TeacherSalary.location_id == location_id,
            G.TeacherSalary.calendar_month == month_id,
            G.TeacherSalary.calendar_year == year_id,
        )
        .all()
    )

    out: list[SalaryRow] = []
    for sal, user_name, user_surname, bonus in rows:
        base = int(sal.total_salary or 0)
        adv = int(sal.taken_money or 0)
        b = int(bonus or 0)
        total = base + b
        rem = max(0, total - adv)
        out.append(SalaryRow(
            id=sal.id,
            employee_id=sal.teacher_id,
            name=f"{user_name or ''} {user_surname or ''}".strip(),
            role="teacher",
            position="O'qituvchi",
            base_salary=base,
            bonus=b,
            advance=adv,
            total=total,
            remaining=rem,
            status=_derive_status(total, adv),
        ))
    return out


def _gennis_assistent_rows(db: Session, location_id: int, month_id: int, year_id: int) -> List[SalaryRow]:
    black = (
        db.query(
            G.AssistentBlackSalary.assistent_id.label("aid"),
            func.coalesce(func.sum(G.AssistentBlackSalary.total_salary), 0).label("bonus"),
        )
        .filter(
            G.AssistentBlackSalary.location_id == location_id,
            G.AssistentBlackSalary.calendar_month == month_id,
            G.AssistentBlackSalary.calendar_year == year_id,
        )
        .group_by(G.AssistentBlackSalary.assistent_id)
        .subquery()
    )

    rows = (
        db.query(
            G.AssistentSalary,
            G.Users.name.label("user_name"),
            G.Users.surname.label("user_surname"),
            black.c.bonus,
        )
        .join(G.Assistent, G.Assistent.id == G.AssistentSalary.assisten_id)
        .join(G.Users, G.Users.id == G.Assistent.user_id)
        .outerjoin(black, black.c.aid == G.Assistent.id)
        .filter(
            G.AssistentSalary.location_id == location_id,
            G.AssistentSalary.calendar_month == month_id,
            G.AssistentSalary.calendar_year == year_id,
        )
        .all()
    )

    out: list[SalaryRow] = []
    for sal, user_name, user_surname, bonus in rows:
        base = int(sal.total_salary or 0)
        adv = int(sal.taken_money or 0)
        b = int(bonus or 0)
        total = base + b
        rem = max(0, total - adv)
        out.append(SalaryRow(
            id=sal.id,
            employee_id=sal.assisten_id,
            name=f"{user_name or ''} {user_surname or ''}".strip(),
            role="assistent",
            position="Assistent",
            base_salary=base,
            bonus=b,
            advance=adv,
            total=total,
            remaining=rem,
            status=_derive_status(total, adv),
        ))
    return out


def _gennis_staff_rows(db: Session, location_id: int, month_id: int, year_id: int) -> List[SalaryRow]:
    rows = (
        db.query(
            G.StaffSalary,
            G.Users.name.label("user_name"),
            G.Users.surname.label("user_surname"),
            G.GennisProfessions.name.label("profession_name"),
        )
        .join(G.Staff, G.Staff.id == G.StaffSalary.staff_id)
        .join(G.Users, G.Users.id == G.Staff.user_id)
        .outerjoin(G.GennisProfessions, G.GennisProfessions.id == G.Staff.profession_id)
        .filter(
            G.StaffSalary.location_id == location_id,
            G.StaffSalary.calendar_month == month_id,
            G.StaffSalary.calendar_year == year_id,
        )
        .all()
    )

    out: list[SalaryRow] = []
    for sal, user_name, user_surname, profession in rows:
        base = int(sal.total_salary or 0)
        adv = int(sal.taken_money or 0)
        total = base  # no bonus bucket for staff in Gennis
        rem = max(0, total - adv)
        out.append(SalaryRow(
            id=sal.id,
            employee_id=sal.staff_id,
            name=f"{user_name or ''} {user_surname or ''}".strip(),
            role="staff",
            position=profession,
            base_salary=base,
            bonus=0,
            advance=adv,
            total=total,
            remaining=rem,
            status=_derive_status(total, adv),
        ))
    return out


def _gennis_collect(
    db: Session,
    location_id: int,
    month: int,
    year: int,
    role: str,
) -> List[SalaryRow]:
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        return []
    month_id, year_id = ids

    out: list[SalaryRow] = []
    if role in ("all", "teacher"):
        out += _gennis_teacher_rows(db, location_id, month_id, year_id)
    if role in ("all", "assistent"):
        out += _gennis_assistent_rows(db, location_id, month_id, year_id)
    if role in ("all", "staff"):
        out += _gennis_staff_rows(db, location_id, month_id, year_id)
    return out


# ── Turon ─────────────────────────────────────────────────────────────────────

def _turon_teacher_rows(db: Session, branch_id: int, month: int, year: int) -> List[SalaryRow]:
    rows = (
        db.query(
            T.TeacherSalary,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
        )
        .select_from(T.TeacherSalary)
        .join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id)
        .join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id)
        .filter(
            T.TeacherSalary.branch_id == branch_id,
            extract("month", T.TeacherSalary.month_date) == month,
            extract("year", T.TeacherSalary.month_date) == year,
        )
        .all()
    )

    out: list[SalaryRow] = []
    for sal, user_name, user_surname in rows:
        base = int(sal.total_salary or 0)
        adv = int(sal.taken_salary or 0)
        rem = int(sal.remaining_salary or max(0, base - adv))
        out.append(SalaryRow(
            id=sal.id,
            employee_id=sal.teacher_id,
            name=f"{user_name or ''} {user_surname or ''}".strip(),
            role="teacher",
            position="O'qituvchi",
            base_salary=base,
            bonus=0,
            advance=adv,
            total=base,
            remaining=rem,
            status=_derive_status(base, adv),
        ))
    return out


def _turon_staff_rows(db: Session, branch_id: int, month: int, year: int) -> List[SalaryRow]:
    rows = (
        db.query(
            T.UserSalary,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
        )
        .select_from(T.UserSalary)
        .join(T.CustomUser, T.CustomUser.id == T.UserSalary.user_id)
        .filter(
            T.CustomUser.branch_id == branch_id,
            extract("month", T.UserSalary.date) == month,
            extract("year", T.UserSalary.date) == year,
        )
        .all()
    )

    out: list[SalaryRow] = []
    for sal, user_name, user_surname in rows:
        base = int(sal.total_salary or 0)
        adv = int(sal.taken_salary or 0)
        rem = int(sal.remaining_salary or max(0, base - adv))
        out.append(SalaryRow(
            id=sal.id,
            employee_id=sal.user_id,
            name=f"{user_name or ''} {user_surname or ''}".strip(),
            role="staff",
            position=None,
            base_salary=base,
            bonus=0,
            advance=adv,
            total=base,
            remaining=rem,
            status=_derive_status(base, adv),
        ))
    return out


def _turon_collect(
    db: Session,
    branch_id: int,
    month: int,
    year: int,
    role: str,
) -> List[SalaryRow]:
    out: list[SalaryRow] = []
    if role in ("all", "teacher"):
        out += _turon_teacher_rows(db, branch_id, month, year)
    if role in ("all", "staff"):
        out += _turon_staff_rows(db, branch_id, month, year)
    # Turon has no Assistent bucket — silently empty when role == "assistent"
    return out


# ── KPIs & filtering ──────────────────────────────────────────────────────────

def _build_kpis(rows: List[SalaryRow]) -> _KpiCards:
    accrued = sum(r.total for r in rows)
    bonus_total = sum(r.bonus for r in rows)
    bonus_employees = sum(1 for r in rows if r.bonus > 0)
    advance = sum(r.advance for r in rows)
    remaining = sum(r.remaining for r in rows)
    return _KpiCards(
        accrued=accrued,
        bonus_total=bonus_total,
        bonus_employee_count=bonus_employees,
        advance=advance,
        remaining=remaining,
    )


def _filter_rows(
    rows: List[SalaryRow],
    search: Optional[str],
    status: str,
) -> List[SalaryRow]:
    out = rows
    if search:
        s = search.lower()
        out = [r for r in out if s in r.name.lower() or s in (r.position or "").lower()]
    if status != "all":
        out = [r for r in out if r.status == status]
    return out


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/salaries", response_model=SalariesOut)
def accountant_salaries(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Defaults to current month"),
    year: Optional[int] = Query(None, ge=2000, description="Defaults to current year"),
    search: Optional[str] = Query(None, description="Match name or position"),
    role: Literal["all", "teacher", "assistent", "staff"] = Query("all"),
    status: Literal["all", "pending", "partial", "paid"] = Query("all"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    today = date.today()
    m = month or today.month
    y = year or today.year

    if system == "gennis":
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id is required when system=gennis")
        rows = _gennis_collect(gennis_db, location_id, m, y, role)
        scope_id = location_id
    else:
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required when system=turon")
        rows = _turon_collect(turon_db, branch_id, m, y, role)
        scope_id = branch_id

    rows = _filter_rows(rows, search, status)
    rows.sort(key=lambda r: (r.name.lower(), r.id))
    total = len(rows)
    page = rows[offset : offset + limit]

    return SalariesOut(
        system=system,
        scope_id=scope_id,
        month=m,
        year=y,
        kpis=_build_kpis(rows),
        rows=page,
        pagination=_Pagination(
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < total,
        ),
    )
