from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import List, Optional
from datetime import datetime, date
from ...database import get_db, get_gennis_db, get_turon_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, MissionHistory, Tag, User, ProjectMember, Branch, Project, Section, SectionMember
from ...schemas import (
    MissionCreate, MissionBulkCreate, MissionUpdate, MissionOut, MissionStatusEnum,
    MissionApprove, MissionHistoryOut,
)
from ...external_models.gennis import GennisMission, GennisMissionHistory, Users as GennisUsers, Staff as GennisStaff, GennisProfessions, Locations as GennisLocations
from ...external_models.turon import TuronMission, TuronMissionHistory, CustomUser as TuronUser, AuthGroup, CustomAutoGroup, ManyBranch
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

# ── Helpers ───────────────────────────────────────────────────────────────────

class MissionExternalSync(BaseModel):
    """Payload sent by Gennis/Turon when they update a management-originated mission."""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[date] = None
    finish_date: Optional[date] = None
    delay_days: Optional[int] = None
    final_sc: Optional[int] = None
    kpi_weight: Optional[int] = None
    penalty_per_day: Optional[int] = None
    early_bonus_per_day: Optional[int] = None
    max_bonus: Optional[int] = None
    max_penalty: Optional[int] = None


class ExternalMissionOut(BaseModel):
    id: int
    source: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    creator_id: Optional[int] = None
    creator_name: Optional[str] = None
    executor_id: Optional[int] = None
    executor_name: Optional[str] = None
    reviewer_id: Optional[int] = None
    reviewer_name: Optional[str] = None
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


def _log_history(mission: Mission, db: Session, changed_by_id: Optional[int] = None, note: Optional[str] = None) -> MissionHistory:
    entry = MissionHistory(
        mission_id=mission.id,
        changed_by_id=changed_by_id,
        executor_id=mission.executor_id,
        reviewer_id=mission.reviewer_id,
        gennis_executor_id=mission.gennis_executor_id,
        gennis_executor_name=mission.gennis_executor_name,
        gennis_reviewer_id=mission.gennis_reviewer_id,
        gennis_reviewer_name=mission.gennis_reviewer_name,
        turon_executor_id=mission.turon_executor_id,
        turon_executor_name=mission.turon_executor_name,
        turon_reviewer_id=mission.turon_reviewer_id,
        turon_reviewer_name=mission.turon_reviewer_name,
        note=note,
    )
    db.add(entry)
    return entry


def _resolve_user_name(db: Session, user_id: Optional[int]) -> Optional[str]:
    if not user_id:
        return None
    u = db.query(User).filter(User.id == user_id).first()
    return f"{u.name} {u.surname}".strip() if u else None


def _sync_history_to_gennis(entry: MissionHistory, mission: Mission, db: Session, gennis_db: Session):
    gennis_mission = gennis_db.query(GennisMission).filter(GennisMission.management_id == mission.id).first()
    if not gennis_mission:
        return
    kwargs = dict(
        mission_id=gennis_mission.id,
        executor_id=entry.gennis_executor_id,
        reviewer_id=entry.gennis_reviewer_id,
        management_executor_id=entry.executor_id,
        management_executor_name=_resolve_user_name(db, entry.executor_id),
        management_reviewer_id=entry.reviewer_id,
        management_reviewer_name=_resolve_user_name(db, entry.reviewer_id),
        turon_executor_id=entry.turon_executor_id,
        turon_executor_name=entry.turon_executor_name,
        turon_reviewer_id=entry.turon_reviewer_id,
        turon_reviewer_name=entry.turon_reviewer_name,
        changed_by_name=_resolve_user_name(db, entry.changed_by_id),
        note=entry.note,
        created_at=entry.created_at,
    )
    existing = gennis_db.query(GennisMissionHistory).filter(GennisMissionHistory.management_id == entry.id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        gennis_db.add(GennisMissionHistory(management_id=entry.id, **kwargs))
    gennis_db.commit()


def _sync_history_to_turon(entry: MissionHistory, mission: Mission, db: Session, turon_db: Session):
    turon_mission = turon_db.query(TuronMission).filter(TuronMission.management_id == mission.id).first()
    if not turon_mission:
        return
    kwargs = dict(
        mission_id=turon_mission.id,
        executor_id=entry.turon_executor_id,
        reviewer_id=entry.turon_reviewer_id,
        management_executor_id=entry.executor_id,
        management_executor_name=_resolve_user_name(db, entry.executor_id),
        management_reviewer_id=entry.reviewer_id,
        management_reviewer_name=_resolve_user_name(db, entry.reviewer_id),
        gennis_executor_id=entry.gennis_executor_id,
        gennis_executor_name=entry.gennis_executor_name,
        gennis_reviewer_id=entry.gennis_reviewer_id,
        gennis_reviewer_name=entry.gennis_reviewer_name,
        changed_by_name=_resolve_user_name(db, entry.changed_by_id),
        note=entry.note,
        created_at=entry.created_at,
    )
    existing = turon_db.query(TuronMissionHistory).filter(TuronMissionHistory.management_id == entry.id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        turon_db.add(TuronMissionHistory(management_id=entry.id, **kwargs))
    turon_db.commit()


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
    section_id: Optional[int],
    db: Session,
):
    """Raise 403 if the creator is not allowed to assign to executor."""
    if creator.role in OWNER_ROLES:
        return  # owner can assign to anyone
    if channel == "service_request":
        return  # cross-dept allowed

    creator_role = creator.role
    executor_role = executor.role

    if creator_role == "manager":
        if not project_id and not section_id:
            raise HTTPException(
                status_code=403,
                detail="project_id or section_id is required for manager assignments",
            )
        if project_id:
            project = db.query(Project).filter(
                Project.id == project_id,
                Project.manager_id == creator.id,
                Project.deleted == False,
            ).first()
            if not project:
                raise HTTPException(
                    status_code=403,
                    detail="You can only assign missions within projects you manage",
                )
            member = db.query(ProjectMember).filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == executor.id,
            ).first()
            if not member:
                raise HTTPException(
                    status_code=403,
                    detail="Executor is not a member of your project",
                )
        else:
            section = db.query(Section).filter(
                Section.id == section_id,
                Section.leader_id == creator.id,
                Section.deleted == False,
            ).first()
            if not section:
                raise HTTPException(
                    status_code=403,
                    detail="You can only assign missions within sections you lead",
                )
            member = db.query(SectionMember).filter(
                SectionMember.section_id == section_id,
                SectionMember.user_id == executor.id,
            ).first()
            if not member:
                raise HTTPException(
                    status_code=403,
                    detail="Executor is not a member of your section",
                )
        return

    allowed = ROLE_CAN_ASSIGN.get(creator_role, set())
    if executor_role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{creator_role}' is not allowed to assign missions to role '{executor_role}'",
        )


# ── Owner permission check ───────────────────────────────────────────────────

OWNER_ROLES = {"owner"}

def _check_owner_permission(creator: User, db: Session):
    """Only the owner role can assign to Gennis/Turon executors or project members."""
    if creator.role not in OWNER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only owner can assign missions to Gennis/Turon executors or project members",
        )


# ── Director auto-fill ────────────────────────────────────────────────────────

def _get_location_name(location_id: int, gennis_db: Session) -> Optional[str]:
    loc = gennis_db.query(GennisLocations).filter(GennisLocations.id == location_id).first()
    return loc.name if loc else None


def _get_gennis_executor_name(executor_id: int, gennis_db: Session) -> Optional[str]:
    user = gennis_db.query(GennisUsers).filter(GennisUsers.id == executor_id).first()
    return f"{user.name} {user.surname}".strip() if user else None


def _get_turon_executor_name(executor_id: int, turon_db: Session) -> Optional[str]:
    user = turon_db.query(TuronUser).filter(TuronUser.id == executor_id).first()
    return f"{user.name} {user.surname}".strip() if user else None


def _get_gennis_user_name(user_id: int, gennis_db: Session) -> Optional[str]:
    user = gennis_db.query(GennisUsers).filter(GennisUsers.id == user_id).first()
    return f"{user.name} {user.surname}".strip() if user else None


def _get_turon_user_name(user_id: int, turon_db: Session) -> Optional[str]:
    user = turon_db.query(TuronUser).filter(TuronUser.id == user_id).first()
    return f"{user.name} {user.surname}".strip() if user else None


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
    creator_name = (
        f"{mission.creator.name} {mission.creator.surname}".strip()
        if mission.creator else "from office"
    )
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
        existing.creator_id = None
        existing.creator_name = creator_name
        existing.executor_id = mission.gennis_executor_id
        existing.reviewer_id = mission.gennis_reviewer_id
        existing.reviewer_name = mission.gennis_reviewer_name
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
            creator_id=None,
            creator_name=creator_name,
            executor_id=mission.gennis_executor_id,
            reviewer_id=mission.gennis_reviewer_id,
            reviewer_name=mission.gennis_reviewer_name,
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
    creator_name = (
        f"{mission.creator.name} {mission.creator.surname}".strip()
        if mission.creator else "from office"
    )
    if existing:
        existing.title = mission.title
        existing.description = mission.description
        existing.category = mission.category
        existing.status = mission.status
        existing.deadline = mission.deadline
        existing.branch_id = mission.branch_id
        existing.creator_id = None
        existing.creator_name = creator_name
        existing.executor_id = mission.turon_executor_id
        existing.reviewer_id = mission.turon_reviewer_id
        existing.reviewer_name = mission.turon_reviewer_name
        existing.kpi_weight = mission.kpi_weight
        existing.delay_days = mission.delay_days
        existing.final_sc = mission.final_sc
        existing.is_redirected = mission.is_redirected
        existing.repeat_every = mission.repeat_every
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
            creator_id=None,
            creator_name=creator_name,
            executor_id=mission.turon_executor_id,
            reviewer_id=mission.turon_reviewer_id,
            reviewer_name=mission.turon_reviewer_name,
            kpi_weight=mission.kpi_weight,
            delay_days=mission.delay_days,
            final_sc=mission.final_sc,
            is_redirected=bool(mission.is_redirected),
            is_recurring=bool(mission.is_recurring),
            repeat_every=mission.repeat_every or 1,
            created_at=mission.created_at.date() if mission.created_at else None,
            updated_at=mission.updated_at.date() if mission.updated_at else None,
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

    # Auto-fill system_id and branch_name from branch when not explicitly set
    if base.get("branch_id"):
        branch = db.query(Branch).filter(Branch.id == base["branch_id"]).first()
        if branch:
            if not base.get("system_id") and branch.system_model_id:
                base["system_id"] = branch.system_model_id
            base["branch_name"] = branch.name

    # Auto-fill executor IDs from branch/location directors only for owners
    if creator.role in OWNER_ROLES:
        if base.get("location_id") and not base.get("gennis_executor_id"):
            base["gennis_executor_id"] = _find_gennis_manager(base["location_id"], gennis_db)
        if base.get("branch_id") and not base.get("turon_executor_id"):
            base["turon_executor_id"] = _find_turon_director(base["branch_id"], turon_db)

    # Lookup external executor/reviewer names and location name
    if base.get("gennis_executor_id"):
        base["gennis_executor_name"] = _get_gennis_executor_name(base["gennis_executor_id"], gennis_db)
    if base.get("turon_executor_id"):
        base["turon_executor_name"] = _get_turon_executor_name(base["turon_executor_id"], turon_db)
    if base.get("gennis_reviewer_id"):
        base["gennis_reviewer_name"] = _get_gennis_user_name(base["gennis_reviewer_id"], gennis_db)
    if base.get("turon_reviewer_id"):
        base["turon_reviewer_name"] = _get_turon_user_name(base["turon_reviewer_id"], turon_db)
    # Fall back to management reviewer name when no external reviewer ID is set
    if base.get("reviewer_id") and (not base.get("gennis_reviewer_name") or not base.get("turon_reviewer_name")):
        rev = db.query(User).filter(User.id == base["reviewer_id"]).first()
        mgmt_rev_name = f"{rev.name} {rev.surname}".strip() if rev else None
        if mgmt_rev_name:
            if not base.get("gennis_reviewer_name"):
                base["gennis_reviewer_name"] = mgmt_rev_name
            if not base.get("turon_reviewer_name"):
                base["turon_reviewer_name"] = mgmt_rev_name
    if base.get("location_id"):
        base["location_name"] = _get_location_name(base["location_id"], gennis_db)

    # Only owners can assign to external directors/managers
    if base.get("gennis_executor_id") or base.get("turon_executor_id"):
        _check_owner_permission(creator, db)

    tags = db.query(Tag).filter(Tag.id.in_(data.tag_ids)).all() if data.tag_ids else []

    created = []
    for executor_id in data.executor_ids:
        executor = db.query(User).filter(User.id == executor_id).first()
        if not executor:
            raise HTTPException(status_code=404, detail=f"Executor {executor_id} not found")
        _validate_role_assignment(creator, executor, data.channel.value, data.project_id, data.section_id, db)

        mission = Mission(**base, executor_id=executor_id, creator_id=creator_id)
        mission.tags = tags
        db.add(mission)
        db.flush()
        db.refresh(mission)
        entry = _log_history(mission, db, changed_by_id=creator_id, note="initial assignment")
        db.flush()
        _sync_to_gennis(mission, gennis_db)
        _sync_to_turon(mission, turon_db)
        _sync_history_to_gennis(entry, mission, db, gennis_db)
        _sync_history_to_turon(entry, mission, db, turon_db)
        created.append(mission)

    db.commit()
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

    _check_owner_permission(creator, db)

    base = data.model_dump(exclude={"tag_ids", "executor_ids", "gennis_executor_ids", "turon_executor_ids"})

    if base.get("gennis_reviewer_id"):
        base["gennis_reviewer_name"] = _get_gennis_user_name(base["gennis_reviewer_id"], gennis_db)
    if base.get("turon_reviewer_id"):
        base["turon_reviewer_name"] = _get_turon_user_name(base["turon_reviewer_id"], turon_db)
    # Fall back to management reviewer name when no external reviewer ID is set
    if base.get("reviewer_id") and (not base.get("gennis_reviewer_name") or not base.get("turon_reviewer_name")):
        rev = db.query(User).filter(User.id == base["reviewer_id"]).first()
        mgmt_rev_name = f"{rev.name} {rev.surname}".strip() if rev else None
        if mgmt_rev_name:
            if not base.get("gennis_reviewer_name"):
                base["gennis_reviewer_name"] = mgmt_rev_name
            if not base.get("turon_reviewer_name"):
                base["turon_reviewer_name"] = mgmt_rev_name

    tags = db.query(Tag).filter(Tag.id.in_(data.tag_ids)).all() if data.tag_ids else []

    created = []

    for executor_id in data.executor_ids:
        executor = db.query(User).filter(User.id == executor_id).first()
        if not executor:
            raise HTTPException(status_code=404, detail=f"Executor {executor_id} not found")
        _validate_role_assignment(creator, executor, data.channel.value, data.project_id, data.section_id, db)
        mission = Mission(**base, executor_id=executor_id, creator_id=creator_id)
        mission.tags = tags
        db.add(mission)
        db.flush()
        db.refresh(mission)
        _sync_to_gennis(mission, gennis_db)
        _sync_to_turon(mission, turon_db)
        created.append(mission)

    for item in data.gennis_executor_ids:
        gname = _get_gennis_executor_name(item.id, gennis_db)
        mission = Mission(
            **{**base,
               "executor_id": creator_id,
               "creator_id": creator_id,
               "gennis_executor_id": item.id,
               "gennis_executor_name": gname,
               "location_id": item.location_id,
               "location_name": item.location_name,
               "turon_executor_id": None,
               "turon_executor_name": None,
               "branch_id": None,
               "branch_name": None,
            }
        )
        mission.tags = tags
        db.add(mission)
        db.flush()
        db.refresh(mission)
        _sync_to_gennis(mission, gennis_db)
        created.append(mission)

    for item in data.turon_executor_ids:
        tname = _get_turon_executor_name(item.id, turon_db)
        mission = Mission(
            **{**base,
               "executor_id": creator_id,
               "creator_id": creator_id,
               "turon_executor_id": item.id,
               "turon_executor_name": tname,
               "branch_id": item.branch_id,
               "branch_name": item.branch_name,
               "gennis_executor_id": None,
               "gennis_executor_name": None,
               "location_id": None,
               "location_name": None,
            }
        )
        mission.tags = tags
        db.add(mission)
        db.flush()
        db.refresh(mission)
        _sync_to_turon(mission, turon_db)
        created.append(mission)

    db.commit()
    return created


@router.get("/", response_model=List[MissionOut])
def list_missions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    creator_id: Optional[int] = Query(None),
    executor_id: Optional[int] = Query(None),
    reviewer_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    location_id: Optional[int] = Query(None),
    channel: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    section_id: Optional[int] = Query(None),
    overdue: Optional[bool] = Query(None),
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
    if reviewer_id:
        q = q.filter(Mission.reviewer_id == reviewer_id)
    if branch_id:
        q = q.filter(Mission.branch_id == branch_id)
    if location_id:
        q = q.filter(Mission.location_id == location_id)
    if channel:
        q = q.filter(Mission.channel == channel)
    if project_id:
        q = q.filter(Mission.project_id == project_id)
    if section_id:
        q = q.filter(Mission.section_id == section_id)
    if overdue:
        q = q.filter(
            Mission.deadline < date.today(),
            Mission.status.notin_(["completed", "approved"]),
        )
    return q.order_by(Mission.created_at.desc()).all()


@router.get("/{mission_id}", response_model=MissionOut)
def get_mission(mission_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, mission_id)


@router.patch("/{mission_id}", response_model=MissionOut)
def update_mission(
    mission_id: int,
    data: MissionUpdate,
    changed_by_id: Optional[int] = None,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_or_404(db, mission_id)

    old_executor = mission.executor_id
    old_reviewer = mission.reviewer_id
    old_gennis_executor = mission.gennis_executor_id
    old_gennis_reviewer = mission.gennis_reviewer_id
    old_turon_executor = mission.turon_executor_id
    old_turon_reviewer = mission.turon_reviewer_id

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

    # Auto-fill system_id and branch_name from branch if branch changed
    if "branch_id" in payload:
        branch = db.query(Branch).filter(Branch.id == mission.branch_id).first()
        if branch:
            if not mission.system_id and branch.system_model_id:
                mission.system_id = branch.system_model_id
            mission.branch_name = branch.name

    # Auto-fill executor IDs from location/branch if changed and not explicitly set
    if "location_id" in payload and "gennis_executor_id" not in payload:
        mission.gennis_executor_id = _find_gennis_manager(mission.location_id, gennis_db)
    if "branch_id" in payload and "turon_executor_id" not in payload:
        mission.turon_executor_id = _find_turon_director(mission.branch_id, turon_db)

    # Refresh executor/reviewer names and location name whenever IDs change
    if "gennis_executor_id" in payload or "location_id" in payload:
        mission.gennis_executor_name = _get_gennis_executor_name(mission.gennis_executor_id, gennis_db) if mission.gennis_executor_id else None
    if "turon_executor_id" in payload or "branch_id" in payload:
        mission.turon_executor_name = _get_turon_executor_name(mission.turon_executor_id, turon_db) if mission.turon_executor_id else None
    if "gennis_reviewer_id" in payload:
        mission.gennis_reviewer_name = _get_gennis_user_name(mission.gennis_reviewer_id, gennis_db) if mission.gennis_reviewer_id else None
    if "turon_reviewer_id" in payload:
        mission.turon_reviewer_name = _get_turon_user_name(mission.turon_reviewer_id, turon_db) if mission.turon_reviewer_id else None
    if "location_id" in payload:
        mission.location_name = _get_location_name(mission.location_id, gennis_db) if mission.location_id else None

    # Fall back to management reviewer name when no external reviewer name is set
    if "reviewer_id" in payload and mission.reviewer_id:
        rev = db.query(User).filter(User.id == mission.reviewer_id).first()
        mgmt_rev_name = f"{rev.name} {rev.surname}".strip() if rev else None
        if mgmt_rev_name:
            if not mission.gennis_reviewer_name:
                mission.gennis_reviewer_name = mgmt_rev_name
            if not mission.turon_reviewer_name:
                mission.turon_reviewer_name = mgmt_rev_name

    db.commit()
    db.refresh(mission)

    if (
        mission.executor_id != old_executor
        or mission.reviewer_id != old_reviewer
        or mission.gennis_executor_id != old_gennis_executor
        or mission.gennis_reviewer_id != old_gennis_reviewer
        or mission.turon_executor_id != old_turon_executor
        or mission.turon_reviewer_id != old_turon_reviewer
    ):
        entry = _log_history(mission, db, changed_by_id=changed_by_id)
        db.commit()
        _sync_history_to_gennis(entry, mission, db, gennis_db)
        _sync_history_to_turon(entry, mission, db, turon_db)

    _sync_to_gennis(mission, gennis_db)
    _sync_to_turon(mission, turon_db)

    return mission



@router.get("/{mission_id}/history", response_model=List[MissionHistoryOut])
def get_mission_history(mission_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, mission_id)
    entries = (
        db.query(MissionHistory)
        .options(
            selectinload(MissionHistory.changed_by),
            selectinload(MissionHistory.executor),
            selectinload(MissionHistory.reviewer),
        )
        .filter(MissionHistory.mission_id == mission_id)
        .order_by(MissionHistory.created_at.asc())
        .all()
    )
    return [MissionHistoryOut.model_validate(e) for e in entries]


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
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_or_404(db, mission_id)

    new_executor = db.query(User).filter(User.id == new_executor_id).first()
    if not new_executor:
        raise HTTPException(status_code=404, detail="New executor not found")

    redirected_by = db.query(User).filter(User.id == redirected_by_id).first()
    if not redirected_by:
        raise HTTPException(status_code=404, detail="Redirected by user not found")

    # Managers can only redirect to members of their projects or sections
    if redirected_by.role == "manager":
        in_project = (
            db.query(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .filter(
                Project.manager_id == redirected_by.id,
                Project.deleted == False,
                ProjectMember.user_id == new_executor_id,
            )
            .first()
        )
        in_section = (
            db.query(SectionMember)
            .join(Section, Section.id == SectionMember.section_id)
            .filter(
                Section.leader_id == redirected_by.id,
                Section.deleted == False,
                SectionMember.user_id == new_executor_id,
            )
            .first()
        )
        if not in_project and not in_section:
            raise HTTPException(
                status_code=403,
                detail="You can only redirect missions to members of your project or section",
            )

    mission.original_executor_id = mission.executor_id
    mission.executor_id = new_executor_id
    mission.redirected_by_id = redirected_by_id
    mission.is_redirected = True
    mission.redirected_at = datetime.utcnow()

    db.flush()
    entry = _log_history(mission, db, changed_by_id=redirected_by_id, note=f"redirected to {new_executor.name} {new_executor.surname}".strip())
    db.flush()
    _sync_to_gennis(mission, gennis_db)
    _sync_to_turon(mission, turon_db)
    _sync_history_to_gennis(entry, mission, db, gennis_db)
    _sync_history_to_turon(entry, mission, db, turon_db)
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


# ── Reverse sync endpoint (called by Gennis / Turon) ─────────────────────────

@router.patch("/sync/{management_id}", status_code=200)
def sync_from_external(
    management_id: int,
    data: MissionExternalSync,
    db: Session = Depends(get_db),
):
    """
    Called by Gennis or Turon when they update a mission that originated from management.
    Only updates the fields present in the payload.
    """
    mission = db.query(Mission).filter(
        Mission.id == management_id,
        Mission.deleted == False,
    ).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    payload = data.model_dump(exclude_none=True)
    for field, value in payload.items():
        setattr(mission, field, value)

    db.commit()
    return {"ok": True}


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

    user_ids = set()
    for m in missions:
        for uid in (m.creator_id, m.executor_id, m.reviewer_id):
            if uid:
                user_ids.add(uid)
    users = {}
    if user_ids:
        rows = gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        users = {u.id: f"{u.name or ''} {u.surname or ''}".strip() for u in rows}

    results = [
        ExternalMissionOut(
            id=m.id, source="gennis", title=m.title, description=m.description,
            category=m.category, status=m.status, creator_id=m.creator_id,
            creator_name=users.get(m.creator_id),
            executor_id=m.executor_id, executor_name=users.get(m.executor_id),
            reviewer_id=m.reviewer_id, reviewer_name=users.get(m.reviewer_id),
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

    user_ids = set()
    for m in missions:
        for uid in (m.creator_id, m.executor_id, m.reviewer_id):
            if uid:
                user_ids.add(uid)
    users = {}
    if user_ids:
        rows = turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
        users = {u.id: f"{u.name or ''} {u.surname or ''}".strip() for u in rows}

    results = [
        ExternalMissionOut(
            id=m.id, source="turon", title=m.title, description=m.description,
            category=m.category, status=m.status, creator_id=m.creator_id,
            creator_name=users.get(m.creator_id),
            executor_id=m.executor_id, executor_name=users.get(m.executor_id),
            reviewer_id=m.reviewer_id, reviewer_name=users.get(m.reviewer_id),
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
