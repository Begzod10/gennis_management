"""Accountant payment list — table view, per-channel KPIs and revenue/expense trend.

Backs the Buxgalteriya `To'lovlar` screen:
- 3 KPI cards: Click, Payme (placeholder if absent), Naqd/Bank — for selected month
- 6-month bar chart: revenue (student payments) vs expense (salaries + overheads)
- Paginated payment list

GET /api/v1/accountant/payments
    ?system=gennis&location_id=4
    &month=5&year=2026
    &search=...
    &channel=cash|click|bank          (filter list)
    &type=payment|discount             (filter list)
    &from=YYYY-MM-DD&to=YYYY-MM-DD     (filter list by date range)
    &offset=0&limit=50
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, extract, func, or_
from sqlalchemy.orm import Session

from app.database import get_gennis_db, get_turon_db
from app.external_models import gennis as G
from app.external_models import turon as T


router = APIRouter(prefix="/accountant", tags=["Accountant"])


# ── Response shape ────────────────────────────────────────────────────────────

class _ChannelTotal(BaseModel):
    channel: str       # raw payment-type name from DB ("cash" / "click" / "bank")
    label: str         # user-facing label ("Naqd" / "Click" / "Bank")
    value: int
    percent: float     # 0..100, share of month total


class _TrendPoint(BaseModel):
    month: int
    year: int
    label: str         # short Uzbek month abbrev ("Yan", "Fev", …)
    revenue: int
    expense: int


class _PaymentItem(BaseModel):
    id: int
    code: str                 # "#INV-2501"
    student_name: str
    amount: int
    channel: Optional[str]    # raw name
    channel_label: Optional[str]
    date: str                 # ISO YYYY-MM-DD
    date_label: str           # "19-yan"
    type: str                 # "Oy to'lovi" | "Chegirma"
    status: str               # "To'landi" | "Chegirma"


class _Pagination(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool


class PaymentsOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    month: int
    year: int
    month_total: int
    totals_by_channel: List[_ChannelTotal]
    trend: List[_TrendPoint]
    items: List[_PaymentItem]
    pagination: _Pagination


# ── Helpers ───────────────────────────────────────────────────────────────────

_CHANNEL_LABELS = {"cash": "Naqd", "click": "Click", "bank": "Bank", "payme": "Payme"}

_MONTH_SHORT_UZ = {
    1: "Yan", 2: "Fev", 3: "Mar", 4: "Apr", 5: "May", 6: "Iyn",
    7: "Iyl", 8: "Avg", 9: "Sen", 10: "Okt", 11: "Noy", 12: "Dek",
}


def _channel_label(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return _CHANNEL_LABELS.get(name.lower(), name.capitalize())


def _format_date_label(d: date) -> str:
    return f"{d.day}-{_MONTH_SHORT_UZ[d.month].lower()}"


def _last_n_months(n: int, anchor: date) -> List[tuple[int, int]]:
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


def _percentages(values: List[int]) -> List[float]:
    total = sum(values)
    if total <= 0:
        return [0.0 for _ in values]
    return [round(v * 100.0 / total, 2) for v in values]


# ── Gennis aggregation ────────────────────────────────────────────────────────

def _gennis_month_year_ids(db: Session, month: int, year: int) -> Optional[tuple[int, int]]:
    """Return (month_row_id, year_row_id) or None if Gennis has no rows for this period."""
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


def _gennis_channel_totals(
    db: Session, location_id: int, month: int, year: int,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> List[_ChannelTotal]:
    q = (
        db.query(G.PaymentTypes.name, func.coalesce(func.sum(G.StudentPayments.payment_sum), 0))
        .join(G.StudentPayments, G.StudentPayments.payment_type_id == G.PaymentTypes.id)
        .filter(
            G.StudentPayments.location_id == location_id,
            G.StudentPayments.payment == True,
        )
        .group_by(G.PaymentTypes.name)
    )

    if date_from and date_to:
        q = q.join(G.CalendarDay, G.CalendarDay.id == G.StudentPayments.calendar_day).filter(
            func.date(G.CalendarDay.date) >= date_from,
            func.date(G.CalendarDay.date) <= date_to,
        )
    else:
        ids = _gennis_month_year_ids(db, month, year)
        if not ids:
            return []
        month_id, year_id = ids
        q = q.filter(
            G.StudentPayments.calendar_month == month_id,
            G.StudentPayments.calendar_year == year_id,
        )

    rows = [(n or "", int(v or 0)) for n, v in q.all()]
    values = [v for _, v in rows]
    percents = _percentages(values)
    return [
        _ChannelTotal(channel=n, label=_channel_label(n) or n, value=v, percent=p)
        for (n, v), p in zip(rows, percents)
    ]


def _gennis_month_revenue(db: Session, location_id: int, month: int, year: int) -> int:
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        return 0
    month_id, year_id = ids
    return int(db.query(func.coalesce(func.sum(G.StudentPayments.payment_sum), 0)).filter(
        G.StudentPayments.location_id == location_id,
        G.StudentPayments.payment == True,
        G.StudentPayments.calendar_month == month_id,
        G.StudentPayments.calendar_year == year_id,
    ).scalar() or 0)


def _gennis_month_expense(db: Session, location_id: int, month: int, year: int) -> int:
    """Salaries paid that month (teacher + assistent + staff) + overhead-log payments that month."""
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        return 0
    month_id, year_id = ids

    def _salary_sum(model) -> int:
        return int(db.query(func.coalesce(func.sum(model.payment_sum), 0)).filter(
            model.location_id == location_id,
            model.calendar_month == month_id,
            model.calendar_year == year_id,
        ).scalar() or 0)

    salaries = _salary_sum(G.TeacherSalaries) + _salary_sum(G.AssistentSalaries) + _salary_sum(G.StaffSalaries)

    overhead = int(db.query(func.coalesce(func.sum(G.OverheadTypeLogPayment.amount), 0)).join(
        G.OverheadTypeLog, G.OverheadTypeLog.id == G.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        G.OverheadTypeLog.location_id == location_id,
        G.OverheadTypeLogPayment.deleted == False,
        extract("month", G.OverheadTypeLogPayment.paid_date) == month,
        extract("year", G.OverheadTypeLogPayment.paid_date) == year,
    ).scalar() or 0)

    return salaries + overhead


def _gennis_trend(db: Session, location_id: int, months: List[tuple[int, int]]) -> List[_TrendPoint]:
    points: list[_TrendPoint] = []
    for (y, m) in months:
        points.append(_TrendPoint(
            month=m, year=y, label=_MONTH_SHORT_UZ[m],
            revenue=_gennis_month_revenue(db, location_id, m, y),
            expense=_gennis_month_expense(db, location_id, m, y),
        ))
    return points


def _gennis_payments_list(
    db: Session,
    location_id: int,
    month: int,
    year: int,
    search: Optional[str],
    channel: Optional[str],
    type_filter: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    offset: int,
    limit: int,
) -> tuple[int, list[_PaymentItem]]:
    base = (
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
        .outerjoin(G.CalendarDay, G.CalendarDay.id == G.StudentPayments.calendar_day)
        .filter(G.StudentPayments.location_id == location_id)
    )

    if not (date_from and date_to):
        ids = _gennis_month_year_ids(db, month, year)
        if not ids:
            return 0, []
        month_id, year_id = ids
        base = base.filter(
            G.StudentPayments.calendar_month == month_id,
            G.StudentPayments.calendar_year == year_id,
        )

    if search:
        like = f"%{search}%"
        base = base.filter(or_(G.Users.name.ilike(like), G.Users.surname.ilike(like)))

    if channel:
        base = base.filter(G.PaymentTypes.name == channel)

    if type_filter == "payment":
        base = base.filter(G.StudentPayments.payment == True)
    elif type_filter == "discount":
        base = base.filter(G.StudentPayments.payment == False)

    if date_from:
        base = base.filter(G.CalendarDay.date >= date_from)
    if date_to:
        base = base.filter(G.CalendarDay.date <= date_to)

    total = base.with_entities(func.count(G.StudentPayments.id)).scalar() or 0

    rows = (
        base.order_by(G.StudentPayments.id.desc()).offset(offset).limit(limit).all()
    )

    items: list[_PaymentItem] = []
    for r in rows:
        pay = r.StudentPayments
        paid_date = r.paid_date
        is_real = bool(pay.payment)
        items.append(_PaymentItem(
            id=pay.id,
            code=f"#INV-{pay.id}",
            student_name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            amount=pay.payment_sum or 0,
            channel=r.payment_type_name,
            channel_label=_channel_label(r.payment_type_name),
            date=paid_date.strftime("%Y-%m-%d") if paid_date else "",
            date_label=_format_date_label(paid_date) if paid_date else "",
            type="Oy to'lovi" if is_real else "Chegirma",
            status="To'landi" if is_real else "Chegirma",
        ))
    return int(total), items


# ── Turon aggregation ─────────────────────────────────────────────────────────

def _turon_channel_totals(
    db: Session, branch_id: int, month: int, year: int,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
) -> List[_ChannelTotal]:
    q = (
        db.query(T.PaymentTypes.name, func.coalesce(func.sum(T.StudentPayment.payment_sum), 0))
        .join(T.StudentPayment, T.StudentPayment.payment_type_id == T.PaymentTypes.id)
        .filter(
            T.StudentPayment.branch_id == branch_id,
            T.StudentPayment.deleted == False,
            T.StudentPayment.status == False,  # real payments, not discounts
        )
        .group_by(T.PaymentTypes.name)
    )
    if date_from and date_to:
        q = q.filter(
            T.StudentPayment.date >= date_from,
            T.StudentPayment.date <= date_to,
        )
    else:
        q = q.filter(
            extract("month", T.StudentPayment.date) == month,
            extract("year", T.StudentPayment.date) == year,
        )
    raw = q.all()
    rows = [(n or "", int(v or 0)) for n, v in raw]
    values = [v for _, v in rows]
    percents = _percentages(values)
    return [
        _ChannelTotal(channel=n, label=_channel_label(n) or n, value=v, percent=p)
        for (n, v), p in zip(rows, percents)
    ]


def _turon_month_revenue(db: Session, branch_id: int, month: int, year: int) -> int:
    return int(db.query(func.coalesce(func.sum(T.StudentPayment.payment_sum), 0)).filter(
        T.StudentPayment.branch_id == branch_id,
        T.StudentPayment.deleted == False,
        T.StudentPayment.status == False,
        extract("month", T.StudentPayment.date) == month,
        extract("year", T.StudentPayment.date) == year,
    ).scalar() or 0)


def _turon_month_expense(db: Session, branch_id: int, month: int, year: int) -> int:
    teacher = int(db.query(func.coalesce(func.sum(T.TeacherSalaryList.salary), 0)).filter(
        T.TeacherSalaryList.branch_id == branch_id,
        T.TeacherSalaryList.deleted == False,
        extract("month", T.TeacherSalaryList.date) == month,
        extract("year", T.TeacherSalaryList.date) == year,
    ).scalar() or 0)

    staff = int(db.query(func.coalesce(func.sum(T.UserSalaryList.salary), 0)).filter(
        T.UserSalaryList.branch_id == branch_id,
        T.UserSalaryList.deleted == False,
        extract("month", T.UserSalaryList.date) == month,
        extract("year", T.UserSalaryList.date) == year,
    ).scalar() or 0)

    overhead_legacy = int(db.query(func.coalesce(func.sum(T.Overhead.price), 0)).filter(
        T.Overhead.branch_id == branch_id,
        T.Overhead.deleted == False,
        extract("month", T.Overhead.created) == month,
        extract("year", T.Overhead.created) == year,
    ).scalar() or 0)

    overhead_split = int(db.query(func.coalesce(func.sum(T.OverheadTypeLogPayment.amount), 0)).join(
        T.OverheadTypeLog, T.OverheadTypeLog.id == T.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        T.OverheadTypeLog.branch_id == branch_id,
        T.OverheadTypeLogPayment.deleted == False,
        extract("month", T.OverheadTypeLogPayment.paid_date) == month,
        extract("year", T.OverheadTypeLogPayment.paid_date) == year,
    ).scalar() or 0)

    return teacher + staff + overhead_legacy + overhead_split


def _turon_trend(db: Session, branch_id: int, months: List[tuple[int, int]]) -> List[_TrendPoint]:
    points: list[_TrendPoint] = []
    for (y, m) in months:
        points.append(_TrendPoint(
            month=m, year=y, label=_MONTH_SHORT_UZ[m],
            revenue=_turon_month_revenue(db, branch_id, m, y),
            expense=_turon_month_expense(db, branch_id, m, y),
        ))
    return points


def _turon_payments_list(
    db: Session,
    branch_id: int,
    month: int,
    year: int,
    search: Optional[str],
    channel: Optional[str],
    type_filter: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    offset: int,
    limit: int,
) -> tuple[int, list[_PaymentItem]]:
    base = (
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
            T.StudentPayment.deleted == False,
        )
    )

    if not (date_from and date_to):
        base = base.filter(
            extract("month", T.StudentPayment.date) == month,
            extract("year", T.StudentPayment.date) == year,
        )

    if search:
        like = f"%{search}%"
        base = base.filter(or_(T.CustomUser.name.ilike(like), T.CustomUser.surname.ilike(like)))

    if channel:
        base = base.filter(T.PaymentTypes.name == channel)

    # Turon convention: status=False is a real channel payment, status=True is applied discount
    if type_filter == "payment":
        base = base.filter(T.StudentPayment.status == False)
    elif type_filter == "discount":
        base = base.filter(T.StudentPayment.status == True)

    if date_from:
        base = base.filter(T.StudentPayment.date >= date_from)
    if date_to:
        base = base.filter(T.StudentPayment.date <= date_to)

    total = base.with_entities(func.count(T.StudentPayment.id)).scalar() or 0

    rows = (
        base.order_by(T.StudentPayment.id.desc()).offset(offset).limit(limit).all()
    )

    items: list[_PaymentItem] = []
    for r in rows:
        pay = r.StudentPayment
        is_real = not bool(pay.status)
        items.append(_PaymentItem(
            id=pay.id,
            code=f"#INV-{pay.id}",
            student_name=f"{r.user_name or ''} {r.user_surname or ''}".strip(),
            amount=pay.payment_sum or 0,
            channel=r.payment_type_name,
            channel_label=_channel_label(r.payment_type_name),
            date=pay.date.strftime("%Y-%m-%d") if pay.date else "",
            date_label=_format_date_label(pay.date) if pay.date else "",
            type="Oy to'lovi" if is_real else "Chegirma",
            status="To'landi" if is_real else "Chegirma",
        ))
    return int(total), items


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/payments", response_model=PaymentsOut)
def accountant_payments(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Defaults to current month"),
    year: Optional[int] = Query(None, ge=2000, description="Defaults to current year"),
    search: Optional[str] = Query(None, description="Filter list by student name/surname"),
    channel: Optional[str] = Query(None, description="Filter list by payment type name (cash|click|bank|…)"),
    type_filter: Optional[Literal["payment", "discount"]] = Query(None, alias="type", description="Filter list to real payments vs discounts"),
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    today = date.today()
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="`from` must be on or before `to`")
    month_v = month or today.month
    year_v = year or today.year
    months_window = _last_n_months(6, date(year_v, month_v, 1))

    if system == "gennis":
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id is required when system=gennis")
        channel_totals = _gennis_channel_totals(gennis_db, location_id, month_v, year_v, date_from, date_to)
        trend = _gennis_trend(gennis_db, location_id, months_window)
        total, items = _gennis_payments_list(
            gennis_db, location_id, month_v, year_v,
            search, channel, type_filter, date_from, date_to,
            offset, limit,
        )
        scope_id = location_id
    else:
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required when system=turon")
        channel_totals = _turon_channel_totals(turon_db, branch_id, month_v, year_v, date_from, date_to)
        trend = _turon_trend(turon_db, branch_id, months_window)
        total, items = _turon_payments_list(
            turon_db, branch_id, month_v, year_v,
            search, channel, type_filter, date_from, date_to,
            offset, limit,
        )
        scope_id = branch_id

    month_total = sum(c.value for c in channel_totals)

    return PaymentsOut(
        system=system,
        scope_id=scope_id,
        month=month_v,
        year=year_v,
        month_total=month_total,
        totals_by_channel=channel_totals,
        trend=trend,
        items=items,
        pagination=_Pagination(
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < total,
        ),
    )
