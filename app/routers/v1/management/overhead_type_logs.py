"""Read-only proxy for Gennis and Turon overhead_type_log monthly views.

Mirrors Turon's `api/Overhead/overhead_type_logs/{month}/{year}/` and Gennis's
`api/account/overhead_type_logs/{month}/{year}` so the management UI can
consume the same shapes without going through the source services. Read-only
— no writes, no schema changes.

Filter semantics differ from the source routes by design: this proxy filters
on the underlying OverheadType's branch / location, not on the log row's own
branch_id / location_id. The source generators can create logs with a
log-level branch/location that diverges from the parent OverheadType — this
proxy hides those mismatches by joining and filtering on the parent.

Source selection:
- `branch_id` set → Turon
- `location_id` set → Gennis
- neither set → both sources combined (each row tagged with `source`)
- explicit `source` query param wins when set
"""

from datetime import date, datetime
from typing import Optional, Literal, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_gennis_db, get_turon_db
from app.external_models.gennis import (
    CalendarMonth as GennisCalendarMonth,
    CalendarYear as GennisCalendarYear,
    OverheadType as GennisOverheadType,
    OverheadTypeLog as GennisOverheadTypeLog,
)
from app.external_models.turon import (
    OverheadType as TuronOverheadType,
    OverheadTypeLog as TuronOverheadTypeLog,
)


router = APIRouter(prefix="/overhead-type-logs", tags=["Overhead Type Logs"])

StatusFilter = Literal["all", "paid", "unpaid"]
SourceFilter = Literal["gennis", "turon"]


def _format_date(d: Optional[date]) -> Optional[str]:
    return d.strftime("%d.%m.%Y") if d else None


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    total_count = len(rows)
    paid_count = sum(1 for r in rows if r["is_paid"])
    total_sum = sum(r["cost"] for r in rows)
    paid_sum = sum(r["cost"] for r in rows if r["is_paid"])
    return {
        "total_count": total_count,
        "paid_count": paid_count,
        "unpaid_count": total_count - paid_count,
        "total_sum": total_sum,
        "paid_sum": paid_sum,
        "unpaid_sum": total_sum - paid_sum,
    }


def _fetch_turon(
    month: int,
    year: int,
    branch_id: Optional[int],
    status: StatusFilter,
    turon_db: Session,
) -> list[dict[str, Any]]:
    q = (
        turon_db.query(TuronOverheadTypeLog, TuronOverheadType)
        .join(TuronOverheadType, TuronOverheadType.id == TuronOverheadTypeLog.overhead_type_id)
        .filter(
            TuronOverheadTypeLog.deleted == False,
            TuronOverheadTypeLog.date == date(year, month, 1),
        )
    )
    if branch_id is not None:
        q = q.filter(TuronOverheadType.branch_id == branch_id)
    if status == "paid":
        q = q.filter(TuronOverheadTypeLog.is_paid == True)
    elif status == "unpaid":
        q = q.filter(TuronOverheadTypeLog.is_paid == False)

    return [
        {
            "source": "turon",
            "id": log.id,
            "overhead_type_id": log.overhead_type_id,
            "overhead_type_name": ot.name,
            "cost": log.cost or 0,
            "is_paid": bool(log.is_paid),
            "is_prepaid": bool(log.is_prepaid),
            "paid_date": _format_date(log.paid_date.date() if log.paid_date else None),
            "overhead_id": log.overhead_id,
            "branch_id": log.branch_id,
            "date": _format_date(log.date),
        }
        for log, ot in q.order_by(TuronOverheadTypeLog.id).all()
    ]


def _resolve_gennis_calendar_ids(
    month: int, year: int, gennis_db: Session
) -> tuple[Optional[int], Optional[int]]:
    """Look up Gennis CalendarMonth.id and CalendarYear.id by date."""
    year_obj = (
        gennis_db.query(GennisCalendarYear)
        .filter(GennisCalendarYear.date == datetime(year, 1, 1))
        .first()
    )
    if not year_obj:
        return None, None
    month_obj = (
        gennis_db.query(GennisCalendarMonth)
        .filter(GennisCalendarMonth.date == datetime(year, month, 1))
        .first()
    )
    if not month_obj:
        return None, year_obj.id
    return month_obj.id, year_obj.id


def _fetch_gennis(
    month: int,
    year: int,
    location_id: Optional[int],
    status: StatusFilter,
    gennis_db: Session,
) -> list[dict[str, Any]]:
    month_id, year_id = _resolve_gennis_calendar_ids(month, year, gennis_db)
    if not month_id or not year_id:
        return []

    q = (
        gennis_db.query(GennisOverheadTypeLog, GennisOverheadType)
        .join(GennisOverheadType, GennisOverheadType.id == GennisOverheadTypeLog.overhead_type_id)
        .filter(
            GennisOverheadTypeLog.deleted == False,
            GennisOverheadTypeLog.calendar_month == month_id,
            GennisOverheadTypeLog.calendar_year == year_id,
        )
    )
    if location_id is not None:
        q = q.filter(GennisOverheadType.location_id == location_id)
    if status == "paid":
        q = q.filter(GennisOverheadTypeLog.is_paid == True)
    elif status == "unpaid":
        q = q.filter(GennisOverheadTypeLog.is_paid == False)

    return [
        {
            "source": "gennis",
            "id": log.id,
            "overhead_type_id": log.overhead_type_id,
            "overhead_type_name": ot.name,
            "cost": log.cost or 0,
            "is_paid": bool(log.is_paid),
            "is_prepaid": bool(log.is_prepaid),
            "paid_date": _format_date(log.paid_date.date() if log.paid_date else None),
            "overhead_id": log.overhead_id,
            "location_id": log.location_id,
            "calendar_month": log.calendar_month,
            "calendar_year": log.calendar_year,
        }
        for log, ot in q.order_by(GennisOverheadTypeLog.id).all()
    ]


@router.get("/{month}/{year}")
def list_overhead_type_logs(
    month: int,
    year: int,
    branch_id: Optional[int] = Query(None, description="Turon branch filter"),
    location_id: Optional[int] = Query(None, description="Gennis location filter"),
    status: StatusFilter = Query("all", description="Filter by payment status"),
    source: Optional[SourceFilter] = Query(None, description="Restrict to one source"),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")
    if year < 1970 or year > 2100:
        raise HTTPException(status_code=400, detail="year out of range")
    if source == "gennis" and branch_id is not None:
        raise HTTPException(
            status_code=400,
            detail="branch_id does not apply to source=gennis (use location_id)",
        )
    if source == "turon" and location_id is not None:
        raise HTTPException(
            status_code=400,
            detail="location_id does not apply to source=turon (use branch_id)",
        )

    if source is not None:
        include_gennis = source == "gennis"
        include_turon = source == "turon"
    else:
        scope_to_turon = branch_id is not None and location_id is None
        scope_to_gennis = location_id is not None and branch_id is None
        include_gennis = not scope_to_turon
        include_turon = not scope_to_gennis

    data: list[dict[str, Any]] = []
    if include_turon:
        data.extend(_fetch_turon(month, year, branch_id, status, turon_db))
    if include_gennis:
        data.extend(_fetch_gennis(month, year, location_id, status, gennis_db))

    return {
        "success": True,
        "summary": _summary(data),
        "data": data,
    }
