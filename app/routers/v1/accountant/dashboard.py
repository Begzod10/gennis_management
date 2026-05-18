"""Accountant dashboard aggregates.

Single endpoint that returns the KPIs, income trend and recent payment activity
for one branch (Turon) or one location (Gennis). Used by the Buxgalteriya
dashboard screen.

Query contract:

    GET /api/v1/accountant/dashboard?system=gennis&location_id=4
    GET /api/v1/accountant/dashboard?system=turon&branch_id=2

The shape is identical regardless of system so the frontend has one renderer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, extract, func
from sqlalchemy.orm import Session

from app.database import get_gennis_db, get_turon_db
from app.external_models import gennis as G
from app.external_models import turon as T


router = APIRouter(prefix="/accountant", tags=["Accountant"])


# ── Response shape ────────────────────────────────────────────────────────────

class _TodayKpi(BaseModel):
    value: int
    yesterday_value: int
    delta_vs_yesterday_pct: Optional[float]  # None when yesterday was 0


class _MonthlyKpi(BaseModel):
    value: int
    month: int
    year: int
    month_label: str  # e.g. "Yanvar 2025"


class _DebtKpi(BaseModel):
    value: int
    open_count: int


class _ExpensesKpi(BaseModel):
    value: int
    salaries: int
    overheads: int


class _TrendPoint(BaseModel):
    month: int
    year: int
    label: str  # short month abbrev, e.g. "Yan"
    income: int


class _RecentPayment(BaseModel):
    id: int
    student_name: str
    amount: int
    channel: Optional[str]
    date: str  # YYYY-MM-DD
    type: str  # "Oy to'lovi" | "Qisman to'lov" | "Chegirma"
    status: str  # "To'landi" | "Qisman"


class _Range(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    mode: Literal["today", "custom"]


class DashboardOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int  # location_id for gennis, branch_id for turon
    today: str
    range: _Range
    today_payments: _TodayKpi
    monthly_income: _MonthlyKpi
    debt: _DebtKpi
    today_expenses: _ExpensesKpi
    trend: List[_TrendPoint]
    recent_payments: List[_RecentPayment]


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_LABELS_UZ = {
    1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel", 5: "May", 6: "Iyun",
    7: "Iyul", 8: "Avgust", 9: "Sentabr", 10: "Oktabr", 11: "Noyabr", 12: "Dekabr",
}

_MONTH_SHORT_UZ = {
    1: "Yan", 2: "Fev", 3: "Mar", 4: "Apr", 5: "May", 6: "Iyn",
    7: "Iyl", 8: "Avg", 9: "Sen", 10: "Okt", 11: "Noy", 12: "Dek",
}


def _delta_pct(today_val: int, yesterday_val: int) -> Optional[float]:
    if yesterday_val <= 0:
        return None
    return round((today_val - yesterday_val) * 100.0 / yesterday_val, 2)


def _last_n_months(n: int, anchor: date) -> List[tuple[int, int]]:
    """Return [(year, month), …] for the last n months including the anchor month, oldest first."""
    out: list[tuple[int, int]] = []
    y, m = anchor.year, anchor.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    out.reverse()
    return out


# ── Gennis aggregation ────────────────────────────────────────────────────────

def _gennis_payments_in_range(
    db: Session, location_id: int, date_from: date, date_to: date,
) -> int:
    """Sum of real student payments (payment=True) within [date_from, date_to]."""
    return db.query(func.coalesce(func.sum(G.StudentPayments.payment_sum), 0)).join(
        G.CalendarDay, G.CalendarDay.id == G.StudentPayments.calendar_day,
    ).filter(
        G.StudentPayments.location_id == location_id,
        G.StudentPayments.payment == True,
        func.date(G.CalendarDay.date) >= date_from,
        func.date(G.CalendarDay.date) <= date_to,
    ).scalar() or 0


def _gennis_monthly_income(db: Session, location_id: int, year: int, month: int) -> int:
    return db.query(func.coalesce(func.sum(G.StudentPayments.payment_sum), 0)).join(
        G.CalendarMonth, G.CalendarMonth.id == G.StudentPayments.calendar_month,
    ).join(
        G.CalendarYear, G.CalendarYear.id == G.StudentPayments.calendar_year,
    ).filter(
        G.StudentPayments.location_id == location_id,
        G.StudentPayments.payment == True,
        extract("month", G.CalendarMonth.date) == month,
        extract("year", G.CalendarYear.date) == year,
    ).scalar() or 0


def _gennis_debt(db: Session, location_id: int, year: int, month: int) -> tuple[int, int]:
    """Return (total_remaining_debt, open_debt_count) for the current month."""
    q = db.query(
        func.coalesce(func.sum(G.AttendanceHistoryStudent.remaining_debt), 0),
        func.count(G.AttendanceHistoryStudent.id),
    ).join(
        G.CalendarMonth, G.CalendarMonth.id == G.AttendanceHistoryStudent.calendar_month,
    ).join(
        G.CalendarYear, G.CalendarYear.id == G.AttendanceHistoryStudent.calendar_year,
    ).filter(
        G.AttendanceHistoryStudent.location_id == location_id,
        G.AttendanceHistoryStudent.remaining_debt > 0,
        extract("month", G.CalendarMonth.date) == month,
        extract("year", G.CalendarYear.date) == year,
    )
    total, cnt = q.one()
    return int(total or 0), int(cnt or 0)


def _gennis_salary_expenses_in_range(
    db: Session, location_id: int, date_from: date, date_to: date,
) -> int:
    """Sum of every salary transaction (teacher + assistent + staff) paid in [date_from, date_to]."""
    def _sum(model) -> int:
        return db.query(func.coalesce(func.sum(model.payment_sum), 0)).join(
            G.CalendarDay, G.CalendarDay.id == model.calendar_day,
        ).filter(
            model.location_id == location_id,
            func.date(G.CalendarDay.date) >= date_from,
            func.date(G.CalendarDay.date) <= date_to,
        ).scalar() or 0

    return (
        _sum(G.TeacherSalaries)
        + _sum(G.AssistentSalaries)
        + _sum(G.StaffSalaries)
    )


def _gennis_overhead_expenses_in_range(
    db: Session, location_id: int, date_from: date, date_to: date,
) -> int:
    """Sum of overhead-type-log payments in [date_from, date_to] at `location_id`.

    Joins through the log to enforce the location filter — split payments
    inherit location from their parent log.
    """
    return db.query(func.coalesce(func.sum(G.OverheadTypeLogPayment.amount), 0)).join(
        G.OverheadTypeLog, G.OverheadTypeLog.id == G.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        G.OverheadTypeLog.location_id == location_id,
        G.OverheadTypeLogPayment.deleted == False,
        func.date(G.OverheadTypeLogPayment.paid_date) >= date_from,
        func.date(G.OverheadTypeLogPayment.paid_date) <= date_to,
    ).scalar() or 0


def _gennis_income_trend(db: Session, location_id: int, months: list[tuple[int, int]]) -> List[_TrendPoint]:
    points: list[_TrendPoint] = []
    for (y, m) in months:
        total = _gennis_monthly_income(db, location_id, y, m)
        points.append(_TrendPoint(month=m, year=y, label=_MONTH_SHORT_UZ[m], income=int(total)))
    return points


def _gennis_recent_payments(db: Session, location_id: int, limit: int = 8) -> List[_RecentPayment]:
    rows = (
        db.query(
            G.StudentPayments,
            G.Users.name.label("user_name"),
            G.Users.surname.label("user_surname"),
            G.PaymentTypes.name.label("payment_type_name"),
            G.CalendarDay.date.label("paid_date"),
        )
        .join(G.Students, G.Students.id == G.StudentPayments.student_id)
        .join(G.Users, G.Users.id == G.Students.user_id)
        .outerjoin(G.PaymentTypes, G.PaymentTypes.id == G.StudentPayments.payment_type_id)
        .join(G.CalendarDay, G.CalendarDay.id == G.StudentPayments.calendar_day)
        .filter(
            G.StudentPayments.location_id == location_id,
            G.StudentPayments.payment == True,
        )
        .order_by(G.StudentPayments.id.desc())
        .limit(limit)
        .all()
    )

    out: list[_RecentPayment] = []
    for r in rows:
        pay = r.StudentPayments
        paid_date = r.paid_date
        out.append(_RecentPayment(
            id=pay.id,
            student_name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            amount=pay.payment_sum or 0,
            channel=r.payment_type_name,
            date=paid_date.strftime("%Y-%m-%d") if paid_date else "",
            type="Oy to'lovi",
            status="To'landi",
        ))
    return out


# ── Turon aggregation ─────────────────────────────────────────────────────────

def _turon_payments_in_range(
    db: Session, branch_id: int, date_from: date, date_to: date,
) -> int:
    return db.query(func.coalesce(func.sum(T.StudentPayment.payment_sum), 0)).filter(
        T.StudentPayment.branch_id == branch_id,
        T.StudentPayment.status == True,
        T.StudentPayment.deleted == False,
        T.StudentPayment.date >= date_from,
        T.StudentPayment.date <= date_to,
    ).scalar() or 0


def _turon_monthly_income(db: Session, branch_id: int, year: int, month: int) -> int:
    return db.query(func.coalesce(func.sum(T.StudentPayment.payment_sum), 0)).filter(
        T.StudentPayment.branch_id == branch_id,
        T.StudentPayment.status == True,
        T.StudentPayment.deleted == False,
        extract("month", T.StudentPayment.date) == month,
        extract("year", T.StudentPayment.date) == year,
    ).scalar() or 0


def _turon_debt(db: Session, branch_id: int, year: int, month: int) -> tuple[int, int]:
    q = (
        db.query(
            func.coalesce(func.sum(T.AttendancePerMonth.remaining_debt), 0),
            func.count(T.AttendancePerMonth.id),
        )
        .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .filter(
            T.CustomUser.branch_id == branch_id,
            T.AttendancePerMonth.remaining_debt > 0,
            extract("month", T.AttendancePerMonth.month_date) == month,
            extract("year", T.AttendancePerMonth.month_date) == year,
        )
    )
    total, cnt = q.one()
    return int(total or 0), int(cnt or 0)


def _turon_salary_expenses_in_range(
    db: Session, branch_id: int, date_from: date, date_to: date,
) -> int:
    teacher = db.query(func.coalesce(func.sum(T.TeacherSalaryList.salary), 0)).filter(
        T.TeacherSalaryList.branch_id == branch_id,
        T.TeacherSalaryList.deleted == False,
        T.TeacherSalaryList.date >= date_from,
        T.TeacherSalaryList.date <= date_to,
    ).scalar() or 0

    staff = db.query(func.coalesce(func.sum(T.UserSalaryList.salary), 0)).filter(
        T.UserSalaryList.branch_id == branch_id,
        T.UserSalaryList.deleted == False,
        T.UserSalaryList.date >= date_from,
        T.UserSalaryList.date <= date_to,
    ).scalar() or 0

    return int(teacher) + int(staff)


def _turon_overhead_expenses_in_range(
    db: Session, branch_id: int, date_from: date, date_to: date,
) -> int:
    legacy = db.query(func.coalesce(func.sum(T.Overhead.price), 0)).filter(
        T.Overhead.branch_id == branch_id,
        T.Overhead.deleted == False,
        T.Overhead.created >= date_from,
        T.Overhead.created <= date_to,
    ).scalar() or 0

    split = db.query(func.coalesce(func.sum(T.OverheadTypeLogPayment.amount), 0)).join(
        T.OverheadTypeLog, T.OverheadTypeLog.id == T.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        T.OverheadTypeLog.branch_id == branch_id,
        T.OverheadTypeLogPayment.deleted == False,
        func.date(T.OverheadTypeLogPayment.paid_date) >= date_from,
        func.date(T.OverheadTypeLogPayment.paid_date) <= date_to,
    ).scalar() or 0

    return int(legacy) + int(split)


def _turon_income_trend(db: Session, branch_id: int, months: list[tuple[int, int]]) -> List[_TrendPoint]:
    points: list[_TrendPoint] = []
    for (y, m) in months:
        total = _turon_monthly_income(db, branch_id, y, m)
        points.append(_TrendPoint(month=m, year=y, label=_MONTH_SHORT_UZ[m], income=int(total)))
    return points


def _turon_recent_payments(db: Session, branch_id: int, limit: int = 8) -> List[_RecentPayment]:
    rows = (
        db.query(
            T.StudentPayment,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
            T.PaymentTypes.name.label("payment_type_name"),
        )
        .join(T.Student, T.Student.id == T.StudentPayment.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .outerjoin(T.PaymentTypes, T.PaymentTypes.id == T.StudentPayment.payment_type_id)
        .filter(
            T.StudentPayment.branch_id == branch_id,
            T.StudentPayment.status == True,
            T.StudentPayment.deleted == False,
        )
        .order_by(T.StudentPayment.id.desc())
        .limit(limit)
        .all()
    )

    out: list[_RecentPayment] = []
    for r in rows:
        pay = r.StudentPayment
        out.append(_RecentPayment(
            id=pay.id,
            student_name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            amount=pay.payment_sum or 0,
            channel=r.payment_type_name,
            date=pay.date.strftime("%Y-%m-%d") if pay.date else "",
            type="Oy to'lovi",
            status="To'landi",
        ))
    return out


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardOut)
def accountant_dashboard(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    on_date: Optional[date] = Query(None, alias="date", description="Override 'today' for testing (YYYY-MM-DD)"),
    date_from: Optional[date] = Query(None, alias="from", description="Start of custom range. When set with `to`, KPIs cover [from, to] instead of today."),
    date_to: Optional[date] = Query(None, alias="to", description="End of custom range. When set with `from`, KPIs cover [from, to] instead of today."),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    today = on_date or date.today()

    # Resolve the active aggregation window. When both `from` and `to` are
    # provided, treat that as the new "today" window — payments, expenses and
    # monthly_income all aggregate over it; yesterday comparison becomes the
    # equal-length window immediately before it.
    custom = bool(date_from and date_to)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="`from` must be on or before `to`")

    range_from = date_from if custom else today
    range_to = date_to if custom else today
    window_days = (range_to - range_from).days + 1
    prev_to = range_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=window_days - 1)

    # `monthly_income` and `debt` lock onto the last month in the active window.
    anchor = range_to
    month = anchor.month
    year = anchor.year
    months_window = _last_n_months(6, anchor)

    if system == "gennis":
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id is required when system=gennis")

        range_p = int(_gennis_payments_in_range(gennis_db, location_id, range_from, range_to))
        prev_p = int(_gennis_payments_in_range(gennis_db, location_id, prev_from, prev_to))
        monthly = (range_p if custom
                   else int(_gennis_monthly_income(gennis_db, location_id, year, month)))
        debt_total, debt_count = _gennis_debt(gennis_db, location_id, year, month)
        salaries_range = int(_gennis_salary_expenses_in_range(gennis_db, location_id, range_from, range_to))
        overheads_range = int(_gennis_overhead_expenses_in_range(gennis_db, location_id, range_from, range_to))
        trend = _gennis_income_trend(gennis_db, location_id, months_window)
        recent = _gennis_recent_payments(gennis_db, location_id)
        scope_id = location_id
    else:  # turon
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required when system=turon")

        range_p = int(_turon_payments_in_range(turon_db, branch_id, range_from, range_to))
        prev_p = int(_turon_payments_in_range(turon_db, branch_id, prev_from, prev_to))
        monthly = (range_p if custom
                   else int(_turon_monthly_income(turon_db, branch_id, year, month)))
        debt_total, debt_count = _turon_debt(turon_db, branch_id, year, month)
        salaries_range = int(_turon_salary_expenses_in_range(turon_db, branch_id, range_from, range_to))
        overheads_range = int(_turon_overhead_expenses_in_range(turon_db, branch_id, range_from, range_to))
        trend = _turon_income_trend(turon_db, branch_id, months_window)
        recent = _turon_recent_payments(turon_db, branch_id)
        scope_id = branch_id

    return DashboardOut(
        system=system,
        scope_id=scope_id,
        today=today.strftime("%Y-%m-%d"),
        range=_Range(
            **{"from": range_from.strftime("%Y-%m-%d")},
            to=range_to.strftime("%Y-%m-%d"),
            mode="custom" if custom else "today",
        ),
        today_payments=_TodayKpi(
            value=range_p,
            yesterday_value=prev_p,
            delta_vs_yesterday_pct=_delta_pct(range_p, prev_p),
        ),
        monthly_income=_MonthlyKpi(
            value=monthly,
            month=month,
            year=year,
            month_label=f"{_MONTH_LABELS_UZ[month]} {year}",
        ),
        debt=_DebtKpi(value=debt_total, open_count=debt_count),
        today_expenses=_ExpensesKpi(
            value=salaries_range + overheads_range,
            salaries=salaries_range,
            overheads=overheads_range,
        ),
        trend=trend,
        recent_payments=recent,
    )
