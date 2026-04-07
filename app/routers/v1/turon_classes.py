from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.database import get_turon_db
from app.external_models.turon import (
    ClassNumber, ClassTypes, ClassColors, Language, Teacher, CustomUser,
    Group, Subject, SubjectLevel, Student, Branch, GroupReason,
    StudentMonthlySummary, GroupMonthlySummary, Room,
    group_teachers, group_students,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/turon", tags=["Turon Classes"])


@router.get("/class/class-number-list")
def class_number_list(
    branch: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ClassNumber).order_by(ClassNumber.number)
    if branch:
        q = q.filter(ClassNumber.branch_id == branch)

    rows = q.all()

    ct_ids = {r.class_types_id for r in rows if r.class_types_id}
    class_types = {ct.id: ct for ct in db.query(ClassTypes).filter(ClassTypes.id.in_(ct_ids)).all()}

    return [
        {
            "id": r.id,
            "number": r.number,
            "price": r.price,
            "curriculum_hours": r.curriculum_hours,
            "class_types": (
                {"id": class_types[r.class_types_id].id, "name": class_types[r.class_types_id].name}
                if r.class_types_id and r.class_types_id in class_types else None
            ),
        }
        for r in rows
    ]


@router.get("/class/class-colors")
def class_colors(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(ClassColors).all()
    return [{"id": r.id, "name": r.name, "value": r.value} for r in rows]


@router.get("/language")
def language_list(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Language).all()
    return [{"id": r.id, "name": r.name} for r in rows]


@router.get("/group/create/class/teachers")
def group_create_teachers(
    branch: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Teacher).join(CustomUser, CustomUser.id == Teacher.user_id).filter(Teacher.deleted == False)
    if branch:
        q = q.filter(CustomUser.branch_id == branch)

    rows = q.all()

    user_ids = [t.user_id for t in rows]
    users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()}

    return [
        {
            "id": t.id,
            "name": f"{users[t.user_id].name} {users[t.user_id].surname}" if t.user_id in users else None,
        }
        for t in rows
    ]


# ── Group classes ──────────────────────────────────────────────────────────────

@router.get("/group/classes")
def group_classes(
    branch: Optional[int] = Query(None),
    teacher: Optional[int] = Query(None),
    deleted: Optional[bool] = Query(False),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Group).filter(Group.class_number_id.isnot(None))

    if deleted is not None:
        q = q.filter(Group.deleted == deleted)
    if branch:
        q = q.filter(Group.branch_id == branch)
    if teacher:
        group_ids_for_teacher = {
            r[0] for r in db.execute(
                select(group_teachers.c.group_id).where(group_teachers.c.teacher_id == teacher)
            ).fetchall()
        }
        q = q.filter(Group.id.in_(group_ids_for_teacher))
    if search:
        term = f"%{search}%"
        q = q.filter(Group.name.ilike(term))

    total = q.count()
    groups = q.order_by(Group.class_number_id, Group.id).offset(offset).limit(limit).all()

    group_ids = [g.id for g in groups]

    # Pre-fetch class numbers
    cn_ids = {g.class_number_id for g in groups if g.class_number_id}
    class_numbers = {cn.id: cn for cn in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()} if cn_ids else {}

    # Pre-fetch colors
    color_ids = {g.color_id for g in groups if g.color_id}
    colors = {c.id: c for c in db.query(ClassColors).filter(ClassColors.id.in_(color_ids)).all()} if color_ids else {}

    # Pre-fetch first teacher per group
    teacher_rows = db.execute(
        select(group_teachers.c.group_id, group_teachers.c.teacher_id)
        .where(group_teachers.c.group_id.in_(group_ids))
    ).fetchall()
    group_first_teacher: dict = {}
    for gid, tid in teacher_rows:
        if gid not in group_first_teacher:
            group_first_teacher[gid] = tid

    teacher_ids = set(group_first_teacher.values())
    teachers_objs = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    user_ids = {t.user_id for t in teachers_objs.values()}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}

    # Student counts per group
    student_count_rows = db.execute(
        select(group_students.c.group_id, func.count(group_students.c.student_id))
        .where(group_students.c.group_id.in_(group_ids))
        .group_by(group_students.c.group_id)
    ).fetchall()
    student_counts = {r[0]: r[1] for r in student_count_rows}

    results = []
    for g in groups:
        cn = class_numbers.get(g.class_number_id)
        color = colors.get(g.color_id)
        tid = group_first_teacher.get(g.id)
        t_obj = teachers_objs.get(tid) if tid else None
        u_obj = t_users.get(t_obj.user_id) if t_obj else None
        teacher_name = f"{u_obj.name} {u_obj.surname}" if u_obj else None

        results.append({
            "id": g.id,
            "teacher": teacher_name,
            "status": g.status,
            "name": g.name,
            "count": student_counts.get(g.id, 0),
            "class_number": cn.number if cn else None,
            "color": color.name if color else None,
            "price": g.price,
        })

    return {"count": total, "results": results}


@router.get("/group/classes2")
def group_classes2(
    branch: Optional[int] = Query(None),
    deleted: Optional[bool] = Query(False),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Group).filter(Group.class_number_id.isnot(None))

    if deleted is not None:
        q = q.filter(Group.deleted == deleted)
    if branch:
        q = q.filter(Group.branch_id == branch)

    groups = q.order_by(Group.class_number_id, Group.id).all()
    group_ids = [g.id for g in groups]

    # Pre-fetch class numbers
    cn_ids = {g.class_number_id for g in groups if g.class_number_id}
    class_numbers = {cn.id: cn for cn in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()} if cn_ids else {}

    # Pre-fetch colors
    color_ids = {g.color_id for g in groups if g.color_id}
    colors = {c.id: c for c in db.query(ClassColors).filter(ClassColors.id.in_(color_ids)).all()} if color_ids else {}

    # Pre-fetch languages
    lang_ids = {g.language_id for g in groups if g.language_id}
    languages = {l.id: l for l in db.query(Language).filter(Language.id.in_(lang_ids)).all()} if lang_ids else {}

    # Pre-fetch first teacher per group
    teacher_rows = db.execute(
        select(group_teachers.c.group_id, group_teachers.c.teacher_id)
        .where(group_teachers.c.group_id.in_(group_ids))
    ).fetchall()
    group_first_teacher: dict = {}
    for gid, tid in teacher_rows:
        if gid not in group_first_teacher:
            group_first_teacher[gid] = tid

    teacher_ids = set(group_first_teacher.values())
    teachers_objs = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    user_ids = {t.user_id for t in teachers_objs.values()}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}

    # Students per group
    student_rows = db.execute(
        select(group_students.c.group_id, group_students.c.student_id)
        .where(group_students.c.group_id.in_(group_ids))
    ).fetchall()
    group_student_ids: dict = {}
    for gid, sid in student_rows:
        group_student_ids.setdefault(gid, []).append(sid)

    all_student_ids = {sid for sids in group_student_ids.values() for sid in sids}
    students_map = {s.id: s for s in db.query(Student).filter(Student.id.in_(all_student_ids)).all()} if all_student_ids else {}
    student_user_ids = {s.user_id for s in students_map.values() if s.user_id}
    student_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(student_user_ids)).all()} if student_user_ids else {}

    results = []
    for g in groups:
        cn = class_numbers.get(g.class_number_id)
        color = colors.get(g.color_id)
        lang = languages.get(g.language_id)
        tid = group_first_teacher.get(g.id)
        t_obj = teachers_objs.get(tid) if tid else None
        u_obj = t_users.get(t_obj.user_id) if t_obj else None
        teacher_name = f"{u_obj.name} {u_obj.surname}" if u_obj else None

        s_ids = group_student_ids.get(g.id, [])
        students_list = []
        for sid in s_ids:
            s = students_map.get(sid)
            if not s:
                continue
            su = student_users.get(s.user_id) if s.user_id else None
            students_list.append({
                "id": s.id,
                "name": su.name if su else None,
                "surname": su.surname if su else None,
                "phone": su.phone if su else None,
            })

        results.append({
            "id": g.id,
            "teacher": teacher_name,
            "status": g.status,
            "name": g.name,
            "count": len(s_ids),
            "class_number": cn.number if cn else None,
            "color": color.name if color else None,
            "price": g.price,
            "language": {"id": lang.id, "name": lang.name} if lang else None,
            "students": students_list,
        })

    return results


# ── Subject levels ─────────────────────────────────────────────────────────────

@router.get("/subjects/level-for-subject/{subject_id}")
def level_for_subject(
    subject_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    levels = db.query(SubjectLevel).filter(SubjectLevel.subject_id == subject_id).all()
    subject = db.query(Subject).filter(Subject.id == subject_id).first()

    return [
        {
            "id": lv.id,
            "name": lv.name,
            "subject": {"id": subject.id, "name": subject.name} if subject else None,
            "disabled": lv.disabled,
            "desc": lv.desc,
        }
        for lv in levels
    ]


# ── Subjects ───────────────────────────────────────────────────────────────────

@router.get("/subjects/subject")
def subject_list(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    subjects = db.query(Subject).order_by(Subject.id).all()
    return [{"id": s.id, "name": s.name} for s in subjects]


# ── Group profile ──────────────────────────────────────────────────────────────

@router.get("/group/profile/{group_id}")
def group_profile(
    group_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")

    # Related lookups
    branch = db.query(Branch).filter(Branch.id == g.branch_id).first() if g.branch_id else None
    language = db.query(Language).filter(Language.id == g.language_id).first() if g.language_id else None
    subject = db.query(Subject).filter(Subject.id == g.subject_id).first() if g.subject_id else None
    color = db.query(ClassColors).filter(ClassColors.id == g.color_id).first() if g.color_id else None
    cn = db.query(ClassNumber).filter(ClassNumber.id == g.class_number_id).first() if g.class_number_id else None
    cn_type = db.query(ClassTypes).filter(ClassTypes.id == cn.class_types_id).first() if cn and cn.class_types_id else None

    # Teachers
    teacher_ids = [r[0] for r in db.execute(
        select(group_teachers.c.teacher_id).where(group_teachers.c.group_id == group_id)
    ).fetchall()]
    teachers = db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all() if teacher_ids else []
    t_user_ids = [t.user_id for t in teachers]
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(t_user_ids)).all()} if t_user_ids else {}

    # Students
    student_ids = [r[0] for r in db.execute(
        select(group_students.c.student_id).where(group_students.c.group_id == group_id)
    ).fetchall()]
    students = db.query(Student).filter(Student.id.in_(student_ids)).all() if student_ids else []
    s_user_ids = [s.user_id for s in students]
    s_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(s_user_ids)).all()} if s_user_ids else {}

    return {
        "id": g.id,
        "name": g.name,
        "price": g.price,
        "status": g.status,
        "deleted": g.deleted,
        "branch": {"id": branch.id, "name": branch.name} if branch else None,
        "language": {"id": language.id, "name": language.name} if language else None,
        "subject": {"id": subject.id, "name": subject.name} if subject else None,
        "color": {"id": color.id, "name": color.name, "value": color.value} if color else None,
        "class_number": {
            "id": cn.id,
            "number": cn.number,
            "price": cn.price,
            "curriculum_hours": cn.curriculum_hours,
            "class_types": {"id": cn_type.id, "name": cn_type.name} if cn_type else None,
        } if cn else None,
        "teachers": [
            {
                "id": t.id,
                "name": t_users[t.user_id].name if t.user_id in t_users else None,
                "surname": t_users[t.user_id].surname if t.user_id in t_users else None,
                "phone": t_users[t.user_id].phone if t.user_id in t_users else None,
                "color": t.color,
            }
            for t in teachers
        ],
        "students": [
            {
                "id": s.id,
                "name": s_users[s.user_id].name if s.user_id in s_users else None,
                "surname": s_users[s.user_id].surname if s.user_id in s_users else None,
                "phone": s_users[s.user_id].phone if s.user_id in s_users else None,
                "debt_status": s.debt_status,
            }
            for s in students
        ],
        "count": len(student_ids),
    }


# ── Rooms ─────────────────────────────────────────────────────────────────────

@router.get("/rooms")
def room_list(
    branch: Optional[int] = Query(None),
    deleted: Optional[bool] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Room).order_by(Room.order, Room.id)
    if branch:
        q = q.filter(Room.branch_id == branch)
    if deleted is not None:
        q = q.filter(Room.deleted == deleted)
    rows = q.all()
    return [{"id": r.id, "name": r.name, "order": r.order, "deleted": r.deleted} for r in rows]


# ── Group reason ───────────────────────────────────────────────────────────────

@router.get("/group/group-reason")
def group_reason_list(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(GroupReason).order_by(GroupReason.id).all()
    return [{"id": r.id, "name": r.name} for r in rows]


# ── Attendance periods ─────────────────────────────────────────────────────────

import calendar as _calendar
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta


def _generate_workdays(year: int, month: int) -> list:
    today = _date.today()
    start = _date(year, month, 1)
    end_day = today.day if today.year == year and today.month == month else _calendar.monthrange(year, month)[1]
    end = _date(year, month, end_day)
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.day)
        current += _timedelta(days=1)
    return days


def _normalize_periods(existing: dict, now: _datetime) -> dict:
    cur_year, cur_month, cur_day = now.year, now.month, now.day
    prev_month, prev_year = (12, cur_year - 1) if cur_month == 1 else (cur_month - 1, cur_year)

    folded: dict = {}
    for raw_year, months in existing.items():
        year = int(raw_year)
        ymap = folded.setdefault(year, {})
        for item in months:
            m = int(item["month"])
            days = set(int(d) for d in item.get("days", []))
            ymap[m] = ymap.get(m, set()).union(days)

    for y, m in [(cur_year, cur_month), (prev_year, prev_month)]:
        ymap = folded.setdefault(y, {})
        if m not in ymap:
            ymap[m] = set(_generate_workdays(y, m))

    if cur_year in folded and cur_month in folded[cur_year]:
        folded[cur_year][cur_month] &= set(range(1, cur_day + 1))

    normalized: dict = {}
    for y, ymap in folded.items():
        normalized[y] = [{"month": m, "days": sorted(days)} for m, days in sorted(ymap.items())]
    return normalized


@router.get("/attendance/periods")
def attendance_periods(
    group_id: int = Query(...),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    summaries = (
        db.query(StudentMonthlySummary)
        .filter(StudentMonthlySummary.group_id == group_id)
        .order_by(StudentMonthlySummary.year, StudentMonthlySummary.month)
        .all()
    )

    now = _datetime.now()

    if not summaries:
        today = _date.today()
        return {
            "group_id": group_id,
            "periods": [{"year": today.year, "months": [{"month": today.month, "days": _generate_workdays(today.year, today.month)}]}],
        }

    existing: dict = {}
    for s in summaries:
        existing.setdefault(s.year, [])
        existing[s.year].append({"month": s.month, "days": _generate_workdays(s.year, s.month)})

    normalized = _normalize_periods(existing, now)
    return {
        "group_id": group_id,
        "periods": [{"year": y, "months": normalized[y]} for y in sorted(normalized.keys())],
    }


@router.get("/attendance/monthly")
def attendance_monthly(
    group_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    days_in_month = _calendar.monthrange(year, month)[1]
    days_list = [d for d in range(1, days_in_month + 1) if _calendar.weekday(year, month, d) != 6]

    summary = (
        db.query(GroupMonthlySummary)
        .filter(
            GroupMonthlySummary.group_id == group_id,
            GroupMonthlySummary.year == year,
            GroupMonthlySummary.month == month,
        )
        .first()
    )

    return {"days": days_list, "students": summary.stats if summary else None}
