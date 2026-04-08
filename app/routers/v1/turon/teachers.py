from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_turon_db
from app.external_models.turon import (
    Teacher, CustomUser, Subject, Language, Group, ClassTypes, Branch, TeacherSalaryType,
    teacher_subjects, group_teachers,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/turon/teachers", tags=["Turon Teachers"])


def _calc_age(birth_date) -> Optional[int]:
    if not birth_date:
        return None
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _teacher_has_group(teacher_id: int, db: Session) -> bool:
    row = db.execute(
        select(group_teachers.c.group_id)
        .join(Group, Group.id == group_teachers.c.group_id)
        .where(group_teachers.c.teacher_id == teacher_id, Group.deleted == False)
        .limit(1)
    ).fetchone()
    return row is not None


def _build_teacher_dict(t: Teacher, u: CustomUser | None, subjects: list, status: bool) -> dict:
    return {
        "id": t.id,
        "user_id": u.id if u else None,
        "name": u.name if u else None,
        "surname": u.surname if u else None,
        "phone": u.phone if u else None,
        "username": u.phone if u else None,  # Turon uses phone as username
        "age": _calc_age(u.birth_date) if u else None,
        "face_id": u.face_id if u else None,
        "color": t.color,
        "deleted": t.deleted,
        "subjects": [{"id": s.id, "name": s.name} for s in subjects],
        "status": status,
    }


# ── Teacher list ──────────────────────────────────────────────────────────────

@router.get("/")
def list_teachers(
    branch: Optional[int] = Query(None),
    deleted: Optional[bool] = Query(None),
    language: Optional[int] = Query(None),
    subject: Optional[int] = Query(None),
    age: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Teacher).join(CustomUser, CustomUser.id == Teacher.user_id)

    if deleted is not None:
        q = q.filter(Teacher.deleted == deleted)
    if branch:
        q = q.filter(CustomUser.branch_id == branch)
    if language:
        q = q.filter(CustomUser.language_id == language)
    if subject:
        teacher_ids_with_subject = {
            r[0] for r in db.execute(
                select(teacher_subjects.c.teacher_id).where(teacher_subjects.c.subject_id == subject)
            ).fetchall()
        }
        q = q.filter(Teacher.id.in_(teacher_ids_with_subject))
    if search:
        term = f"%{search}%"
        q = q.filter(
            CustomUser.name.ilike(term) |
            CustomUser.surname.ilike(term) |
            CustomUser.phone.ilike(term)
        )

    total = q.count()
    teachers = q.order_by(Teacher.id).offset(offset).limit(limit).all()

    # Pre-fetch
    teacher_ids = [t.id for t in teachers]
    user_ids = [t.user_id for t in teachers]
    users = {u.id: u for u in db.query(CustomUser).filter(CustomUser.id.in_(user_ids)).all()}

    subj_rows = db.execute(
        select(teacher_subjects.c.teacher_id, teacher_subjects.c.subject_id)
        .where(teacher_subjects.c.teacher_id.in_(teacher_ids))
    ).fetchall()
    subj_ids = {r[1] for r in subj_rows}
    subj_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(subj_ids)).all()} if subj_ids else {}
    teacher_subj: dict = {}
    for tid, sid in subj_rows:
        teacher_subj.setdefault(tid, []).append(subj_map[sid])

    # Status: teacher is free if not in any active group
    group_teacher_ids = {
        r[0] for r in db.execute(
            select(group_teachers.c.teacher_id)
            .join(Group, Group.id == group_teachers.c.group_id)
            .where(group_teachers.c.teacher_id.in_(teacher_ids), Group.deleted == False)
        ).fetchall()
    }

    results = []
    for t in teachers:
        u = users.get(t.user_id)
        if age is not None and u and u.birth_date:
            if _calc_age(u.birth_date) != age:
                continue
        results.append(_build_teacher_dict(t, u, teacher_subj.get(t.id, []), t.id not in group_teacher_ids))

    return {"count": total, "results": results}




@router.get("/salary-types")
def teacher_salary_types(
    branch: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(TeacherSalaryType)
    if branch:
        q = q.filter(TeacherSalaryType.branch_id == branch)
    rows = q.all()
    branch_ids = {r.branch_id for r in rows if r.branch_id}
    branches = {b.id: b for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()} if branch_ids else {}
    return [
        {
            "id": r.id,
            "name": r.name,
            "salary": r.salary,
            "branch": {"id": branches[r.branch_id].id, "name": branches[r.branch_id].name} if r.branch_id in branches else None,
        }
        for r in rows
    ]


# ── Teacher detail ────────────────────────────────────────────────────────────

@router.get("/{teacher_id}")
def get_teacher(
    teacher_id: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    t = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Teacher not found")

    u = db.query(CustomUser).filter(CustomUser.id == t.user_id).first()
    lang = db.query(Language).filter(Language.id == u.language_id).first() if u and u.language_id else None
    branch = db.query(Branch).filter(Branch.id == u.branch_id).first() if u and u.branch_id else None
    class_type = db.query(ClassTypes).filter(ClassTypes.id == t.class_type_id).first() if t.class_type_id else None

    subj_ids = [r[0] for r in db.execute(
        select(teacher_subjects.c.subject_id).where(teacher_subjects.c.teacher_id == teacher_id)
    ).fetchall()]
    subjects = db.query(Subject).filter(Subject.id.in_(subj_ids)).all() if subj_ids else []

    group_ids = [r[0] for r in db.execute(
        select(group_teachers.c.group_id).where(group_teachers.c.teacher_id == teacher_id)
    ).fetchall()]
    groups = db.query(Group).filter(Group.id.in_(group_ids), Group.deleted == False).all() if group_ids else []

    status = len(groups) == 0

    return {
        "id": t.id,
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
        "color": t.color,
        "deleted": t.deleted,
        "class_type": {"id": class_type.id, "name": class_type.name} if class_type else None,
        "subjects": [{"id": s.id, "name": s.name} for s in subjects],
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "status": status,
    }


@router.get("/salary-types")
def salary_type_list(
    branch: Optional[int] = Query(None),
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(TeacherSalaryType)
    if branch:
        q = q.filter(TeacherSalaryType.branch_id == branch)
    rows = q.all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "salary": r.salary,
            "branch_id": r.branch_id,
        }
        for r in rows
    ]
