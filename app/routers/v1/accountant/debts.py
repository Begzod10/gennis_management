"""Accountant debts — Buxgalteriya `Qarzlar` screen.

Three tabs, switchable with the `tab` query param:

- `students` (O'quvchi qarzlari) — students with unpaid balance for the month.
- `given`    (Berilgan qarzlar)  — branch loans the school issued (direction=out).
- `taken`    (Olingan qarzlar)   — branch loans the school received (direction=in).

GET /api/v1/accountant/debts
    ?system=gennis&location_id=4
    &tab=students|given|taken
    &month=5&year=2026     (used by `students` only; defaults to today)
    &status=...            (loans only: active|settled|cancelled|all)
    &search=...
    &offset=0&limit=50

`system=turon` swaps `location_id` for `branch_id`.
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


# ── Response shapes ───────────────────────────────────────────────────────────

class StudentDebtRow(BaseModel):
    student_id: int
    name: str
    group_label: Optional[str] = None       # Guruh — group/class names
    debt_amount: int                        # Qarz miqdori — sum of remaining_debt
    days_overdue: int                       # Kechikkan kunlar
    discount_status: str                    # Chegirma holati — "active" | "cancelled" | "none"
    discount_amount: int
    last_payment_date: Optional[str] = None # Oxirgi to'lov
    status: Literal["overdue", "pending"]   # Status — Kechikkan | Kutilmoqda


class LoanDebtRow(BaseModel):
    id: int
    management_id: Optional[int] = None
    counterparty: str                       # name + surname (+ phone if no name)
    counterparty_phone: Optional[str] = None
    direction: Literal["out", "in"]
    principal_amount: int
    issued_date: Optional[str] = None
    due_date: Optional[str] = None
    settled_date: Optional[str] = None
    days_overdue: int                       # 0 when settled or not yet due
    reason: Optional[str] = None
    status: str                             # "active" | "settled" | "cancelled" | "overdue"


class _Pagination(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool


class _StudentTotals(BaseModel):
    count: int
    debt_amount: int
    overdue_count: int
    pending_count: int


class _LoanTotals(BaseModel):
    count: int
    principal_total: int
    active_total: int
    settled_total: int
    cancelled_total: int


class StudentDebtsOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    tab: Literal["students"]
    month: int
    year: int
    rows: List[StudentDebtRow]
    totals: _StudentTotals
    pagination: _Pagination


class LoanDebtsOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    tab: Literal["given", "taken"]
    rows: List[LoanDebtRow]
    totals: _LoanTotals
    pagination: _Pagination


# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    first_next = date(year, month + 1, 1)
    return date.fromordinal(first_next.toordinal() - 1)


def _days_between(earlier: Optional[date], later: date) -> int:
    if not earlier:
        return 0
    return max(0, (later - earlier).days)


def _student_status(days_overdue: int) -> Literal["overdue", "pending"]:
    # Kechikkan = overdue, Kutilmoqda = pending. Anything older than two weeks counts as overdue.
    return "overdue" if days_overdue >= 14 else "pending"


# ── Gennis: students with debt ────────────────────────────────────────────────

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


def _gennis_students_with_debt(
    db: Session, location_id: int, month: int, year: int,
    search: Optional[str], offset: int, limit: int,
) -> StudentDebtsOut:
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        raise HTTPException(404, detail=f"Calendar month {year}-{month} not found")
    month_id, year_id = ids

    agg = (
        db.query(
            G.AttendanceHistoryStudent.student_id.label("sid"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.remaining_debt), 0).label("debt"),
            func.coalesce(func.sum(G.AttendanceHistoryStudent.total_discount), 0).label("discount"),
            func.string_agg(G.Groups.name, ", ").label("groups"),
        )
        .outerjoin(G.Groups, G.Groups.id == G.AttendanceHistoryStudent.group_id)
        .filter(
            G.AttendanceHistoryStudent.location_id == location_id,
            G.AttendanceHistoryStudent.calendar_month == month_id,
            G.AttendanceHistoryStudent.calendar_year == year_id,
            G.AttendanceHistoryStudent.remaining_debt > 0,
        )
        .group_by(G.AttendanceHistoryStudent.student_id)
        .subquery()
    )

    # Latest payment date per student
    last_pay_sub = (
        db.query(
            G.StudentPayments.student_id.label("sid"),
            func.max(G.CalendarDay.date).label("last_paid"),
        )
        .join(G.CalendarDay, G.CalendarDay.id == G.StudentPayments.calendar_day)
        .filter(
            G.StudentPayments.location_id == location_id,
            G.StudentPayments.payment == True,
        )
        .group_by(G.StudentPayments.student_id)
        .subquery()
    )

    q = (
        db.query(
            G.Students.id.label("student_id"),
            G.Users.name.label("first_name"),
            G.Users.surname.label("last_name"),
            agg.c.debt,
            agg.c.discount,
            agg.c.groups,
            last_pay_sub.c.last_paid,
        )
        .select_from(G.Students)
        .join(G.Users, G.Users.id == G.Students.user_id)
        .join(agg, agg.c.sid == G.Students.id)
        .outerjoin(last_pay_sub, last_pay_sub.c.sid == G.Students.id)
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(G.Users.name.ilike(like), G.Users.surname.ilike(like)))

    rows = q.order_by(G.Users.surname.asc(), G.Users.name.asc()).all()

    today = date.today()
    month_end = _last_day_of_month(year, month)

    out: list[StudentDebtRow] = []
    for r in rows:
        last_paid = r.last_paid.date() if isinstance(r.last_paid, datetime) else r.last_paid
        days_overdue = _days_between(month_end, today) if today > month_end else 0
        discount = int(r.discount or 0)
        discount_status = (
            "active" if discount > 0
            else "cancelled" if discount < 0
            else "none"
        )
        out.append(StudentDebtRow(
            student_id=r.student_id,
            name=f"{r.first_name or ''} {r.last_name or ''}".strip(),
            group_label=r.groups,
            debt_amount=int(r.debt or 0),
            days_overdue=days_overdue,
            discount_status=discount_status,
            discount_amount=discount,
            last_payment_date=last_paid.strftime("%Y-%m-%d") if last_paid else None,
            status=_student_status(days_overdue),
        ))

    return _student_response("gennis", location_id, month, year, out, offset, limit)


# ── Turon: students with debt ─────────────────────────────────────────────────

def _turon_students_with_debt(
    db: Session, branch_id: int, month: int, year: int,
    search: Optional[str], offset: int, limit: int,
) -> StudentDebtsOut:
    agg = (
        db.query(
            T.AttendancePerMonth.student_id.label("sid"),
            func.coalesce(func.sum(T.AttendancePerMonth.remaining_debt), 0).label("debt"),
            func.coalesce(func.sum(T.AttendancePerMonth.discount), 0).label("discount"),
        )
        .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .filter(
            T.CustomUser.branch_id == branch_id,
            T.AttendancePerMonth.remaining_debt > 0,
            extract("month", T.AttendancePerMonth.month_date) == month,
            extract("year", T.AttendancePerMonth.month_date) == year,
        )
        .group_by(T.AttendancePerMonth.student_id)
        .subquery()
    )

    last_pay_sub = (
        db.query(
            T.StudentPayment.student_id.label("sid"),
            func.max(T.StudentPayment.date).label("last_paid"),
        )
        .filter(
            T.StudentPayment.branch_id == branch_id,
            T.StudentPayment.status == True,
            T.StudentPayment.deleted == False,
        )
        .group_by(T.StudentPayment.student_id)
        .subquery()
    )

    q = (
        db.query(
            T.Student.id.label("student_id"),
            T.CustomUser.name.label("first_name"),
            T.CustomUser.surname.label("last_name"),
            T.ClassNumber.number.label("class_number"),
            agg.c.debt,
            agg.c.discount,
            last_pay_sub.c.last_paid,
        )
        .select_from(T.Student)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .outerjoin(T.ClassNumber, T.ClassNumber.id == T.Student.class_number_id)
        .join(agg, agg.c.sid == T.Student.id)
        .outerjoin(last_pay_sub, last_pay_sub.c.sid == T.Student.id)
        .filter(T.CustomUser.branch_id == branch_id)
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(T.CustomUser.name.ilike(like), T.CustomUser.surname.ilike(like)))

    rows = q.order_by(T.CustomUser.surname.asc(), T.CustomUser.name.asc()).all()

    today = date.today()
    month_end = _last_day_of_month(year, month)

    out: list[StudentDebtRow] = []
    for r in rows:
        last_paid = r.last_paid
        days_overdue = _days_between(month_end, today) if today > month_end else 0
        discount = int(r.discount or 0)
        discount_status = (
            "active" if discount > 0
            else "cancelled" if discount < 0
            else "none"
        )
        out.append(StudentDebtRow(
            student_id=r.student_id,
            name=f"{r.first_name or ''} {r.last_name or ''}".strip(),
            group_label=str(r.class_number) if r.class_number is not None else None,
            debt_amount=int(r.debt or 0),
            days_overdue=days_overdue,
            discount_status=discount_status,
            discount_amount=discount,
            last_payment_date=last_paid.strftime("%Y-%m-%d") if last_paid else None,
            status=_student_status(days_overdue),
        ))

    return _student_response("turon", branch_id, month, year, out, offset, limit)


def _student_response(
    system: Literal["gennis", "turon"], scope_id: int,
    month: int, year: int,
    rows: list[StudentDebtRow], offset: int, limit: int,
) -> StudentDebtsOut:
    total = len(rows)
    overdue = sum(1 for r in rows if r.status == "overdue")
    pending = sum(1 for r in rows if r.status == "pending")
    debt_sum = sum(r.debt_amount for r in rows)
    page = rows[offset : offset + limit]
    return StudentDebtsOut(
        system=system,
        scope_id=scope_id,
        tab="students",
        month=month, year=year,
        rows=page,
        totals=_StudentTotals(
            count=total,
            debt_amount=debt_sum,
            overdue_count=overdue,
            pending_count=pending,
        ),
        pagination=_Pagination(
            total=total, offset=offset, limit=limit,
            has_more=(offset + limit) < total,
        ),
    )


# ── Loans (given / taken) — common ────────────────────────────────────────────

def _loan_status(status: str, due_date: Optional[date], today: date) -> str:
    """`active` loans past their `due_date` are reported as `overdue` for the UI."""
    if status == "active" and due_date and today > due_date:
        return "overdue"
    return status


def _loan_response(
    system: Literal["gennis", "turon"], scope_id: int, tab: Literal["given", "taken"],
    rows: list[LoanDebtRow], offset: int, limit: int,
) -> LoanDebtsOut:
    total = len(rows)
    principal_total = sum(r.principal_amount for r in rows)
    active_total = sum(r.principal_amount for r in rows if r.status in ("active", "overdue"))
    settled_total = sum(r.principal_amount for r in rows if r.status == "settled")
    cancelled_total = sum(r.principal_amount for r in rows if r.status == "cancelled")
    page = rows[offset : offset + limit]
    return LoanDebtsOut(
        system=system,
        scope_id=scope_id,
        tab=tab,
        rows=page,
        totals=_LoanTotals(
            count=total,
            principal_total=principal_total,
            active_total=active_total,
            settled_total=settled_total,
            cancelled_total=cancelled_total,
        ),
        pagination=_Pagination(
            total=total, offset=offset, limit=limit,
            has_more=(offset + limit) < total,
        ),
    )


def _gennis_loans(
    db: Session, location_id: int, direction: str,
    status: str, search: Optional[str], offset: int, limit: int,
    tab: Literal["given", "taken"],
) -> LoanDebtsOut:
    q = db.query(G.GennisBranchLoan).filter(
        G.GennisBranchLoan.location_id == location_id,
        G.GennisBranchLoan.direction == direction,
        G.GennisBranchLoan.deleted == False,
    )
    if status != "all":
        q = q.filter(G.GennisBranchLoan.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            G.GennisBranchLoan.counterparty_name.ilike(like),
            G.GennisBranchLoan.counterparty_surname.ilike(like),
            G.GennisBranchLoan.counterparty_phone.ilike(like),
            G.GennisBranchLoan.reason.ilike(like),
        ))

    today = date.today()
    items = q.order_by(G.GennisBranchLoan.issued_date.desc()).all()

    rows: list[LoanDebtRow] = []
    for loan in items:
        issued = loan.issued_date.date() if isinstance(loan.issued_date, datetime) else loan.issued_date
        due = loan.due_date.date() if isinstance(loan.due_date, datetime) else loan.due_date
        settled = loan.settled_date.date() if isinstance(loan.settled_date, datetime) else loan.settled_date
        derived_status = _loan_status(loan.status or "active", due, today)
        days_overdue = _days_between(due, today) if derived_status == "overdue" else 0
        rows.append(LoanDebtRow(
            id=loan.id,
            management_id=loan.management_id,
            counterparty=" ".join(filter(None, [loan.counterparty_name, loan.counterparty_surname])).strip()
                         or (loan.counterparty_phone or ""),
            counterparty_phone=loan.counterparty_phone,
            direction=loan.direction,
            principal_amount=int(loan.principal_amount or 0),
            issued_date=issued.strftime("%Y-%m-%d") if issued else None,
            due_date=due.strftime("%Y-%m-%d") if due else None,
            settled_date=settled.strftime("%Y-%m-%d") if settled else None,
            days_overdue=days_overdue,
            reason=loan.reason,
            status=derived_status,
        ))

    return _loan_response("gennis", location_id, tab, rows, offset, limit)


def _turon_loans(
    db: Session, branch_id: int, direction: str,
    status: str, search: Optional[str], offset: int, limit: int,
    tab: Literal["given", "taken"],
) -> LoanDebtsOut:
    q = db.query(T.TuronBranchLoan).filter(
        T.TuronBranchLoan.branch_id == branch_id,
        T.TuronBranchLoan.direction == direction,
        T.TuronBranchLoan.deleted == False,
    )
    if status != "all":
        q = q.filter(T.TuronBranchLoan.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            T.TuronBranchLoan.counterparty_name.ilike(like),
            T.TuronBranchLoan.counterparty_surname.ilike(like),
            T.TuronBranchLoan.counterparty_phone.ilike(like),
            T.TuronBranchLoan.reason.ilike(like),
        ))

    today = date.today()
    items = q.order_by(T.TuronBranchLoan.issued_date.desc()).all()

    rows: list[LoanDebtRow] = []
    for loan in items:
        issued = loan.issued_date
        due = loan.due_date
        settled = loan.settled_date
        derived_status = _loan_status(loan.status or "active", due, today)
        days_overdue = _days_between(due, today) if derived_status == "overdue" else 0
        rows.append(LoanDebtRow(
            id=loan.id,
            management_id=loan.management_id,
            counterparty=" ".join(filter(None, [loan.counterparty_name, loan.counterparty_surname])).strip()
                         or (loan.counterparty_phone or ""),
            counterparty_phone=loan.counterparty_phone,
            direction=loan.direction,
            principal_amount=int(loan.principal_amount or 0),
            issued_date=issued.strftime("%Y-%m-%d") if issued else None,
            due_date=due.strftime("%Y-%m-%d") if due else None,
            settled_date=settled.strftime("%Y-%m-%d") if settled else None,
            days_overdue=days_overdue,
            reason=loan.reason,
            status=derived_status,
        ))

    return _loan_response("turon", branch_id, tab, rows, offset, limit)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/debts", response_model=None)
def accountant_debts(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    tab: Literal["students", "given", "taken"] = Query("students", description="Tab to render"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Used by tab=students; default current month"),
    year: Optional[int] = Query(None, ge=2000, description="Used by tab=students; default current year"),
    status: Literal["all", "active", "settled", "cancelled"] = Query("all", description="Loan status filter (loans tabs)"),
    search: Optional[str] = Query(None),
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
            raise HTTPException(400, detail="location_id is required when system=gennis")
        if tab == "students":
            return _gennis_students_with_debt(gennis_db, location_id, month, year, search, offset, limit)
        direction = "out" if tab == "given" else "in"
        return _gennis_loans(gennis_db, location_id, direction, status, search, offset, limit, tab)

    # turon
    if not branch_id:
        raise HTTPException(400, detail="branch_id is required when system=turon")
    if tab == "students":
        return _turon_students_with_debt(turon_db, branch_id, month, year, search, offset, limit)
    direction = "out" if tab == "given" else "in"
    return _turon_loans(turon_db, branch_id, direction, status, search, offset, limit, tab)
