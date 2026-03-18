from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ...database import get_db, get_gennis_db, get_turon_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, Tag, User, ProjectMember, Branch, Project
from ...schemas import (
    MissionCreate, MissionBulkCreate, MissionUpdate, MissionOut, MissionStatusEnum,
    MissionApprove,
)
from ...external_models.gennis import GennisMission, Users as GennisUsers, Staff as GennisStaff, GennisProfessions
from ...external_models.turon import TuronMission, CustomUser as TuronUser, AuthGroup, CustomAutoGroup, ManyBranch
from pydantic import BaseModel


# ── Role-based assignment rules ───────────────────────────────────────────────

ROLE_CAN_ASSIGN: dict[str, set[str]] = {
    "super_admin":      {"director", "dept_head", "project_manager"},
    "director":         {"deputy_director", "dept_head"},
    "ad":               {"teacher", "subject_council", "coordinator"},
    "dept_head":        {"team_lead", "specialist"},
    "deputy_director":  {"class_teacher", "psychologist", "student_president", "sardor"},
    "team_lead":        set(),   # project-scoped check below
    "project_manager":  set(),   # project-scoped check below
    "employee":         {"employee"},  # service_request or self only
}

PROJECT_SCOPED_ROLES = {"team_lead", "project_manager"}


# ── Helpers ───────────────────────────────────────────────────────────────────

class ExternalMissionOut(BaseModel):
    id: int
    source: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    creator_id: Optional[int] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    location_id: Optional[int] = None
    branch_id: Optional[int] = None
    deadline: Optional[str] = None
    finish_date: Optional[str] = None
    kpi_weight: int = 10
    delay_days: int = 0
    final_sc: int = 0
    is_recurring: bool = False
    created_at: Optional[str] = None

router = APIRouter(prefix="/missions", tags=["Missions"])


def _get_or_404(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _validate_role_assignment(
    creator: User,
    executor: User,
    channel: str,
    project_id: Optional[int],
    db: Session,
):
    """Raise 403 if the creator is not allowed to assign to executor."""
    if channel == "service_request":
        return  # cross-dept allowed

    creator_role = creator.role
    executor_role = executor.role

    allowed = ROLE_CAN_ASSIGN.get(creator_role, set())

    if creator_role in PROJECT_SCOPED_ROLES:
        # team_lead / project_manager: executor must be a member of the same project
        if not project_id:
            raise HTTPException(
                status_code=403,
                detail="project_id is required for team_lead/project_manager assignments",
            )
        member = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == executor.id,
            )
            .first()
        )
        if not member:
            raise HTTPException(
                status_code=403,
                detail="Executor is not a member of the specified project",
            )
        return

    if executor_role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{creator_role}' is not allowed to assign missions to role '{executor_role}'",
        )


# ── Owner permission check ───────────────────────────────────────────────────

OWNER_ROLES = {"owner"}

def _check_owner_permission(creator: User, project_id: Optional[int], db: Session):
    """Only the project owner or a top-level role can assign to external directors/managers."""
    if project_id:
        project = db.query(Project).filter(Project.id == project_id, Project.deleted == False).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if creator.id != project.manager_id and creator.role not in OWNER_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Only the project owner can assign missions to external directors/managers",
            )
    else:
        if creator.role not in OWNER_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Only super_admin or director can assign missions to external directors/managers",
            )


# ── Director auto-fill ────────────────────────────────────────────────────────

def _find_gennis_manager(location_id: int, gennis_db: Session) -> Optional[int]:
    """Return the Gennis user ID of the active manager-profession staff for a location."""
    row = (
        gennis_db.query(GennisStaff)
        .join(GennisUsers, GennisStaff.user_id == GennisUsers.id)
        .join(GennisProfessions, GennisStaff.profession_id == GennisProfessions.id)
        .filter(
            GennisUsers.location_id == location_id,
            GennisProfessions.name.ilike("manager"),
            GennisUsers.deleted == False,
            GennisStaff.deleted == False,
        )
        .first()
    )
    return row.user_id if row else None


def _find_turon_director(branch_id: int, turon_db: Session) -> Optional[int]:
    """Return the Turon CustomUser ID of the active director for a branch."""
    from sqlalchemy import or_
    user = (
        turon_db.query(TuronUser)
        .join(CustomAutoGroup, CustomAutoGroup.user_id == TuronUser.id)
        .join(AuthGroup, AuthGroup.id == CustomAutoGroup.group_id)
        .join(ManyBranch, ManyBranch.user_id == TuronUser.id)
        .filter(
            AuthGroup.name == "Direktor",
            ManyBranch.branch_id == branch_id,
            TuronUser.is_active == True,
            or_(CustomAutoGroup.deleted == False, CustomAutoGroup.deleted == None),
        )
        .first()
    )
    return user.id if user else None


# ── Sync helpers ──────────────────────────────────────────────────────────────

def _sync_to_gennis(mission: Mission, gennis_db: Session):
    # Only sync if we have a valid executor to assign in Gennis
    if not mission.gennis_executor_id:
        return
    deadline_dt = datetime.combine(mission.deadline, datetime.min.time()) if mission.deadline else None
    existing = (
        gennis_db.query(GennisMission)
        .filter(GennisMission.management_id == mission.id)
        .first()
    )
    if existing:
        existing.title = mission.title
        existing.description = mission.description
        existing.category = mission.category
        existing.status = mission.status
        existing.deadline_datetime = deadline_dt
        existing.location_id = mission.location_id
        existing.creator_id = mission.gennis_executor_id
        existing.creator_name = "from office"
        existing.executor_id = mission.gennis_executor_id
        existing.kpi_weight = mission.kpi_weight
        existing.delay_days = mission.delay_days
        existing.final_sc = mission.final_sc
    else:
        record = GennisMission(
            management_id=mission.id,
            title=mission.title,
            description=mission.description,
            category=mission.category,
            status=mission.status,
            start_datetime=mission.created_at,
            deadline_datetime=deadline_dt,
            location_id=mission.location_id,
            creator_id=mission.gennis_executor_id,
            creator_name="from office",
            executor_id=mission.gennis_executor_id,
            kpi_weight=mission.kpi_weight,
            delay_days=mission.delay_days,
            final_sc=mission.final_sc,
            created_at=mission.created_at,
        )
        gennis_db.add(record)
    gennis_db.commit()


def _sync_to_turon(mission: Mission, turon_db: Session):
    # Only sync if we have a valid executor to assign in Turon
    if not mission.turon_executor_id:
        return
    existing = (
        turon_db.query(TuronMission)
        .filter(TuronMission.management_id == mission.id)
        .first()
    )
    if existing:
        existing.title = mission.title
        existing.description = mission.description
        existing.category = mission.category
        existing.status = mission.status
        existing.deadline = mission.deadline
        existing.branch_id = mission.branch_id
        existing.creator_id = mission.turon_executor_id
        existing.creator_name = "from office"
        existing.executor_id = mission.turon_executor_id
        existing.kpi_weight = mission.kpi_weight
        existing.delay_days = mission.delay_days
        existing.final_sc = mission.final_sc
    else:
        record = TuronMission(
            management_id=mission.id,
            title=mission.title,
            description=mission.description,
            category=mission.category,
            status=mission.status,
            start_date=mission.created_at.date() if mission.created_at else None,
            deadline=mission.deadline,
            branch_id=mission.branch_id,
            creator_id=mission.turon_executor_id,
            creator_name="from office",
            executor_id=mission.turon_executor_id,
            kpi_weight=mission.kpi_weight,
            delay_days=mission.delay_days,
            final_sc=mission.final_sc,
            created_at=mission.created_at.date() if mission.created_at else None,
        )
        turon_db.add(record)
    turon_db.commit()


def _sync_delete(mission: Mission, gennis_db: Session, turon_db: Session):
    if mission.gennis_executor_id:
        rec = (
            gennis_db.query(GennisMission)
            .filter(GennisMission.management_id == mission.id)
            .first()
        )
        if rec:
            rec.status = "declined"
            gennis_db.commit()
    if mission.turon_executor_id:
        rec = (
            turon_db.query(TuronMission)
            .filter(TuronMission.management_id == mission.id)
            .first()
        )
        if rec:
            rec.status = "declined"
            turon_db.commit()


# ── Mission CRUD ──────────────────────────────────────────────────────────────

@router.post("/", response_model=List[MissionOut], status_code=201)
def create_mission(
    data: MissionCreate,
    creator_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    creator = db.query(User).filter(User.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    base = data.model_dump(exclude={"tag_ids", "executor_ids"})

    # Auto-fill system_id from branch when not explicitly set
    if base.get("branch_id") and not base.get("system_id"):
        branch = db.query(Branch).filter(Branch.id == base["branch_id"]).first()
        if branch and branch.system_model_id:
            base["system_id"] = branch.system_model_id

    # Auto-fill executor IDs from branch/location directors when not explicitly set
    if base.get("location_id") and not base.get("gennis_executor_id"):
        base["gennis_executor_id"] = _find_gennis_manager(base["location_id"], gennis_db)
    if base.get("branch_id") and not base.get("turon_executor_id"):
        base["turon_executor_id"] = _find_turon_director(base["branch_id"], turon_db)

    # Only owners can assign to external directors/managers
    if base.get("gennis_executor_id") or base.get("turon_executor_id"):
        _check_owner_permission(creator, base.get("project_id"), db)

    tags = db.query(Tag).filter(Tag.id.in_(data.tag_ids)).all() if data.tag_ids else []

    created = []
    for executor_id in data.executor_ids:
        executor = db.query(User).filter(User.id == executor_id).first()
        if not executor:
            raise HTTPException(status_code=404, detail=f"Executor {executor_id} not found")
        _validate_role_assignment(creator, executor, data.channel.value, data.project_id, db)

        mission = Mission(**base, executor_id=executor_id, creator_id=creator_id)
        mission.tags = tags
        db.add(mission)
        db.commit()
        db.refresh(mission)
        _sync_to_gennis(mission, gennis_db)
        _sync_to_turon(mission, turon_db)
        created.append(mission)

    return created


@router.post("/bulk", response_model=List[MissionOut], status_code=201)
def create_bulk_missions(
    data: MissionBulkCreate,
    creator_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Create one mission per each internal executor ID, Gennis manager ID, and Turon director ID provided."""
    creator = db.query(User).filter(User.id == creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    if not data.executor_ids and not data.gennis_executor_ids and not data.turon_executor_ids:
        raise HTTPException(status_code=400, detail="At least one executor ID must be provided")

    _check_owner_permission(creator, data.project_id, db)

    base = data.model_dump(exclude={"tag_ids", "executor_ids", "gennis_executor_ids", "turon_executor_ids"})

    # Auto-fill system_id from branch
    if base.get("branch_id") and not base.get("system_id"):
        branch = db.query(Branch).filter(Branch.id == base["branch_id"]).first()
        if branch and branch.system_model_id:
            base["system_id"] = branch.system_model_id

    tags = db.query(Tag).filter(Tag.id.in_(data.tag_ids)).all() if data.tag_ids else []

    created = []

    for executor_id in data.executor_ids:
        executor = db.query(User).filter(User.id == executor_id).first()
        if not executor:
            raise HTTPException(status_code=404, detail=f"Executor {executor_id} not found")
        _validate_role_assignment(creator, executor, data.channel.value, data.project_id, db)
        mission = Mission(**base, executor_id=executor_id, creator_id=creator_id)
        mission.tags = tags
        db.add(mission)
        db.commit()
        db.refresh(mission)
        _sync_to_gennis(mission, gennis_db)
        _sync_to_turon(mission, turon_db)
        created.append(mission)

    for gid in data.gennis_executor_ids:
        mission = Mission(**base, executor_id=creator_id, creator_id=creator_id, gennis_executor_id=gid, turon_executor_id=None)
        mission.tags = tags
        db.add(mission)
        db.commit()
        db.refresh(mission)
        _sync_to_gennis(mission, gennis_db)
        created.append(mission)

    for tid in data.turon_executor_ids:
        mission = Mission(**base, executor_id=creator_id, creator_id=creator_id, turon_executor_id=tid, gennis_executor_id=None)
        mission.tags = tags
        db.add(mission)
        db.commit()
        db.refresh(mission)
        _sync_to_turon(mission, turon_db)
        created.append(mission)

    return created


@router.get("/", response_model=List[MissionOut])
def list_missions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    creator_id: Optional[int] = Query(None),
    executor_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    channel: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Mission).filter(Mission.deleted == False)
    if status:
        q = q.filter(Mission.status == status)
    if category:
        q = q.filter(Mission.category == category)
    if creator_id:
        q = q.filter(Mission.creator_id == creator_id)
    if executor_id:
        q = q.filter(Mission.executor_id == executor_id)
    if branch_id:
        q = q.filter(Mission.branch_id == branch_id)
    if channel:
        q = q.filter(Mission.channel == channel)
    if project_id:
        q = q.filter(Mission.project_id == project_id)
    return q.order_by(Mission.created_at.desc()).all()


@router.get("/{mission_id}", response_model=MissionOut)
def get_mission(mission_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, mission_id)


@router.patch("/{mission_id}", response_model=MissionOut)
def update_mission(
    mission_id: int,
    data: MissionUpdate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_or_404(db, mission_id)

    tag_ids = data.tag_ids
    payload = data.model_dump(exclude_none=True, exclude={"tag_ids"})
    for field, value in payload.items():
        setattr(mission, field, value)

    if tag_ids is not None:
        tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        mission.tags = tags

    if "finish_date" in payload or "deadline" in payload:
        mission.calculate_delay_days()
        mission.final_sc = mission.final_score()

    # Auto-fill system_id from branch if branch changed
    if "branch_id" in payload and not mission.system_id:
        branch = db.query(Branch).filter(Branch.id == mission.branch_id).first()
        if branch and branch.system_model_id:
            mission.system_id = branch.system_model_id

    # Auto-fill executor IDs from location/branch if changed and not explicitly set
    if "location_id" in payload and "gennis_executor_id" not in payload:
        mission.gennis_executor_id = _find_gennis_manager(mission.location_id, gennis_db)
    if "branch_id" in payload and "turon_executor_id" not in payload:
        mission.turon_executor_id = _find_turon_director(mission.branch_id, turon_db)

    db.commit()
    db.refresh(mission)

    _sync_to_gennis(mission, gennis_db)
    _sync_to_turon(mission, turon_db)

    return mission


@router.delete("/{mission_id}", status_code=204)
def delete_mission(
    mission_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_or_404(db, mission_id)
    _sync_delete(mission, gennis_db, turon_db)
    mission.deleted = True
    db.commit()


@router.patch("/{mission_id}/status", response_model=MissionOut)
def change_status(
    mission_id: int,
    status: MissionStatusEnum,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_or_404(db, mission_id)
    mission.status = status.value
    db.commit()
    db.refresh(mission)

    _sync_to_gennis(mission, gennis_db)
    _sync_to_turon(mission, turon_db)

    return mission


@router.patch("/{mission_id}/approve", response_model=MissionOut)
def approve_mission(
    mission_id: int,
    data: MissionApprove,
    approver_id: int,
    db: Session = Depends(get_db),
):
    mission = _get_or_404(db, mission_id)
    mission.approval_status = data.approval_status.value
    mission.approved_by_id = approver_id
    db.commit()
    db.refresh(mission)
    return mission


@router.patch("/{mission_id}/redirect", response_model=MissionOut)
def redirect_mission(
    mission_id: int,
    new_executor_id: int,
    redirected_by_id: int,
    db: Session = Depends(get_db),
):
    mission = _get_or_404(db, mission_id)
    if not db.query(User).filter(User.id == new_executor_id).first():
        raise HTTPException(status_code=404, detail="New executor not found")

    mission.original_executor_id = mission.executor_id
    mission.executor_id = new_executor_id
    mission.redirected_by_id = redirected_by_id
    mission.is_redirected = True
    mission.redirected_at = datetime.utcnow()

    db.commit()
    db.refresh(mission)
    return mission


@router.post("/{mission_id}/complete", response_model=MissionOut)
def complete_mission(
    mission_id: int,
    finish_date: str,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    from datetime import date
    mission = _get_or_404(db, mission_id)
    try:
        mission.finish_date = date.fromisoformat(finish_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
    mission.status = "completed"
    mission.calculate_delay_days()
    mission.final_sc = mission.final_score()
    db.commit()
    db.refresh(mission)

    _sync_to_gennis(mission, gennis_db)
    _sync_to_turon(mission, turon_db)

    return mission


# ── External missions (read-only from Gennis & Turon DBs) ─────────────────────

@router.get("/external/gennis", response_model=dict)
def list_gennis_missions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    location_id: Optional[int] = Query(None),
    executor_id: Optional[int] = Query(None),
    gennis_db: Session = Depends(get_gennis_db),
):
    q = gennis_db.query(GennisMission)
    if status:
        q = q.filter(GennisMission.status == status)
    if category:
        q = q.filter(GennisMission.category == category)
    if location_id:
        q = q.filter(GennisMission.location_id == location_id)
    if executor_id:
        q = q.filter(GennisMission.executor_id == executor_id)

    missions = q.order_by(GennisMission.id.desc()).all()
    results = [
        ExternalMissionOut(
            id=m.id, source="gennis", title=m.title, description=m.description,
            category=m.category, status=m.status, creator_id=m.creator_id,
            executor_id=m.executor_id, reviewer_id=m.reviewer_id,
            location_id=m.location_id, branch_id=None,
            deadline=m.deadline_datetime.date().isoformat() if m.deadline_datetime else None,
            finish_date=m.finish_datetime.date().isoformat() if m.finish_datetime else None,
            kpi_weight=m.kpi_weight, delay_days=m.delay_days, final_sc=m.final_sc,
            is_recurring=m.is_recurring or False,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in missions
    ]
    return {"total": len(results), "results": results}


@router.get("/external/turon", response_model=dict)
def list_turon_missions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    branch_id: Optional[int] = Query(None),
    executor_id: Optional[int] = Query(None),
    turon_db: Session = Depends(get_turon_db),
):
    q = turon_db.query(TuronMission)
    if status:
        q = q.filter(TuronMission.status == status)
    if category:
        q = q.filter(TuronMission.category == category)
    if branch_id:
        q = q.filter(TuronMission.branch_id == branch_id)
    if executor_id:
        q = q.filter(TuronMission.executor_id == executor_id)

    missions = q.order_by(TuronMission.id.desc()).all()
    results = [
        ExternalMissionOut(
            id=m.id, source="turon", title=m.title, description=m.description,
            category=m.category, status=m.status, creator_id=m.creator_id,
            executor_id=m.executor_id, reviewer_id=m.reviewer_id,
            location_id=None, branch_id=m.branch_id,
            deadline=m.deadline.isoformat() if m.deadline else None,
            finish_date=m.finish_date.isoformat() if m.finish_date else None,
            kpi_weight=m.kpi_weight, delay_days=m.delay_days, final_sc=m.final_sc,
            is_recurring=m.is_recurring or False,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in missions
    ]
    return {"total": len(results), "results": results}


@router.get("/external/stats", response_model=dict)
def external_mission_stats(
    location_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    STATUS_LIST = ["not_started", "in_progress", "blocked", "completed", "approved", "declined", "recheck"]

    def by_status(q, model):
        return {s: q.filter(model.status == s).count() for s in STATUS_LIST}

    gq = gennis_db.query(GennisMission)
    if location_id:
        gq = gq.filter(GennisMission.location_id == location_id)

    tq = turon_db.query(TuronMission)
    if branch_id:
        tq = tq.filter(TuronMission.branch_id == branch_id)

    return {
        "gennis": {"total": gq.count(), "by_status": by_status(gq, GennisMission)},
        "turon": {"total": tq.count(), "by_status": by_status(tq, TuronMission)},
    }
