from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_turon_db
from app.external_models.turon import (
    Group, GroupSubjects, Subject, ClassNumber, ClassColors, Term, TermTest,
)
from app.routers.v1.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/turon/terms", tags=["Turon Terms"])


@router.get("/list-term/{academic_year}")
def list_term(
    academic_year: str,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    terms = db.query(Term).filter(Term.academic_year == academic_year).all()
    return [
        {
            "id": t.id,
            "quarter": t.quarter,
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "end_date": t.end_date.isoformat() if t.end_date else None,
            "academic_year": t.academic_year,
        }
        for t in terms
    ]


@router.get("/list-test/{term}/{branch}")
def list_test(
    term: int,
    branch: int,
    db: Session = Depends(get_turon_db),
    current_user: User = Depends(get_current_user),
):
    groups = (
        db.query(Group)
        .filter(Group.branch_id == branch, Group.deleted == False)
        .order_by(Group.class_number_id)
        .all()
    )

    # Pre-fetch class numbers and colors for group titles
    cn_ids = {g.class_number_id for g in groups if g.class_number_id}
    color_ids = {g.color_id for g in groups if g.color_id}
    class_numbers = {cn.id: cn for cn in db.query(ClassNumber).filter(ClassNumber.id.in_(cn_ids)).all()} if cn_ids else {}
    colors = {c.id: c for c in db.query(ClassColors).filter(ClassColors.id.in_(color_ids)).all()} if color_ids else {}

    group_ids = [g.id for g in groups]

    # Fetch all GroupSubjects for these groups
    group_subjects_rows = (
        db.query(GroupSubjects)
        .filter(GroupSubjects.group_id.in_(group_ids))
        .all()
    )
    # group_id -> list of unique subject_ids (preserve order, deduplicate)
    group_subject_map: dict = {}
    seen = set()
    for gs in group_subjects_rows:
        key = (gs.group_id, gs.subject_id)
        if key not in seen:
            seen.add(key)
            group_subject_map.setdefault(gs.group_id, []).append(gs.subject_id)

    # Pre-fetch subjects
    all_subject_ids = {sid for sids in group_subject_map.values() for sid in sids}
    subjects_map = {s.id: s for s in db.query(Subject).filter(Subject.id.in_(all_subject_ids)).all()} if all_subject_ids else {}

    # Fetch all tests for these groups / term
    tests = (
        db.query(TermTest)
        .filter(
            TermTest.group_id.in_(group_ids),
            TermTest.term_id == term,
            TermTest.deleted == False,
        )
        .all()
    )
    # (group_id, subject_id) -> list of test dicts
    test_map: dict = {}
    for t in tests:
        test_map.setdefault((t.group_id, t.subject_id), []).append({
            "id": t.id,
            "name": t.name,
            "weight": t.weight,
            "date": t.date.isoformat() if t.date else None,
        })

    result = []
    for g in groups:
        cn = class_numbers.get(g.class_number_id)
        color = colors.get(g.color_id)
        title = g.name if g.name else (
            f"{cn.number} {color.name}" if cn and color else (str(cn.number) if cn else str(g.id))
        )

        children = []
        for subject_id in group_subject_map.get(g.id, []):
            subj = subjects_map.get(subject_id)
            if not subj:
                continue
            children.append({
                "title": subj.name,
                "id": subj.id,
                "type": "subject",
                "tableData": test_map.get((g.id, subject_id), []),
            })

        result.append({
            "title": title,
            "id": g.id,
            "type": "group",
            "children": children,
        })

    return result
