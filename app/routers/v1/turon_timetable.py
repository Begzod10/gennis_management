from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_turon_db
from app.external_models.turon import (
    ClassTimeTable, Hours, Room, WeekDays, Group,
    Teacher, CustomUser, Subject, group_students,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/turon/timetable", tags=["Turon Timetable"])

WEEK_DAYS_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


@router.get("/lessons")
def timetable_lessons(
    branch: int = Query(...),
    student: Optional[int] = Query(None),
    teacher: Optional[int] = Query(None),
    date_str: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    # Use provided date's week, or default to current week
    anchor = date.fromisoformat(date_str) if date_str else date.today()
    start_of_week = anchor - timedelta(days=anchor.weekday())
    week_dates = [start_of_week + timedelta(days=i) for i in range(7)]

    # Pre-fetch rooms and hours for branch
    rooms = db.query(Room).filter(Room.branch_id == branch, Room.deleted == False).order_by(Room.order, Room.id).all()
    hours = db.query(Hours).filter(Hours.branch_id == branch).order_by(Hours.order).all()

    if not rooms or not hours:
        return {"time_tables": [], "hours_list": []}

    # Student group filter
    student_group_ids: Optional[set] = None
    if student:
        g_ids = {r[0] for r in db.execute(
            select(group_students.c.group_id).where(group_students.c.student_id == student)
        ).fetchall()}
        student_group_ids = g_ids

    room_ids = [r.id for r in rooms]
    hour_ids = [h.id for h in hours]

    # Fetch all timetable entries for this branch in current week
    q = (
        db.query(ClassTimeTable)
        .filter(
            ClassTimeTable.branch_id == branch,
            ClassTimeTable.date.in_(week_dates),
            ClassTimeTable.room_id.in_(room_ids),
        )
    )
    if student_group_ids is not None:
        q = q.filter(ClassTimeTable.group_id.in_(student_group_ids))
    if teacher:
        q = q.filter(ClassTimeTable.teacher_id == teacher)

    all_entries = q.all()

    # Build lookup maps
    entry_map: dict = {}
    for e in all_entries:
        entry_map.setdefault((e.date, e.room_id, e.hours_id), e)

    # Pre-fetch groups, teachers, subjects
    group_ids = {e.group_id for e in all_entries if e.group_id}
    teacher_ids = {e.teacher_id for e in all_entries if e.teacher_id}
    subject_ids = {e.subject_id for e in all_entries if e.subject_id}
    user_ids_for_teachers = set()

    groups = {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()} if group_ids else {}
    teachers = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    if teachers:
        user_ids_for_teachers = {t.user_id for t in teachers.values()}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids_for_teachers)).all()} if user_ids_for_teachers else {}
    subj_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()} if subject_ids else {}

    hours_map = {h.id: h for h in hours}
    rooms_map = {r.id: r for r in rooms}

    # Build response
    time_tables = []
    for day_date in week_dates:
        rooms_info = []
        for room in rooms:
            lessons = []
            for hour in hours:
                entry = entry_map.get((day_date, room.id, hour.id))
                if entry:
                    grp = groups.get(entry.group_id)
                    tch = teachers.get(entry.teacher_id)
                    tch_user = t_users.get(tch.user_id) if tch else None
                    subj = subj_map.get(entry.subject_id)
                    lessons.append({
                        "id": entry.id,
                        "status": True,
                        "hours": hour.id,
                        "room": room.id,
                        "group": {"id": grp.id, "name": grp.name} if grp else {},
                        "teacher": {"id": tch.id, "name": f"{tch_user.name} {tch_user.surname}" if tch_user else None} if tch else {},
                        "subject": {"id": subj.id, "name": subj.name} if subj else {},
                    })
                else:
                    lessons.append({"status": False, "hours": hour.id, "room": room.id, "group": {}, "teacher": {}, "subject": {}})
            rooms_info.append({"id": room.id, "name": room.name, "order": room.order, "lessons": lessons})

        time_tables.append({
            "date": day_date.isoformat(),
            "weekday": WEEK_DAYS_UZ[day_date.weekday()],
            "rooms": rooms_info,
        })

    hours_list = [
        {"id": h.id, "name": h.name, "start_time": str(h.start_time), "end_time": str(h.end_time)}
        for h in hours
    ]

    return {"time_tables": time_tables, "hours_list": hours_list}


@router.get("/group/{group_id}")
def group_timetable_list(
    group_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    """Timetable entries for a specific group (current week)."""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    week_dates = [start_of_week + timedelta(days=i) for i in range(7)]

    entries = (
        db.query(ClassTimeTable)
        .filter(ClassTimeTable.group_id == group_id, ClassTimeTable.date.in_(week_dates))
        .order_by(ClassTimeTable.date, ClassTimeTable.hours_id)
        .all()
    )

    if not entries:
        return []

    # Pre-fetch related objects
    teacher_ids = {e.teacher_id for e in entries if e.teacher_id}
    subject_ids = {e.subject_id for e in entries if e.subject_id}
    room_ids = {e.room_id for e in entries if e.room_id}
    hour_ids = {e.hours_id for e in entries if e.hours_id}

    teachers = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    user_ids = {t.user_id for t in teachers.values()}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}
    subjects = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()} if subject_ids else {}
    rooms = {r.id: r for r in db.query(Room).filter(Room.id.in_(room_ids)).all()} if room_ids else {}
    hours_map = {h.id: h for h in db.query(Hours).filter(Hours.id.in_(hour_ids)).all()} if hour_ids else {}

    result = []
    for e in entries:
        tch = teachers.get(e.teacher_id)
        tch_user = t_users.get(tch.user_id) if tch else None
        subj = subjects.get(e.subject_id)
        room = rooms.get(e.room_id)
        hour = hours_map.get(e.hours_id)
        result.append({
            "id": e.id,
            "date": e.date.isoformat() if e.date else None,
            "weekday": WEEK_DAYS_UZ[e.date.weekday()] if e.date else None,
            "hours": {
                "id": hour.id,
                "name": hour.name,
                "start_time": str(hour.start_time),
                "end_time": str(hour.end_time),
            } if hour else None,
            "room": {"id": room.id, "name": room.name} if room else None,
            "teacher": {
                "id": tch.id,
                "name": f"{tch_user.name} {tch_user.surname}" if tch_user else None,
            } if tch else None,
            "subject": {"id": subj.id, "name": subj.name} if subj else None,
        })

    return result


@router.get("/next-lesson")
def check_group_next_lesson(
    id: int = Query(...),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    """Return the next upcoming lesson for a group."""
    today = date.today()
    entry = (
        db.query(ClassTimeTable)
        .filter(ClassTimeTable.group_id == id, ClassTimeTable.date >= today)
        .order_by(ClassTimeTable.date, ClassTimeTable.hours_id)
        .first()
    )

    if not entry:
        return {"next_lesson": None}

    tch = db.query(Teacher).filter(Teacher.id == entry.teacher_id).first() if entry.teacher_id else None
    tch_user = db.query(CustomUser).filter(CustomUser.id == tch.user_id).first() if tch else None
    subj = db.query(Subject).filter(Subject.id == entry.subject_id).first() if entry.subject_id else None
    room = db.query(Room).filter(Room.id == entry.room_id).first() if entry.room_id else None
    hour = db.query(Hours).filter(Hours.id == entry.hours_id).first() if entry.hours_id else None

    return {
        "next_lesson": {
            "id": entry.id,
            "date": entry.date.isoformat() if entry.date else None,
            "weekday": WEEK_DAYS_UZ[entry.date.weekday()] if entry.date else None,
            "hours": {
                "id": hour.id,
                "name": hour.name,
                "start_time": str(hour.start_time),
                "end_time": str(hour.end_time),
            } if hour else None,
            "room": {"id": room.id, "name": room.name} if room else None,
            "teacher": {
                "id": tch.id,
                "name": f"{tch_user.name} {tch_user.surname}" if tch_user else None,
            } if tch else None,
            "subject": {"id": subj.id, "name": subj.name} if subj else None,
        }
    }


@router.get("/hours")
def hours_list(
    branch: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Hours).order_by(Hours.order, Hours.id)
    if branch:
        q = q.filter(Hours.branch_id == branch)
    if search:
        q = q.filter(Hours.name.ilike(f"%{search}%"))
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {
        "count": total,
        "results": [
            {"id": h.id, "name": h.name, "start_time": str(h.start_time), "end_time": str(h.end_time), "order": h.order}
            for h in rows
        ],
    }


@router.get("/week-days")
def week_days_list(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(WeekDays).order_by(WeekDays.order, WeekDays.id).all()
    return [{"id": r.id, "name_uz": r.name_uz, "name_en": r.name_en, "order": r.order} for r in rows]
