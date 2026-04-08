from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.database import get_turon_db
from app.external_models.turon import (
    ClassNumber, ClassTypes, ClassColors, Language, Teacher, CustomUser,
    Group, Subject, SubjectLevel, Student, Branch, GroupReason,
    StudentMonthlySummary, GroupMonthlySummary, StudentDailyAttendance, Room,
    CustomAutoGroup, AuthGroup, Term, StudentExamResult,
    Flow, flow_students,
    group_teachers, group_students, teacher_subjects,
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


@router.get("/attendance/branch-daily/{branch_id}")
def attendance_branch_daily(
    branch_id: int,
    day: int = Query(...),
    month: int = Query(...),
    year: int = Query(...),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import date as _date_cls
    target_date = _date_cls(year, month, day)

    groups = (
        db.query(Group)
        .filter(Group.branch_id == branch_id, Group.deleted == False)
        .order_by(Group.class_number_id)
        .all()
    )
    group_ids = [g.id for g in groups]

    # Fetch all StudentMonthlySummary for these groups in the given year/month
    summaries = (
        db.query(StudentMonthlySummary)
        .filter(
            StudentMonthlySummary.group_id.in_(group_ids),
            StudentMonthlySummary.year == year,
            StudentMonthlySummary.month == month,
        )
        .all()
    )
    summary_ids = [s.id for s in summaries]
    # summary_id -> (student_id, group_id)
    summary_meta = {s.id: (s.student_id, s.group_id) for s in summaries}

    # Fetch daily attendance records for target date
    daily_records = (
        db.query(StudentDailyAttendance)
        .filter(
            StudentDailyAttendance.monthly_summary_id.in_(summary_ids),
            StudentDailyAttendance.day == target_date,
        )
        .all()
    )
    # group_id -> {student_id -> status}
    rec_map: dict = {}
    for r in daily_records:
        sid, gid = summary_meta.get(r.monthly_summary_id, (None, None))
        if gid and sid:
            rec_map.setdefault(gid, {})[sid] = r.status

    # Fetch students per group
    student_rows = db.execute(
        select(group_students.c.group_id, group_students.c.student_id)
        .where(group_students.c.group_id.in_(group_ids))
    ).fetchall()
    group_student_ids: dict = {}
    for gid, sid in student_rows:
        group_student_ids.setdefault(gid, []).append(sid)

    all_student_ids = {sid for sids in group_student_ids.values() for sid in sids}
    students_map = {s.id: s for s in db.query(Student).filter(Student.id.in_(all_student_ids)).all()} if all_student_ids else {}
    user_ids = {s.user_id for s in students_map.values() if s.user_id}
    users_map = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}

    branch_present = branch_absent = branch_total = 0
    group_list = []

    for g in groups:
        s_ids = group_student_ids.get(g.id, [])
        g_rec = rec_map.get(g.id, {})
        present = absent = 0
        student_data = []

        for sid in s_ids:
            st = students_map.get(sid)
            u = users_map.get(st.user_id) if st else None
            status_val = g_rec.get(sid, None)
            if status_val is True:
                present += 1
                branch_present += 1
            elif status_val is False:
                absent += 1
                branch_absent += 1
            student_data.append({
                "id": sid,
                "name": u.name if u else None,
                "surname": u.surname if u else None,
                "status": status_val,
            })

        branch_total += len(s_ids)
        group_list.append({
            "group_id": g.id,
            "group_name": g.name,
            "students": student_data,
            "summary": {"present": present, "absent": absent, "total": len(s_ids)},
        })

    return {
        "branch_id": branch_id,
        "date": str(target_date),
        "groups": group_list,
        "overall_summary": {"present": branch_present, "absent": branch_absent, "total": branch_total},
    }


# ── Employees ──────────────────────────────────────────────────────────────────

@router.get("/users/employees")
def employees_list(
    branch: Optional[int] = Query(None),
    deleted: Optional[bool] = Query(False),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    from datetime import date as _date_cls

    q = db.query(CustomAutoGroup)
    if deleted is not None:
        q = q.filter(CustomAutoGroup.deleted == deleted)

    if branch:
        user_ids_in_branch = [
            u.id for u in db.query(CustomUser).filter(CustomUser.branch_id == branch).all()
        ]
        q = q.filter(CustomAutoGroup.user_id.in_(user_ids_in_branch))

    total = q.count()
    rows = q.offset(offset).limit(limit).all()

    user_ids = {r.user_id for r in rows if r.user_id}
    group_ids = {r.group_id for r in rows if r.group_id}

    users_map = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}
    groups_map = {g.id: g for g in db.query(AuthGroup).filter(AuthGroup.id.in_(group_ids)).all()} if group_ids else {}

    def calc_age(birth_date):
        if not birth_date:
            return None
        today = _date_cls.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    results = []
    for r in rows:
        u = users_map.get(r.user_id)
        g = groups_map.get(r.group_id)
        full_name = " ".join(filter(None, [
            u.name if u else None,
            u.surname if u else None,
            u.father_name if u else None,
        ]))
        results.append({
            "id": r.id,
            "user_id": u.id if u else None,
            "name": full_name or None,
            "phone": u.phone if u else None,
            "age": calc_age(u.birth_date) if u else None,
            "job": g.name if g else None,
        })

    return {"count": total, "results": results}


@router.get("/users/employees/{employer_id}")
def employee_detail(
    employer_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    emp = db.query(CustomAutoGroup).filter(
        CustomAutoGroup.id == employer_id,
        CustomAutoGroup.deleted == False,
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employer not found")

    u = db.query(CustomUser).filter(CustomUser.id == emp.user_id).first() if emp.user_id else None
    g = db.query(AuthGroup).filter(AuthGroup.id == emp.group_id).first() if emp.group_id else None
    branch = db.query(Branch).filter(Branch.id == u.branch_id).first() if u and u.branch_id else None
    lang = db.query(Language).filter(Language.id == u.language_id).first() if u and u.language_id else None

    def calc_age(birth_date):
        if not birth_date:
            return None
        from datetime import date as _d
        today = _d.today()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    return {
        "id": emp.id,
        "deleted": emp.deleted,
        "group": {"id": g.id, "name": g.name} if g else None,
        "user": {
            "id": u.id if u else None,
            "name": u.name if u else None,
            "surname": u.surname if u else None,
            "father_name": u.father_name if u else None,
            "phone": u.phone if u else None,
            "comment": u.comment if u else None,
            "registered_date": u.registered_date.isoformat() if u and u.registered_date else None,
            "birth_date": u.birth_date.isoformat() if u and u.birth_date else None,
            "age": calc_age(u.birth_date) if u else None,
            "balance": u.balance if u else None,
            "face_id": u.face_id if u else None,
            "language": {"id": lang.id, "name": lang.name} if lang else None,
            "branch": {"id": branch.id, "name": branch.name} if branch else None,
        },
    }


# ── Groups by class type ───────────────────────────────────────────────────────

@router.get("/group/groups-by-class-type")
def groups_by_class_type(
    branch_id: int = Query(...),
    class_type_id: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import or_
    from app.external_models.turon import GroupSubjects

    q = db.query(Group).filter(Group.branch_id == branch_id, Group.deleted == False)

    if class_type_id:
        q = q.filter(or_(Group.class_type_id == class_type_id, Group.class_type_id.is_(None)))
    else:
        q = q.filter(Group.class_type_id.is_(None))

    groups = q.order_by(Group.class_number_id).all()
    group_ids = [g.id for g in groups]

    cn_ids = {g.class_number_id for g in groups if g.class_number_id}
    color_ids = {g.color_id for g in groups if g.color_id}
    ct_ids = {g.class_type_id for g in groups if g.class_type_id}

    class_numbers = {cn.id: cn for cn in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()} if cn_ids else {}
    colors = {c.id: c for c in db.query(ClassColors).filter(ClassColors.id.in_(color_ids)).all()} if color_ids else {}
    class_types = {ct.id: ct for ct in db.query(ClassTypes).filter(ClassTypes.id.in_(ct_ids)).all()} if ct_ids else {}

    gs_rows = db.query(GroupSubjects).filter(GroupSubjects.group_id.in_(group_ids)).all()
    gs_map: dict = {}
    seen_gs: set = set()
    for gs in gs_rows:
        key = (gs.group_id, gs.subject_id)
        if key not in seen_gs:
            seen_gs.add(key)
            gs_map.setdefault(gs.group_id, []).append(gs)

    all_subject_ids = {gs.subject_id for gs in gs_rows}
    subjects_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(all_subject_ids)).all()} if all_subject_ids else {}

    data = []
    for g in groups:
        cn = class_numbers.get(g.class_number_id)
        color = colors.get(g.color_id)
        ct = class_types.get(g.class_type_id)
        gs_list = gs_map.get(g.id, [])
        overall_hours = sum((gs.hours or 0) for gs in gs_list)
        status_class_type = bool(class_type_id and g.class_type_id == class_type_id)

        data.append({
            "id": g.id,
            "class_number": cn.number if cn else None,
            "color": color.name if color else None,
            "class_type": ct.name if ct else None,
            "price": g.price,
            "subjects": [
                {
                    "subject_id": gs.subject_id,
                    "subject": subjects_map[gs.subject_id].name if gs.subject_id in subjects_map else None,
                    "hours": gs.hours,
                    "count": gs.count,
                }
                for gs in gs_list
            ],
            "status_class_type": status_class_type,
            "overall_hours": overall_hours,
        })

    return {"data": data}

# ── Education years ────────────────────────────────────────────────────────────

CURRENT_EDUCATION_YEAR = "2025-2026"

@router.get("/terms/education-years")
def education_years(
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Term.academic_year).distinct().all()
    years = sorted(
        {r[0] for r in rows if r[0]},
        key=lambda y: (0 if y == CURRENT_EDUCATION_YEAR else 1, [-int(x) for x in y.split("-")]),
    )
    return [{"academic_year": y} for y in years]


# ── Class types ────────────────────────────────────────────────────────────────

@router.get("/class/class-types")
def class_types_list(
    branch: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    types = db.query(ClassTypes).order_by(ClassTypes.id).all()

    cn_q = db.query(ClassNumber)
    if branch:
        cn_q = cn_q.filter(ClassNumber.branch_id == branch)
    class_numbers = cn_q.all()

    cn_by_type: dict = {}
    for cn in class_numbers:
        if cn.class_types_id:
            cn_by_type.setdefault(cn.class_types_id, []).append(cn)

    return [
        {
            "id": t.id,
            "name": t.name,
            "class_numbers": [
                {"id": cn.id, "status": True, "number": cn.number}
                for cn in cn_by_type.get(t.id, [])
            ],
        }
        for t in types
    ]


# ── Student exam results ───────────────────────────────────────────────────────

@router.get("/students/student-exam-results")
def student_exam_results(
    teacher: Optional[int] = Query(None),
    group: Optional[int] = Query(None),
    student: Optional[int] = Query(None),
    subject: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import extract
    q = db.query(StudentExamResult)
    if teacher:
        q = q.filter(StudentExamResult.teacher_id == teacher)
    if group:
        q = q.filter(StudentExamResult.group_id == group)
    if student:
        q = q.filter(StudentExamResult.student_id == student)
    if subject:
        q = q.filter(StudentExamResult.subject_id == subject)
    if year:
        q = q.filter(extract("year", StudentExamResult.datetime) == year)
    if month:
        q = q.filter(extract("month", StudentExamResult.datetime) == month)

    rows = q.order_by(StudentExamResult.datetime.desc()).all()

    # Pre-fetch related objects
    student_ids = {r.student_id for r in rows}
    teacher_ids = {r.teacher_id for r in rows}
    group_ids = {r.group_id for r in rows}
    subject_ids = {r.subject_id for r in rows}

    students_map = {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    teachers_map = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    groups_map = {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()} if group_ids else {}
    subjects_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()} if subject_ids else {}

    s_user_ids = {s.user_id for s in students_map.values() if s.user_id}
    t_user_ids = {t.user_id for t in teachers_map.values() if t.user_id}
    all_user_ids = s_user_ids | t_user_ids
    users_map = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(all_user_ids)).all()} if all_user_ids else {}

    results = []
    for r in rows:
        st = students_map.get(r.student_id)
        st_user = users_map.get(st.user_id) if st else None
        tch = teachers_map.get(r.teacher_id)
        tch_user = users_map.get(tch.user_id) if tch else None
        grp = groups_map.get(r.group_id)
        subj = subjects_map.get(r.subject_id)
        results.append({
            "id": r.id,
            "title": r.title,
            "score": r.score,
            "datetime": r.datetime.isoformat() if r.datetime else None,
            "student": r.student_id,
            "student_name": st_user.name if st_user else None,
            "student_surname": st_user.surname if st_user else None,
            "teacher": r.teacher_id,
            "teacher_name": tch_user.name if tch_user else None,
            "teacher_surname": tch_user.surname if tch_user else None,
            "group": r.group_id,
            "group_name": grp.name if grp else None,
            "subject": r.subject_id,
            "subject_name": subj.name if subj else None,
        })

    return results


# ── Flows ──────────────────────────────────────────────────────────────────────

@router.get("/flow/flow-list")
def flow_list(
    branch: Optional[int] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Flow).order_by(Flow.order)
    if branch:
        q = q.filter(Flow.branch_id == branch)

    total = q.count()
    flows = q.offset(offset).limit(limit).all()
    flow_ids = [f.id for f in flows]

    # Pre-fetch related
    subject_ids = {f.subject_id for f in flows if f.subject_id}
    teacher_ids = {f.teacher_id for f in flows if f.teacher_id}
    level_ids = {f.level_id for f in flows if f.level_id}
    branch_ids = {f.branch_id for f in flows if f.branch_id}

    subjects_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()} if subject_ids else {}
    teachers_map = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    user_ids = {t.user_id for t in teachers_map.values() if t.user_id}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()} if user_ids else {}
    levels_map = {lv.id: lv for lv in db.query(SubjectLevel).filter(SubjectLevel.id.in_(level_ids)).all()} if level_ids else {}
    branches_map = {b.id: b for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()} if branch_ids else {}

    # Student counts per flow
    count_rows = db.execute(
        select(flow_students.c.flow_id, func.count(flow_students.c.student_id))
        .where(flow_students.c.flow_id.in_(flow_ids))
        .group_by(flow_students.c.flow_id)
    ).fetchall()
    student_counts = {r[0]: r[1] for r in count_rows}

    results = []
    for f in flows:
        subj = subjects_map.get(f.subject_id)
        tch = teachers_map.get(f.teacher_id)
        tch_user = t_users.get(tch.user_id) if tch else None
        level = levels_map.get(f.level_id)
        branch_obj = branches_map.get(f.branch_id)

        results.append({
            "id": f.id,
            "name": f.name,
            "activity": f.activity,
            "classes": f.classes,
            "subject_name": subj.name if subj else None,
            "teacher_name": tch_user.name if tch_user else None,
            "teacher_surname": tch_user.surname if tch_user else None,
            "student_count": student_counts.get(f.id, 0),
            "level_name": level.name if level else None,
            "branch_name": branch_obj.name if branch_obj else None,
            "type": "flow",
        })

    return {"count": total, "results": results}


# ── Flow profile ───────────────────────────────────────────────────────────────

@router.get("/flow/flow-profile/{flow_id}")
def flow_profile(
    flow_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    f = db.query(Flow).filter(Flow.id == flow_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Flow not found")

    subject = db.query(Subject).filter(Subject.id == f.subject_id).first() if f.subject_id else None
    level = db.query(SubjectLevel).filter(SubjectLevel.id == f.level_id).first() if f.level_id else None

    # Teacher
    tch = db.query(Teacher).filter(Teacher.id == f.teacher_id).first() if f.teacher_id else None
    tch_user = db.query(CustomUser).filter(CustomUser.id == tch.user_id).first() if tch else None
    tch_subj_ids = [r[0] for r in db.execute(
        select(teacher_subjects.c.subject_id).where(teacher_subjects.c.teacher_id == f.teacher_id)
    ).fetchall()] if f.teacher_id else []
    tch_subjects = db.query(Subject).filter(Subject.id.in_(tch_subj_ids)).all() if tch_subj_ids else []

    # Students
    student_ids = [r[0] for r in db.execute(
        select(flow_students.c.student_id).where(flow_students.c.flow_id == flow_id)
    ).fetchall()]
    students = db.query(Student).filter(Student.id.in_(student_ids)).all() if student_ids else []
    s_user_ids = [s.user_id for s in students if s.user_id]
    s_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(s_user_ids)).all()} if s_user_ids else {}

    return {
        "id": f.id,
        "name": f.name,
        "level_name": level.name if level else None,
        "activity": f.activity,
        "subject_name": subject.name if subject else None,
        "subject_id": f.subject_id,
        "teacher": {
            "id": tch.id,
            "name": tch_user.name if tch_user else None,
            "surname": tch_user.surname if tch_user else None,
            "subject": [{"id": s.id, "name": s.name} for s in tch_subjects],
        } if tch else None,
        "students": [
            {
                "id": s.id,
                "name": s_users[s.user_id].name if s.user_id in s_users else None,
                "surname": s_users[s.user_id].surname if s.user_id in s_users else None,
                "phone": s_users[s.user_id].phone if s.user_id in s_users else None,
                "parents_phone": s.parents_number,
                "balance": s_users[s.user_id].balance if s.user_id in s_users else None,
            }
            for s in students
        ],
        "type": "flow",
        "classes": f.classes,
        "order_by": f.order,
    }
