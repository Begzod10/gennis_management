"""Mobile project / section scope endpoints.

The mission create form on mobile needs to know which projects and sections
the caller can assign work in. These endpoints return that scope so the UI
can present a project/section picker that's pre-filtered to legitimate
choices — chained with `/mobile/users/eligible-executors?project_id=...`
to produce the final executor list.

Management-only. Gennis and Turon don't model projects or sections; calls
from those systems return an empty list rather than 403 so the mobile UI
can render the same screen without branching on system.
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import MobileIdentity, MobileProjectOut, MobileSectionOut
from app.models import Project, ProjectMember, Section, SectionMember


router = APIRouter(prefix="/mobile", tags=["Mobile - Scopes"])


@router.get("/projects", response_model=List[MobileProjectOut])
def list_my_projects(
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
):
    """Projects the caller manages or is a member of.

    Manager rows come first so the mobile UI can show them at the top —
    those are the projects where the caller can actually create missions.
    """
    if identity.system != "management":
        return []

    managed = (
        db.query(Project)
        .filter(Project.manager_id == identity.external_id, Project.deleted == False)
        .order_by(Project.name.asc())
        .all()
    )
    managed_ids = {p.id for p in managed}

    member_rows = (
        db.query(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(
            ProjectMember.user_id == identity.external_id,
            Project.deleted == False,
        )
        .order_by(Project.name.asc())
        .all()
    )

    result: List[MobileProjectOut] = [
        MobileProjectOut(id=p.id, name=p.name, description=p.description, role="manager")
        for p in managed
    ]
    for p in member_rows:
        if p.id in managed_ids:
            continue  # caller manages it; manager row already emitted
        result.append(MobileProjectOut(
            id=p.id, name=p.name, description=p.description, role="member",
        ))
    return result


@router.get("/sections", response_model=List[MobileSectionOut])
def list_my_sections(
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
):
    """Sections the caller leads or is a member of.

    Leader rows come first so the mobile UI can prioritize sections where
    the caller can assign work.
    """
    if identity.system != "management":
        return []

    led = (
        db.query(Section)
        .filter(Section.leader_id == identity.external_id, Section.deleted == False)
        .order_by(Section.name.asc())
        .all()
    )
    led_ids = {s.id for s in led}

    member_rows = (
        db.query(Section)
        .join(SectionMember, SectionMember.section_id == Section.id)
        .filter(
            SectionMember.user_id == identity.external_id,
            Section.deleted == False,
        )
        .order_by(Section.name.asc())
        .all()
    )

    result: List[MobileSectionOut] = [
        MobileSectionOut(id=s.id, name=s.name, role="leader") for s in led
    ]
    for s in member_rows:
        if s.id in led_ids:
            continue
        result.append(MobileSectionOut(id=s.id, name=s.name, role="member"))
    return result
