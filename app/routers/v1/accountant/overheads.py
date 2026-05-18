"""Accountant overhead (expenses) list — Buxgalteriya `Xarajatlar` screen.

Returns:
- The flat line-item table (Xarajat turi, Kategoriya, Summa, Filial, Sana,
  To'lov usuli) for the selected month.
- A 6-month income vs expense chart (`Xarajat kategoriyalari`) for the same
  scope, useful for the bar chart at the top of the screen.

GET /api/v1/accountant/overheads
    ?system=gennis&location_id=4
    &month=5&year=2026
    &search=...
    &overhead_type_id=...      # filter by Kategoriya
    &payment_type_id=...       # filter by To'lov usuli
    &offset=0&limit=50

`system=turon` uses `branch_id` instead of `location_id`. `month` / `year`
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

class OverheadRow(BaseModel):
    id: int
    name: Optional[str]            # Xarajat turi — Overhead.item_name / Overhead.name
    category: Optional[str]        # Kategoriya — OverheadType.name
    category_id: Optional[int]
    amount: int                    # Summa
    branch_name: Optional[str]     # Filial — Location.name / Branch.name
    branch_id: int
    date: Optional[str]            # Sana — YYYY-MM-DD
    payment_type: Optional[str]    # To'lov usuli — PaymentTypes.name
    payment_type_id: Optional[int]


class _TrendPoint(BaseModel):
    month: int
    year: int
    label: str        # Avg, Sen, Okt, …
    revenue: int      # Daromad
    expense: int      # Xarajat


class _ByPaymentType(BaseModel):
    payment_type_id: Optional[int]
    payment_type: Optional[str]
    amount: int


class _ByCategory(BaseModel):
    category_id: Optional[int]
    category: Optional[str]
    amount: int


class _Totals(BaseModel):
    count: int
    amount: int
    by_payment_type: List[_ByPaymentType]
    by_category: List[_ByCategory]


class _Pagination(BaseModel):
    total: int
    offset: int
    limit: int
    has_more: bool


class OverheadsOut(BaseModel):
    system: Literal["gennis", "turon"]
    scope_id: int
    month: int
    year: int
    chart: List[_TrendPoint]
    overheads: List[OverheadRow]
    totals: _Totals
    pagination: _Pagination


# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_SHORT_UZ = {
    1: "Yan", 2: "Fev", 3: "Mar", 4: "Apr", 5: "May", 6: "Iyn",
    7: "Iyl", 8: "Avg", 9: "Sen", 10: "Okt", 11: "Noy", 12: "Dek",
}


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


def _aggregate(rows: List[OverheadRow]) -> _Totals:
    by_pt: dict[Optional[int], dict] = {}
    by_cat: dict[Optional[int], dict] = {}
    total_amount = 0
    for r in rows:
        total_amount += r.amount
        bucket = by_pt.setdefault(r.payment_type_id, {"payment_type_id": r.payment_type_id, "payment_type": r.payment_type, "amount": 0})
        bucket["amount"] += r.amount
        cbucket = by_cat.setdefault(r.category_id, {"category_id": r.category_id, "category": r.category, "amount": 0})
        cbucket["amount"] += r.amount

    return _Totals(
        count=len(rows),
        amount=total_amount,
        by_payment_type=[_ByPaymentType(**v) for v in by_pt.values()],
        by_category=[_ByCategory(**v) for v in by_cat.values()],
    )


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


def _gennis_month_overhead_expense(db: Session, location_id: int, month: int, year: int) -> int:
    """Total overhead spend for the month: legacy Overhead rows + split payments not linked to a legacy Overhead."""
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        return 0
    month_id, year_id = ids

    legacy = int(db.query(func.coalesce(func.sum(G.Overhead.item_sum), 0)).filter(
        G.Overhead.location_id == location_id,
        G.Overhead.calendar_month == month_id,
        G.Overhead.calendar_year == year_id,
    ).scalar() or 0)

    # Split payments that have NOT been materialized into a legacy Overhead row yet.
    split = int(db.query(func.coalesce(func.sum(G.OverheadTypeLogPayment.amount), 0)).join(
        G.OverheadTypeLog, G.OverheadTypeLog.id == G.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        G.OverheadTypeLog.location_id == location_id,
        G.OverheadTypeLogPayment.deleted == False,
        G.OverheadTypeLogPayment.overhead_id.is_(None),
        extract("month", G.OverheadTypeLogPayment.paid_date) == month,
        extract("year", G.OverheadTypeLogPayment.paid_date) == year,
    ).scalar() or 0)

    return legacy + split


def _gennis_trend(db: Session, location_id: int, months: List[tuple[int, int]]) -> List[_TrendPoint]:
    return [
        _TrendPoint(
            month=m, year=y, label=_MONTH_SHORT_UZ[m],
            revenue=_gennis_month_revenue(db, location_id, m, y),
            expense=_gennis_month_overhead_expense(db, location_id, m, y),
        )
        for (y, m) in months
    ]


def _gennis_overheads(
    db: Session,
    location_id: int,
    month: int,
    year: int,
    search: Optional[str],
    overhead_type_id: Optional[int],
    payment_type_id: Optional[int],
) -> List[OverheadRow]:
    ids = _gennis_month_year_ids(db, month, year)
    if not ids:
        return []
    month_id, year_id = ids

    q = (
        db.query(
            G.Overhead.id.label("id"),
            G.Overhead.item_name.label("name"),
            G.Overhead.item_sum.label("amount"),
            G.OverheadType.id.label("category_id"),
            G.OverheadType.name.label("category_name"),
            G.Locations.id.label("branch_id"),
            G.Locations.name.label("branch_name"),
            G.CalendarDay.date.label("paid_date"),
            G.PaymentTypes.id.label("payment_type_id"),
            G.PaymentTypes.name.label("payment_type_name"),
        )
        .outerjoin(G.OverheadType, G.OverheadType.id == G.Overhead.overhead_type_id)
        .outerjoin(G.Locations, G.Locations.id == G.Overhead.location_id)
        .outerjoin(G.CalendarDay, G.CalendarDay.id == G.Overhead.calendar_day)
        .outerjoin(G.PaymentTypes, G.PaymentTypes.id == G.Overhead.payment_type_id)
        .filter(
            G.Overhead.location_id == location_id,
            G.Overhead.calendar_month == month_id,
            G.Overhead.calendar_year == year_id,
        )
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            G.Overhead.item_name.ilike(like),
            G.OverheadType.name.ilike(like),
        ))
    if overhead_type_id is not None:
        q = q.filter(G.Overhead.overhead_type_id == overhead_type_id)
    if payment_type_id is not None:
        q = q.filter(G.Overhead.payment_type_id == payment_type_id)

    rows = q.order_by(G.Overhead.id.desc()).all()

    out: list[OverheadRow] = []
    for r in rows:
        out.append(OverheadRow(
            id=r.id,
            name=r.name,
            category=r.category_name,
            category_id=r.category_id,
            amount=int(r.amount or 0),
            branch_id=r.branch_id,
            branch_name=r.branch_name,
            date=r.paid_date.strftime("%Y-%m-%d") if r.paid_date else None,
            payment_type=r.payment_type_name,
            payment_type_id=r.payment_type_id,
        ))
    return out


# ── Turon ─────────────────────────────────────────────────────────────────────

def _turon_month_revenue(db: Session, branch_id: int, month: int, year: int) -> int:
    return int(db.query(func.coalesce(func.sum(T.StudentPayment.payment_sum), 0)).filter(
        T.StudentPayment.branch_id == branch_id,
        T.StudentPayment.status == True,
        T.StudentPayment.deleted == False,
        extract("month", T.StudentPayment.date) == month,
        extract("year", T.StudentPayment.date) == year,
    ).scalar() or 0)


def _turon_month_overhead_expense(db: Session, branch_id: int, month: int, year: int) -> int:
    legacy = int(db.query(func.coalesce(func.sum(T.Overhead.price), 0)).filter(
        T.Overhead.branch_id == branch_id,
        T.Overhead.deleted == False,
        extract("month", T.Overhead.created) == month,
        extract("year", T.Overhead.created) == year,
    ).scalar() or 0)

    split = int(db.query(func.coalesce(func.sum(T.OverheadTypeLogPayment.amount), 0)).join(
        T.OverheadTypeLog, T.OverheadTypeLog.id == T.OverheadTypeLogPayment.overhead_type_log_id,
    ).filter(
        T.OverheadTypeLog.branch_id == branch_id,
        T.OverheadTypeLogPayment.deleted == False,
        T.OverheadTypeLogPayment.overhead_id.is_(None),
        extract("month", T.OverheadTypeLogPayment.paid_date) == month,
        extract("year", T.OverheadTypeLogPayment.paid_date) == year,
    ).scalar() or 0)

    return legacy + split


def _turon_trend(db: Session, branch_id: int, months: List[tuple[int, int]]) -> List[_TrendPoint]:
    return [
        _TrendPoint(
            month=m, year=y, label=_MONTH_SHORT_UZ[m],
            revenue=_turon_month_revenue(db, branch_id, m, y),
            expense=_turon_month_overhead_expense(db, branch_id, m, y),
        )
        for (y, m) in months
    ]


def _turon_overheads(
    db: Session,
    branch_id: int,
    month: int,
    year: int,
    search: Optional[str],
    overhead_type_id: Optional[int],
    payment_type_id: Optional[int],
) -> List[OverheadRow]:
    q = (
        db.query(
            T.Overhead.id.label("id"),
            T.Overhead.name.label("name"),
            T.Overhead.price.label("amount"),
            T.OverheadType.id.label("category_id"),
            T.OverheadType.name.label("category_name"),
            T.Branch.id.label("branch_id"),
            T.Branch.name.label("branch_name"),
            T.Overhead.created.label("paid_date"),
            T.PaymentTypes.id.label("payment_type_id"),
            T.PaymentTypes.name.label("payment_type_name"),
        )
        .outerjoin(T.OverheadType, T.OverheadType.id == T.Overhead.type_id)
        .outerjoin(T.Branch, T.Branch.id == T.Overhead.branch_id)
        .outerjoin(T.PaymentTypes, T.PaymentTypes.id == T.Overhead.payment_id)
        .filter(
            T.Overhead.branch_id == branch_id,
            T.Overhead.deleted == False,
            extract("month", T.Overhead.created) == month,
            extract("year", T.Overhead.created) == year,
        )
    )

    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            T.Overhead.name.ilike(like),
            T.OverheadType.name.ilike(like),
        ))
    if overhead_type_id is not None:
        q = q.filter(T.Overhead.type_id == overhead_type_id)
    if payment_type_id is not None:
        q = q.filter(T.Overhead.payment_id == payment_type_id)

    rows = q.order_by(T.Overhead.id.desc()).all()

    out: list[OverheadRow] = []
    for r in rows:
        out.append(OverheadRow(
            id=r.id,
            name=r.name,
            category=r.category_name,
            category_id=r.category_id,
            amount=int(r.amount or 0),
            branch_id=r.branch_id,
            branch_name=r.branch_name,
            date=r.paid_date.strftime("%Y-%m-%d") if r.paid_date else None,
            payment_type=r.payment_type_name,
            payment_type_id=r.payment_type_id,
        ))
    return out


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/overheads", response_model=OverheadsOut)
def accountant_overheads(
    system: Literal["gennis", "turon"] = Query(..., description="Source system"),
    location_id: Optional[int] = Query(None, description="Gennis location id (required when system=gennis)"),
    branch_id: Optional[int] = Query(None, description="Turon branch id (required when system=turon)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Defaults to current month"),
    year: Optional[int] = Query(None, ge=2000, description="Defaults to current year"),
    search: Optional[str] = Query(None, description="Filter by name or category"),
    overhead_type_id: Optional[int] = Query(None, description="Filter by OverheadType id"),
    payment_type_id: Optional[int] = Query(None, description="Filter by PaymentType id"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    today = date.today()
    month = month or today.month
    year = year or today.year
    months_window = _last_n_months(6, date(year, month, 1))

    if system == "gennis":
        if not location_id:
            raise HTTPException(status_code=400, detail="location_id is required when system=gennis")
        all_rows = _gennis_overheads(gennis_db, location_id, month, year, search, overhead_type_id, payment_type_id)
        chart = _gennis_trend(gennis_db, location_id, months_window)
        scope_id = location_id
    else:
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required when system=turon")
        all_rows = _turon_overheads(turon_db, branch_id, month, year, search, overhead_type_id, payment_type_id)
        chart = _turon_trend(turon_db, branch_id, months_window)
        scope_id = branch_id

    totals = _aggregate(all_rows)
    page = all_rows[offset : offset + limit]

    return OverheadsOut(
        system=system,
        scope_id=scope_id,
        month=month,
        year=year,
        chart=chart,
        overheads=page,
        totals=totals,
        pagination=_Pagination(
            total=len(all_rows),
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < len(all_rows),
        ),
    )
