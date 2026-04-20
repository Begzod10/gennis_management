from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, desc
from typing import Optional, List
from datetime import date, timedelta

from app.database import get_gennis_db, get_turon_db, get_db
from app.external_models import gennis as G
from app.external_models import turon as T
from app.models import Dividend, Investment, ApiLog
from app.external_models.turon import TuronApiLog, TuronCustomUser
from app.external_models.gennis import GennisApiLog, Users as GennisUsers
from app.models import User
from app.schemas_stats import (
    ByPaymentType, GennisOverheadSummary, TuronOverheadSummary,
    GennisSummary, TuronSummary, OverviewOut,
    ApiUsageItem, ApiUsageByUserItem,
    TuronApiUsageItem, TuronApiUsageByUserItem,
    SectionUsageItem,
    GennisApiUsageItem, GennisApiUsageByUserItem,
)

# Section prefix rules — longest prefix must come first so matching is unambiguous
_MANAGEMENT_SECTIONS = [
    ("/api/v1/salary-months",            "Oylik maoshlar"),
    ("/api/v1/salary-days",              "Kunlik maoshlar"),
    ("/api/v1/system-models",            "Tizim modellari"),
    ("/api/v1/missions",                 "Topshiriqlar"),
    ("/api/v1/statistics",               "Statistika"),
    ("/api/v1/projects",                 "Loyihalar"),
    ("/api/v1/sections",                 "Bo'limlar"),
    ("/api/v1/branches",                 "Filiallar"),
    ("/api/v1/dividends",                "Dividendlar"),
    ("/api/v1/investments",              "Investitsiyalar"),
    ("/api/v1/notifications",            "Bildirishnomalar"),
    ("/api/v1/combined",                 "Umumiy moliyaviy hisobot"),
    ("/api/v1/calendar",                 "Taqvim"),
    ("/api/v1/telegram",                 "Telegram bot"),
    ("/api/v1/users",                    "Foydalanuvchilar"),
    ("/api/v1/tags",                     "Teglar"),
    ("/api/v1/jobs",                     "Lavozimlar"),
    ("/api/v1/auth",                     "Kirish / Chiqish"),
    ("/api/v1/turon/students",           "Turon — Talabalar"),
    ("/api/v1/turon/teachers",           "Turon — O'qituvchilar"),
    ("/api/v1/turon/classes",            "Turon — Guruhlar"),
    ("/api/v1/turon/timetable",          "Turon — Dars jadvali"),
    ("/api/v1/turon/terms",              "Turon — Semestrlar"),
    ("/api/v1/turon",                    "Turon"),
    ("/api/v1/gennis",                   "Gennis"),
]

_GENNIS_SECTIONS = [
    ("/api/missions",            "Topshiriqlar"),
    ("/api/comment",             "Topshiriq — Izohlar"),
    ("/api/proofs",              "Topshiriq — Hisobotlar"),
    ("/api/attachments",         "Topshiriq — Fayllar"),
    ("/api/subtasks",            "Topshiriq — Kichik vazifalar"),
    ("/api/student",             "Talabalar"),
    ("/api/teacher/assistent",   "Assistentlar"),
    ("/api/teacher",             "O'qituvchilar"),
    ("/api/account",             "Moliya / Hisob"),
    ("/api/group_classroom",     "Guruh sinf"),
    ("/api/create_group",        "Guruh yaratish"),
    ("/api/group",               "Guruhlar"),
    ("/api/time_table",          "Dars jadvali"),
    ("/api/school",              "Maktab"),
    ("/api/lead",                "Lidlar"),
    ("/api/book",                "Kitoblar"),
    ("/api/parent",              "Ota-onalar"),
    ("/api/mobile",              "Mobil"),
    ("/api/home_page",           "Bosh sahifa"),
    ("/api/reports",             "Hisobotlar"),
    ("/api/room",                "Xonalar"),
    ("/api/base",                "Asosiy"),
    ("/api/checks",              "Tekshiruvlar"),
    ("/api/programmers",         "Dasturchilar"),
    ("/api/bot",                 "Bot"),
    ("/api/classroom",           "Sinf xonasi"),
    ("/api/chat-analyzer",       "Chat tahlili"),
    ("/api",                     "Boshqa"),
]

_TURON_SECTIONS = [
    ("/api/SchoolTimeTable/",   "Maktab dars jadvali"),
    ("/api/Lesson_plan/",       "Dars rejalari"),
    ("/api/TimeTable/",         "Dars jadvali"),
    ("/api/Attendance/",        "Davomat"),
    ("/api/Encashment/",        "Inkassatsiya"),
    ("/api/Overhead/",          "Xarajatlar"),
    ("/api/Capital/",           "Kapital"),
    ("/api/Payments/",          "To'lovlar"),
    ("/api/Students/",          "Talabalar"),
    ("/api/Teachers/",          "O'qituvchilar"),
    ("/api/Users/",             "Foydalanuvchilar"),
    ("/api/parents/",           "Ota-onalar"),
    ("/api/Group/",             "Guruhlar"),
    ("/api/Class/",             "Sinflar"),
    ("/api/Flow/",              "Oqimlar"),
    ("/api/Subjects/",          "Fanlar"),
    ("/api/Rooms/",             "Xonalar"),
    ("/api/Branch/",            "Filiallar"),
    ("/api/Location/",          "Joylashuvlar"),
    ("/api/Tasks/",             "Topshiriqlar"),
    ("/api/Observation/",       "Kuzatuvlar"),
    ("/api/Lead/",              "Lidlar"),
    ("/api/Books/",             "Kitoblar"),
    ("/api/Calendar/",          "Taqvim"),
    ("/api/Bot/",               "Bot"),
    ("/api/Parties/",           "Partiyalar"),
    ("/api/reports/",           "Hisobotlar"),
    ("/api/surveys/",           "So'rovnomalar"),
    ("/api/call/",              "Qo'ng'iroqlar"),
    ("/api/v1/investor/",       "Investorlar"),
    ("/api/Permissions/",       "Ruxsatnomalar"),
    ("/api/System/",            "Tizim"),
    ("/api/Language/",          "Tillar"),
    ("/api/Ui/",                "Interfeys"),
    ("/api/Mobile/",            "Mobil"),
    ("/api/terms/",             "Semestrlar"),
    ("/api/token/",             "Kirish / Chiqish"),
    ("/api/get_user/",          "Foydalanuvchi ma'lumoti"),
    ("/api/set_observer/",      "Kuzatuvchi belgilash"),
    ("/api/update_group_datas/","Guruh ma'lumotlari"),
    ("/api/get_group_datas/",   "Guruh ma'lumotlari"),
]


def _classify(path: str, rules: list) -> str:
    for prefix, label in rules:
        if path.startswith(prefix):
            return label
    return "Boshqa"


def _aggregate_sections(rows, rules):
    sections: dict[str, dict] = {}
    for r in rows:
        label = _classify(r.path, rules)
        if label not in sections:
            sections[label] = {"total": 0, "weighted_ms": 0.0}
        sections[label]["total"] += r.total
        sections[label]["weighted_ms"] += (r.avg_ms or 0) * r.total

    grand_total = sum(v["total"] for v in sections.values()) or 1
    result = []
    for label, v in sections.items():
        result.append({
            "section": label,
            "total_requests": v["total"],
            "percentage": round(v["total"] / grand_total * 100, 1),
            "avg_response_ms": round(v["weighted_ms"] / v["total"], 1) if v["total"] else 0.0,
        })
    return sorted(result, key=lambda x: x["total_requests"], reverse=True)

router = APIRouter(prefix="/statistics", tags=["Statistics"])


# ─── API Usage ────────────────────────────────────────────────────────────────

@router.get("/api-usage", response_model=List[ApiUsageItem], tags=["API Usage"])
def api_usage(
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Most and least used API endpoints by request count."""
    q = db.query(
        ApiLog.method,
        ApiLog.path,
        func.count(ApiLog.id).label("total"),
        func.avg(ApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(ApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(ApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(ApiLog.method, ApiLog.path).order_by(desc("total")).limit(limit).all()

    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "method": r.method,
            "path": r.path,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
            "avg_response_ms": round(r.avg_ms or 0, 1),
        }
        for r in rows
    ]


@router.get("/api-usage/by-user", response_model=List[ApiUsageByUserItem], tags=["API Usage"])
def api_usage_by_user(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Request counts per user."""
    q = db.query(
        ApiLog.user_id,
        User.name,
        User.surname,
        func.count(ApiLog.id).label("total"),
    ).outerjoin(User, User.id == ApiLog.user_id).filter(ApiLog.user_id.isnot(None))
    if from_date:
        q = q.filter(ApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(ApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(ApiLog.user_id, User.name, User.surname).order_by(desc("total")).limit(limit).all()
    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "user_id": r.user_id,
            "name": r.name,
            "surname": r.surname,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
        }
        for r in rows
    ]


@router.get("/api-usage/unknown-paths", tags=["API Usage"])
def api_usage_unknown_paths(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Show paths that fall into 'Boshqa' — not matched by any section rule."""
    q = db.query(
        ApiLog.path,
        func.count(ApiLog.id).label("total"),
    )
    if from_date:
        q = q.filter(ApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(ApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(ApiLog.path).order_by(desc("total")).all()

    return [
        {"path": r.path, "total_requests": r.total}
        for r in rows
        if _classify(r.path, _MANAGEMENT_SECTIONS) == "Boshqa"
    ]


@router.get("/api-usage/by-section", response_model=List[SectionUsageItem], tags=["API Usage"])
def api_usage_by_section(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Total usage grouped by feature section (all mission routes combined, all salary routes combined, etc.)."""
    q = db.query(
        ApiLog.path,
        func.count(ApiLog.id).label("total"),
        func.avg(ApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(ApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(ApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(ApiLog.path).all()
    return _aggregate_sections(rows, _MANAGEMENT_SECTIONS)


# ─── Turon API Usage ─────────────────────────────────────────────────────────

@router.get("/turon/api-usage", response_model=List[TuronApiUsageItem], tags=["API Usage"])
def turon_api_usage(
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_turon_db),
):
    """Most and least used Turon API endpoints by request count."""
    q = db.query(
        TuronApiLog.method,
        TuronApiLog.path,
        func.count(TuronApiLog.id).label("total"),
        func.avg(TuronApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(TuronApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(TuronApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(TuronApiLog.method, TuronApiLog.path).order_by(desc("total")).limit(limit).all()
    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "method": r.method,
            "path": r.path,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
            "avg_response_ms": round(r.avg_ms or 0, 1),
        }
        for r in rows
    ]


@router.get("/turon/api-usage/by-user", response_model=List[TuronApiUsageByUserItem], tags=["API Usage"])
def turon_api_usage_by_user(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_turon_db),
):
    """Request counts per user in Turon."""
    q = db.query(
        TuronApiLog.user_id,
        TuronCustomUser.name,
        TuronCustomUser.surname,
        func.count(TuronApiLog.id).label("total"),
    ).outerjoin(TuronCustomUser, TuronCustomUser.id == TuronApiLog.user_id).filter(TuronApiLog.user_id.isnot(None))
    if from_date:
        q = q.filter(TuronApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(TuronApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(TuronApiLog.user_id, TuronCustomUser.name, TuronCustomUser.surname).order_by(desc("total")).limit(limit).all()
    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "user_id": r.user_id,
            "name": r.name,
            "surname": r.surname,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
        }
        for r in rows
    ]


@router.get("/turon/api-usage/by-section", response_model=List[SectionUsageItem], tags=["API Usage"])
def turon_api_usage_by_section(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_turon_db),
):
    """Turon total usage grouped by feature section."""
    q = db.query(
        TuronApiLog.path,
        func.count(TuronApiLog.id).label("total"),
        func.avg(TuronApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(TuronApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(TuronApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(TuronApiLog.path).all()
    return _aggregate_sections(rows, _TURON_SECTIONS)


# ─── Gennis API Usage ─────────────────────────────────────────────────────────

@router.get("/gennis/api-usage", response_model=List[GennisApiUsageItem], tags=["API Usage"])
def gennis_api_usage(
    limit: int = Query(50, ge=1, le=200),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_gennis_db),
):
    """Most and least used Gennis API endpoints by request count."""
    q = db.query(
        GennisApiLog.method,
        GennisApiLog.path,
        func.count(GennisApiLog.id).label("total"),
        func.avg(GennisApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(GennisApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(GennisApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(GennisApiLog.method, GennisApiLog.path).order_by(desc("total")).limit(limit).all()
    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "method": r.method,
            "path": r.path,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
            "avg_response_ms": round(r.avg_ms or 0, 1),
        }
        for r in rows
    ]


@router.get("/gennis/api-usage/by-user", response_model=List[GennisApiUsageByUserItem], tags=["API Usage"])
def gennis_api_usage_by_user(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_gennis_db),
):
    """Request counts per user in Gennis."""
    q = db.query(
        GennisApiLog.user_id,
        GennisUsers.name,
        GennisUsers.surname,
        func.count(GennisApiLog.id).label("total"),
    ).outerjoin(GennisUsers, GennisUsers.id == GennisApiLog.user_id).filter(GennisApiLog.user_id.isnot(None))
    if from_date:
        q = q.filter(GennisApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(GennisApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(GennisApiLog.user_id, GennisUsers.name, GennisUsers.surname).order_by(desc("total")).limit(limit).all()
    grand_total = sum(r.total for r in rows) or 1
    return [
        {
            "user_id": r.user_id,
            "name": r.name,
            "surname": r.surname,
            "total_requests": r.total,
            "percentage": round(r.total / grand_total * 100, 1),
        }
        for r in rows
    ]


@router.get("/gennis/api-usage/by-section", response_model=List[SectionUsageItem], tags=["API Usage"])
def gennis_api_usage_by_section(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_gennis_db),
):
    """Gennis total usage grouped by feature section."""
    q = db.query(
        GennisApiLog.path,
        func.count(GennisApiLog.id).label("total"),
        func.avg(GennisApiLog.response_time_ms).label("avg_ms"),
    )
    if from_date:
        q = q.filter(GennisApiLog.created_at >= from_date)
    if to_date:
        q = q.filter(GennisApiLog.created_at < to_date + timedelta(days=1))
    rows = q.group_by(GennisApiLog.path).all()
    return _aggregate_sections(rows, _GENNIS_SECTIONS)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _get_total(local_db: Session, model, source: str, month, year, location_id=None, branch_id=None) -> int:
    q = local_db.query(
        func.coalesce(func.sum(model.amount), 0)
    ).filter(model.source == source, model.deleted == False)
    if month:
        q = q.filter(extract("month", model.date) == month)
    if year:
        q = q.filter(extract("year", model.date) == year)
    if location_id:
        q = q.filter(model.location_id == location_id)
    if branch_id:
        q = q.filter(model.branch_id == branch_id)
    return q.scalar()



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

@router.get("/gennis/payments", response_model=ByPaymentType)
def gennis_payments(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    location_id: Optional[int] = Query(None),
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
    if location_id:
        rows = rows.filter(G.StudentPayments.location_id == location_id)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/teacher-salaries", response_model=ByPaymentType)
def gennis_teacher_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    location_id: Optional[int] = Query(None),
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
    if location_id:
        rows = rows.filter(G.TeacherSalaries.location_id == location_id)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/staff-salaries", response_model=ByPaymentType)
def gennis_staff_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    location_id: Optional[int] = Query(None),
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
    if location_id:
        rows = rows.filter(G.StaffSalaries.location_id == location_id)
    rows = rows.group_by(G.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/gennis/overheads", response_model=GennisOverheadSummary)
def gennis_overheads(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    location_id: Optional[int] = Query(None),
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
    if location_id:
        item_rows = item_rows.filter(G.Overhead.location_id == location_id)
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
    if location_id:
        type_rows = type_rows.filter(G.Overhead.location_id == location_id)
    type_rows = type_rows.group_by(G.PaymentTypes.name).all()

    grand_total = sum(r.total for r in item_rows)

    return {
        "total": grand_total,
        "by_item": [{"item": r.item_name, "total": r.total} for r in item_rows],
        "by_payment_type": [{"payment_type": r.name, "total": r.total} for r in type_rows],
    }


@router.get("/gennis/summary", response_model=GennisSummary)
def gennis_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    location_id: Optional[int] = Query(None),
    db: Session = Depends(get_gennis_db),
    local_db: Session = Depends(get_db),
):
    """Full Gennis summary: payments, teacher salaries, staff salaries, overheads, dividends, remaining."""
    payments = gennis_payments(month, year, location_id, db)
    teacher_salaries = gennis_teacher_salaries(month, year, location_id, db)
    staff_salaries = gennis_staff_salaries(month, year, location_id, db)
    overheads = gennis_overheads(month, year, location_id, db)
    dividends = _get_total(local_db, Dividend, "gennis", month, year, location_id=location_id)
    investments = _get_total(local_db, Investment, "gennis", month, year, location_id=location_id)

    total_expenses = teacher_salaries["total"] + staff_salaries["total"] + overheads["total"] + dividends
    remaining = payments["total"] + investments - total_expenses

    return {
        "payments": payments,
        "teacher_salaries": teacher_salaries,
        "staff_salaries": staff_salaries,
        "overheads": overheads,
        "dividends": dividends,
        "investments": investments,
        "total_expenses": total_expenses,
        "remaining": remaining,
    }


# ─── Turon ────────────────────────────────────────────────────────────────────

@router.get("/turon/payments", response_model=ByPaymentType)
def turon_payments(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    branch_id: Optional[int] = Query(None),
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
    if branch_id:
        rows = rows.filter(T.StudentPayment.branch_id == branch_id)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/teacher-salaries", response_model=ByPaymentType)
def turon_teacher_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    branch_id: Optional[int] = Query(None),
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
    if branch_id:
        rows = rows.filter(T.TeacherSalaryList.branch_id == branch_id)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/staff-salaries", response_model=ByPaymentType)
def turon_staff_salaries(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    branch_id: Optional[int] = Query(None),
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
    if branch_id:
        rows = rows.filter(T.UserSalaryList.branch_id == branch_id)
    rows = rows.group_by(T.PaymentTypes.name).all()

    by_type = [{"payment_type": r.name, "total": r.total} for r in rows]
    grand_total = sum(r["total"] for r in by_type)

    return {"total": grand_total, "by_payment_type": by_type}


@router.get("/turon/overheads", response_model=TuronOverheadSummary)
def turon_overheads(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    branch_id: Optional[int] = Query(None),
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
    if branch_id:
        type_rows = type_rows.filter(T.Overhead.branch_id == branch_id)
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
    if branch_id:
        pay_rows = pay_rows.filter(T.Overhead.branch_id == branch_id)
    pay_rows = pay_rows.group_by(T.PaymentTypes.name).all()

    grand_total = sum(r.total for r in type_rows)

    return {
        "total": grand_total,
        "by_overhead_type": [{"type": r.name, "total": r.total} for r in type_rows],
        "by_payment_type": [{"payment_type": r.name, "total": r.total} for r in pay_rows],
    }


@router.get("/turon/summary", response_model=TuronSummary)
def turon_summary(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    local_db: Session = Depends(get_db),
):
    """Full Turon summary: payments, teacher salaries, staff salaries, overheads, dividends, remaining."""
    payments = turon_payments(month, year, branch_id, db)
    teacher_salaries = turon_teacher_salaries(month, year, branch_id, db)
    staff_salaries = turon_staff_salaries(month, year, branch_id, db)
    overheads = turon_overheads(month, year, branch_id, db)
    dividends = _get_total(local_db, Dividend, "turon", month, year, branch_id=branch_id)
    investments = _get_total(local_db, Investment, "turon", month, year, branch_id=branch_id)

    total_expenses = teacher_salaries["total"] + staff_salaries["total"] + overheads["total"] + dividends
    remaining = payments["total"] + investments - total_expenses

    return {
        "payments": payments,
        "teacher_salaries": teacher_salaries,
        "staff_salaries": staff_salaries,
        "overheads": overheads,
        "dividends": dividends,
        "investments": investments,
        "total_expenses": total_expenses,
        "remaining": remaining,
    }


# ─── Combined overview ────────────────────────────────────────────────────────

@router.get("/overview", response_model=OverviewOut)
def overview(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    gennis_location_id: Optional[int] = Query(None),
    turon_branch_id: Optional[int] = Query(None),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
    local_db: Session = Depends(get_db),
):
    """Director dashboard: combined stats from both systems."""
    g = gennis_summary(month, year, gennis_location_id, gennis_db, local_db)
    t = turon_summary(month, year, turon_branch_id, turon_db, local_db)

    total_payments = g["payments"]["total"] + t["payments"]["total"]
    total_teacher_salaries = g["teacher_salaries"]["total"] + t["teacher_salaries"]["total"]
    total_staff_salaries = g["staff_salaries"]["total"] + t["staff_salaries"]["total"]
    total_overheads = g["overheads"]["total"] + t["overheads"]["total"]
    total_dividends = g["dividends"] + t["dividends"]
    total_investments = g["investments"] + t["investments"]
    # investments are minus for management (money sent out), dividends are plus (money received)
    total_expenses = total_teacher_salaries + total_staff_salaries + total_overheads + total_investments
    remaining = total_payments + total_dividends - total_expenses

    return {
        "period": {"month": month, "year": year},
        "gennis": g,
        "turon": t,
        "combined": {
            "total_payments": total_payments,
            "total_teacher_salaries": total_teacher_salaries,
            "total_staff_salaries": total_staff_salaries,
            "total_overheads": total_overheads,
            "total_dividends": total_dividends,
            "total_investments": total_investments,
            "total_expenses": total_expenses,
            "remaining": remaining,
        },
    }

