from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, extract

from app.database import get_turon_db
from app.external_models.turon import (
    Student, CustomUser, DeletedStudent, DeletedNewStudent,
    Group, ClassNumber, ClassColors, Language, GroupReason, Branch,
    StudentCharity, AttendancePerMonth, Subject, StudentExamResult, Teacher,
    student_subjects, group_students,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/turon/students", tags=["Turon Students"])

DEBT_COLOR = {1: "#FACC15", 2: "#FF3130", 0: "#24FF00"}


def _calc_age(birth_date) -> Optional[int]:
    if not birth_date:
        return None
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


@router.get("/new-registered")
def new_registered_students(
    branch: Optional[int] = Query(None),
    language: Optional[int] = Query(None),
    age: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    # IDs to exclude
    deleted_ids = {
        r.student_id for r in
        db.query(DeletedStudent.student_id).filter(DeletedStudent.deleted == False).all()
    }
    deleted_new_ids = {
        r.student_id for r in
        db.query(DeletedNewStudent.student_id).all()
    }
    excluded_ids = deleted_ids | deleted_new_ids

    # Students that have no group (not in group_group_students)
    in_group_ids = {
        r[0] for r in db.execute(select(group_students.c.student_id)).fetchall()
    }

    q = (
        db.query(Student)
        .join(CustomUser, CustomUser.id == Student.user_id)
    )

    if excluded_ids:
        q = q.filter(Student.id.notin_(excluded_ids))
    q = q.filter(Student.id.notin_(in_group_ids))

    if branch:
        q = q.filter(CustomUser.branch_id == branch)
    if language:
        q = q.filter(CustomUser.language_id == language)
    if search:
        term = f"%{search}%"
        q = q.filter(
            CustomUser.name.ilike(term) |
            CustomUser.surname.ilike(term) |
            CustomUser.phone.ilike(term)
        )

    total = q.count()
    students = q.order_by(Student.id.desc()).offset(offset).limit(limit).all()

    # Pre-fetch lookups
    user_ids = [s.user_id for s in students]
    users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()}

    lang_ids = {u.language_id for u in users.values() if u.language_id}
    langs = {l.id: l.name for l in db.query(Language).filter(Language.id.in_(lang_ids)).all()}

    cn_ids = {s.class_number_id for s in students if s.class_number_id}
    class_numbers = {c.id: c.number for c in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()}

    results = []
    for s in students:
        u = users.get(s.user_id)

        # age filter (post-query since birth_date is a date field)
        if age is not None and u and u.birth_date:
            if _calc_age(u.birth_date) != age:
                continue

        results.append({
            "id": s.id,
            "user": {
                "id": s.id,
                "name": u.name if u else None,
                "surname": u.surname if u else None,
                "phone": u.phone if u else None,
                "age": _calc_age(u.birth_date) if u else None,
                "registered_date": u.registered_date.isoformat() if u and u.registered_date else None,
                "language": langs.get(u.language_id) if u else None,
            },
            "group": {"id": None, "name": None, "class_number": None, "color": None},
            "color": DEBT_COLOR.get(s.debt_status, ""),
            "debt": u.balance if u else None,
            "class_number": class_numbers.get(s.class_number_id) if s.class_number_id else None,
            "comment": u.comment if u else None,
            "face_id": u.face_id if u else None,
        })

    return {"count": total, "results": results}


@router.get("/deleted-group")
def deleted_group_students(
    branch: Optional[int] = Query(None),
    language: Optional[int] = Query(None),
    age: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    deleted_new_ids = {
        r.student_id for r in db.query(DeletedNewStudent.student_id).all()
    }
    deleted_student_ids = {
        r.student_id for r in
        db.query(DeletedStudent.student_id).filter(DeletedStudent.deleted == False).all()
    }

    q = (
        db.query(DeletedStudent)
        .join(Student, Student.id == DeletedStudent.student_id)
        .join(CustomUser, CustomUser.id == Student.user_id)
        .filter(
            DeletedStudent.deleted == False,
            DeletedStudent.student_id.in_(deleted_student_ids),
            DeletedStudent.student_id.notin_(deleted_new_ids),
        )
    )

    if branch:
        q = q.filter(CustomUser.branch_id == branch)
    if language:
        q = q.filter(CustomUser.language_id == language)
    if search:
        term = f"%{search}%"
        q = q.filter(
            CustomUser.name.ilike(term) |
            CustomUser.surname.ilike(term) |
            CustomUser.phone.ilike(term)
        )

    total = q.count()
    records = q.order_by(DeletedStudent.deleted_date.desc()).offset(offset).limit(limit).all()

    # Pre-fetch
    student_ids = [r.student_id for r in records]
    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()}

    user_ids = [s.user_id for s in students.values()]
    users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()}

    lang_ids = {u.language_id for u in users.values() if u.language_id}
    langs = {l.id: l.name for l in db.query(Language).filter(Language.id.in_(lang_ids)).all()}

    group_ids = {r.group_id for r in records if r.group_id}
    groups = {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()}

    reason_ids = {r.group_reason_id for r in records if r.group_reason_id}
    reasons = {gr.id: gr for gr in db.query(GroupReason).filter(GroupReason.id.in_(reason_ids)).all()}

    results = []
    for r in records:
        s = students.get(r.student_id)
        u = users.get(s.user_id) if s else None

        if age is not None and u and u.birth_date:
            if _calc_age(u.birth_date) != age:
                continue

        grp = groups.get(r.group_id)
        reason = reasons.get(r.group_reason_id)

        results.append({
            "id": r.id,
            "student": {
                "id": s.id if s else None,
                "name": u.name if u else None,
                "surname": u.surname if u else None,
                "age": _calc_age(u.birth_date) if u else None,
                "phone": u.phone if u else None,
                "registered_date": u.registered_date.isoformat() if u and u.registered_date else None,
            },
            "group": {"id": grp.id if grp else None, "name": grp.name if grp else None},
            "group_reason": {"id": reason.id if reason else None, "name": reason.name if reason else None},
            "deleted_date": r.deleted_date.isoformat() if r.deleted_date else None,
            "comment": r.comment,
        })

    return {"count": total, "results": results}


@router.get("/active")
def active_students(
    branch: Optional[int] = Query(None),
    language: Optional[int] = Query(None),
    age: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    # Students in groups
    in_group_ids = {
        r[0] for r in db.execute(select(group_students.c.student_id)).fetchall()
    }

    # Deleted students whose student has NO group (deleted=False)
    deleted_no_group_ids = {
        r.student_id for r in
        db.query(DeletedStudent.student_id)
        .filter(DeletedStudent.deleted == False, DeletedStudent.student_id.notin_(in_group_ids))
        .all()
    }
    deleted_new_ids = {
        r.student_id for r in db.query(DeletedNewStudent.student_id).all()
    }
    excluded_ids = deleted_no_group_ids | deleted_new_ids

    q = (
        db.query(Student)
        .join(CustomUser, CustomUser.id == Student.user_id)
        .filter(Student.id.in_(in_group_ids))
    )
    if excluded_ids:
        q = q.filter(Student.id.notin_(excluded_ids))

    if branch:
        q = q.filter(CustomUser.branch_id == branch)
    if language:
        q = q.filter(CustomUser.language_id == language)
    if search:
        term = f"%{search}%"
        q = q.filter(
            CustomUser.name.ilike(term) |
            CustomUser.surname.ilike(term) |
            CustomUser.phone.ilike(term)
        )

    total = q.count()
    students = q.join(ClassNumber, ClassNumber.id == Student.class_number_id, isouter=True) \
                .order_by(ClassNumber.number).offset(offset).limit(limit).all()

    # Pre-fetch lookups
    student_ids = [s.id for s in students]
    user_ids = [s.user_id for s in students]

    users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()}

    lang_ids = {u.language_id for u in users.values() if u.language_id}
    langs = {l.id: l.name for l in db.query(Language).filter(Language.id.in_(lang_ids)).all()}

    cn_ids = {s.class_number_id for s in students if s.class_number_id}
    class_numbers = {c.id: c.number for c in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()}

    # First group per student (lowest id)
    rows = db.execute(
        select(group_students.c.student_id, group_students.c.group_id)
        .where(group_students.c.student_id.in_(student_ids))
        .order_by(group_students.c.group_id)
    ).fetchall()
    student_group_id: dict = {}
    for student_id, group_id in rows:
        if student_id not in student_group_id:
            student_group_id[student_id] = group_id

    group_ids = set(student_group_id.values())
    groups = {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()}

    color_ids = {g.color_id for g in groups.values() if g.color_id}
    colors = {c.id: c.name for c in db.query(ClassColors).filter(ClassColors.id.in_(color_ids)).all()}

    results = []
    for s in students:
        u = users.get(s.user_id)

        if age is not None and u and u.birth_date:
            if _calc_age(u.birth_date) != age:
                continue

        grp = groups.get(student_group_id.get(s.id))
        group_data = {
            "id": grp.id if grp else None,
            "name": grp.name if grp else None,
            "class_number": class_numbers.get(grp.class_number_id) if grp else None,
            "color": colors.get(grp.color_id) if grp else None,
        }

        results.append({
            "id": s.id,
            "user": {
                "id": s.id,
                "name": u.name if u else None,
                "surname": u.surname if u else None,
                "phone": u.phone if u else None,
                "age": _calc_age(u.birth_date) if u else None,
                "registered_date": u.registered_date.isoformat() if u and u.registered_date else None,
                "language": langs.get(u.language_id) if u else None,
            },
            "group": group_data,
            "color": DEBT_COLOR.get(s.debt_status, ""),
            "debt": u.balance if u else None,
            "class_number": class_numbers.get(s.class_number_id) if s.class_number_id else None,
            "comment": u.comment if u else None,
            "face_id": u.face_id if u else None,
        })

    return {"count": total, "results": results}


# ── Student exam results ──────────────────────────────────────────────────────

@router.get("/student-exam-results")
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

    student_ids = {r.student_id for r in rows}
    teacher_ids = {r.teacher_id for r in rows}
    group_ids = {r.group_id for r in rows}
    subject_ids = {r.subject_id for r in rows}

    students_map = {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()} if student_ids else {}
    s_user_ids = {s.user_id for s in students_map.values() if s.user_id}
    s_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(s_user_ids)).all()} if s_user_ids else {}

    teachers_map = {t.id: t for t in db.query(Teacher).filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    t_user_ids = {t.user_id for t in teachers_map.values() if t.user_id}
    t_users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(t_user_ids)).all()} if t_user_ids else {}

    groups_map = {g.id: g for g in db.query(Group).filter(Group.id.in_(group_ids)).all()} if group_ids else {}
    subjects_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()} if subject_ids else {}

    return [
        {
            "id": r.id,
            "title": r.title,
            "score": r.score,
            "datetime": r.datetime.isoformat() if r.datetime else None,
            "student": r.student_id,
            "student_name": s_users[students_map[r.student_id].user_id].name if r.student_id in students_map and students_map[r.student_id].user_id in s_users else None,
            "student_surname": s_users[students_map[r.student_id].user_id].surname if r.student_id in students_map and students_map[r.student_id].user_id in s_users else None,
            "teacher": r.teacher_id,
            "teacher_name": t_users[teachers_map[r.teacher_id].user_id].name if r.teacher_id in teachers_map and teachers_map[r.teacher_id].user_id in t_users else None,
            "teacher_surname": t_users[teachers_map[r.teacher_id].user_id].surname if r.teacher_id in teachers_map and teachers_map[r.teacher_id].user_id in t_users else None,
            "group": r.group_id,
            "group_name": groups_map[r.group_id].name if r.group_id in groups_map else None,
            "subject": r.subject_id,
            "subject_name": subjects_map[r.subject_id].name if r.subject_id in subjects_map else None,
        }
        for r in rows
    ]


# ── Student detail ────────────────────────────────────────────────────────────

@router.get("/{student_id}")
def get_student(
    student_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")

    u = db.query(CustomUser).filter(CustomUser.id == s.user_id).first()
    lang = db.query(Language).filter(Language.id == u.language_id).first() if u and u.language_id else None
    branch = db.query(Branch).filter(Branch.id == u.branch_id).first() if u and u.branch_id else None
    cn = db.query(ClassNumber).filter(ClassNumber.id == s.class_number_id).first() if s.class_number_id else None

    g_ids = [r[0] for r in db.execute(select(group_students.c.group_id).where(group_students.c.student_id == student_id)).fetchall()]
    groups = db.query(Group).filter(Group.id.in_(g_ids)).all() if g_ids else []

    sub_ids = [r[0] for r in db.execute(select(student_subjects.c.subject_id).where(student_subjects.c.student_id == student_id)).fetchall()]
    subjects = db.query(Subject).filter(Subject.id.in_(sub_ids)).all() if sub_ids else []

    cn_map = {c.id: c.number for c in db.query(ClassNumber).filter(ClassNumber.id.in_([g.class_number_id for g in groups if g.class_number_id])).all()}
    color_map = {c.id: c.name for c in db.query(ClassColors).filter(ClassColors.id.in_([g.color_id for g in groups if g.color_id])).all()}

    return {
        "id": s.id,
        "user": {
            "id": u.id if u else None,
            "name": u.name if u else None,
            "surname": u.surname if u else None,
            "phone": u.phone if u else None,
            "birth_date": u.birth_date.isoformat() if u and u.birth_date else None,
            "registered_date": u.registered_date.isoformat() if u and u.registered_date else None,
            "language": {"id": lang.id, "name": lang.name} if lang else None,
            "balance": u.balance if u else None,
            "comment": u.comment if u else None,
            "face_id": u.face_id if u else None,
            "branch": {"id": branch.id, "name": branch.name} if branch else None,
        },
        "parents_number": s.parents_number,
        "shift": s.shift,
        "debt_status": s.debt_status,
        "color": DEBT_COLOR.get(s.debt_status, ""),
        "class_number": {"id": cn.id, "number": cn.number} if cn else None,
        "subjects": [{"id": sub.id, "name": sub.name} for sub in subjects],
        "groups": [{"id": g.id, "name": g.name, "class_number": cn_map.get(g.class_number_id), "color": color_map.get(g.color_id)} for g in groups],
    }


# ── Student charities ─────────────────────────────────────────────────────────

@router.get("/{student_id}/charities")
def student_charities(
    student_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    charity = db.query(StudentCharity).filter(StudentCharity.student_id == student_id).first()
    if not charity:
        return None
    return {"id": charity.id, "charity_sum": charity.charity_sum, "name": charity.name}


# ── Payment months ────────────────────────────────────────────────────────────

@router.get("/{student_id}/payment-months")
def student_payment_months(
    student_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Student).filter(Student.id == student_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Student not found")

    g_ids = [r[0] for r in db.execute(select(group_students.c.group_id).where(group_students.c.student_id == student_id)).fetchall()]
    group_id = g_ids[0] if g_ids else None

    if not group_id:
        last_deleted = db.query(DeletedStudent).filter(DeletedStudent.student_id == student_id).order_by(DeletedStudent.id.desc()).first()
        group_id = last_deleted.group_id if last_deleted else None

    if not group_id:
        return []

    months = (
        db.query(AttendancePerMonth)
        .filter(AttendancePerMonth.student_id == student_id, AttendancePerMonth.group_id == group_id, AttendancePerMonth.status == False)
        .order_by(AttendancePerMonth.month_date)
        .all()
    )

    return [
        {"id": m.id, "name": m.month_date.strftime("%B"), "number": m.month_date.strftime("%m"), "price": m.remaining_debt}
        for m in months if m.month_date
    ]


# ── Missing attendance months ─────────────────────────────────────────────────

@router.get("/{student_id}/missing-months")
def missing_months(
    student_id: int,
    ay: Optional[int] = Query(None, description="Academic year start (e.g. 2025 for 2025-2026)"),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    academic_start_year = ay if ay else (today.year if today.month >= 9 else today.year - 1)
    start_date = date(academic_start_year, 9, 1)
    end_date = date(academic_start_year + 1, 7, 1)

    g_ids = [r[0] for r in db.execute(select(group_students.c.group_id).where(group_students.c.student_id == student_id)).fetchall()]
    group_id = g_ids[0] if g_ids else None

    if not group_id:
        last_deleted = db.query(DeletedStudent).filter(DeletedStudent.student_id == student_id).order_by(DeletedStudent.id.desc()).first()
        group_id = last_deleted.group_id if last_deleted else None

    if not group_id:
        return {"month": [], "data": []}

    attendances = (
        db.query(AttendancePerMonth)
        .join(Group, Group.id == AttendancePerMonth.group_id)
        .filter(
            AttendancePerMonth.student_id == student_id,
            AttendancePerMonth.group_id == group_id,
            AttendancePerMonth.month_date >= start_date,
            AttendancePerMonth.month_date < end_date,
            Group.deleted == False,
        )
        .order_by(AttendancePerMonth.month_date)
        .all()
    )

    month_list, data = [], []
    for a in attendances:
        if not a.month_date:
            continue
        month_list.append({"id": a.id, "name": a.month_date.strftime("%B"), "number": int(a.month_date.strftime("%m")), "year": a.month_date.year})
        data.append({"id": a.id, "month_date": a.month_date.isoformat(), "total_debt": a.total_debt, "remaining_debt": a.remaining_debt, "discount": a.discount, "status": a.status, "payment": a.payment})

    return {"month": month_list, "data": data}
