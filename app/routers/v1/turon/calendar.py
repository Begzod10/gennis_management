from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_turon_db
from app.external_models.turon import (
    TuronTypeDay, TuronCalendarYear, TuronCalendarMonth, TuronCalendarDay,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def _build_months(db, year_obj, type_map, month_filter=None):
    months_out = []
    for month_obj in db.query(TuronCalendarMonth).filter(
        TuronCalendarMonth.years_id == year_obj.id
    ).order_by(TuronCalendarMonth.month_number).all():
        if month_filter and month_obj.month_number not in month_filter:
            continue

        days = db.query(TuronCalendarDay).filter(
            TuronCalendarDay.month_id == month_obj.id,
            TuronCalendarDay.year_id == year_obj.id,
        ).order_by(TuronCalendarDay.day_number).all()

        days_out = []
        types: list = []
        for d in days:
            t = type_map.get(d.type_id_id)
            day_dict = {
                "id": d.id,
                "day_number": d.day_number,
                "day_name": d.day_name,
                "type_id": t,
            }
            days_out.append(day_dict)
            if t:
                for grp in types:
                    if grp["type"] == t["type"] and grp["color"] == t["color"]:
                        grp["days"].append(day_dict)
                        break
                else:
                    types.append({"type": t["type"], "color": t["color"], "days": [day_dict]})

        months_out.append({
            "month_number": month_obj.month_number,
            "month_name": month_obj.month_name,
            "days": days_out,
            "types": types,
        })
    return months_out



@router.get("/{year}")
def get_calendar_year(
    year: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    type_map = {t.id: {"id": t.id, "type": t.type, "color": t.color}
                for t in db.query(TuronTypeDay).all()}

    year_obj = db.query(TuronCalendarYear).filter(TuronCalendarYear.year == year).first()
    if not year_obj:
        return {"calendar": []}

    return {"calendar": [{"year": year_obj.year, "months": _build_months(db, year_obj, type_map)}]}


@router.get("/{current_year}/{next_year}")
def get_calendar(
    current_year: int,
    next_year: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    type_map = {t.id: {"id": t.id, "type": t.type, "color": t.color}
                for t in db.query(TuronTypeDay).all()}

    result = []
    for year_obj in db.query(TuronCalendarYear).filter(
        TuronCalendarYear.year.between(current_year, next_year)
    ).order_by(TuronCalendarYear.year).all():
        # academic year split: current_year → Jan–Aug, next_year → Sep–Dec
        if year_obj.year == current_year:
            month_filter = set(range(1, 9))
        else:
            month_filter = set(range(9, 13))

        months = _build_months(db, year_obj, type_map, month_filter)
        result.append({"year": year_obj.year, "months": months})

    return {"calendar": result}
