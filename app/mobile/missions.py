"""Unified mission endpoints for the mobile app.

The route paths stay the same regardless of which system the caller lives
in — the JWT carries `system` + `external_id`, and each handler dispatches
to the appropriate database internally. The response shape is normalised
into `MobileMissionOut` so the mobile client doesn't have to care.

For management users we read management.missions (executor or reviewer of
the caller). For gennis/turon users we read missions.executor_id (or
tasks_mission.executor_id) on the corresponding source DB, which covers
BOTH management-originated missions that were synced down AND native
missions created internally by directors/managers.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import (
    get_db,
    get_gennis_db,
    get_gennis_write_db,
    get_turon_db,
    get_turon_write_db,
)
from app.external_models.gennis import (
    GennisMission,
    Users as GennisUsers,
)
from app.external_models.turon import (
    TuronMission,
    CustomUser as TuronUser,
)
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import (
    MobileApprovalStatus,
    MobileIdentity,
    MobileMissionApprove,
    MobileMissionComplete,
    MobileMissionCreate,
    MobileMissionList,
    MobileMissionOut,
    MobileMissionRedirect,
    MobileMissionUpdate,
    MobileStatusUpdate,
)
from app.models import Mission, User
from app.routers.v1.management.missions import (
    _log_history,
    _sync_delete,
    _sync_history_to_gennis,
    _sync_history_to_turon,
    _sync_to_gennis,
    _sync_to_turon,
    _tg,
    _tg_external,
    _tg_mission_externals,
)
from app.services.telegram import (
    tpl_approved,
    tpl_assigned,
    tpl_completed,
    tpl_declined,
    tpl_deleted,
    tpl_redirected_creator,
    tpl_redirected_new,
    tpl_status_changed,
    tpl_updated,
    tpl_you_are_reviewer,
)


def _notify_external_pair(
    db: Session,
    system: str,
    record,
    name_index: dict,
    tpl_fn,
    *args,
):
    """Fire `tpl_fn` to a gennis/turon record's executor and reviewer.

    `name_index` is the {user_id: display_name} dict already assembled by the
    caller (built from one batched lookup in the source DB).
    """
    executor_id = getattr(record, "executor_id", None)
    reviewer_id = getattr(record, "reviewer_id", None)
    if executor_id:
        _tg_external(db, system, executor_id, name_index.get(executor_id), tpl_fn, *args)
    if reviewer_id and reviewer_id != executor_id:
        _tg_external(db, system, reviewer_id, name_index.get(reviewer_id), tpl_fn, *args)


router = APIRouter(prefix="/mobile/missions", tags=["Mobile - Missions"])


# ── Adapters: source row → normalised MobileMissionOut ───────────────────────

def _from_management(m: Mission, db: Session) -> MobileMissionOut:
    creator = db.query(User).filter(User.id == m.creator_id).first() if m.creator_id else None
    executor = db.query(User).filter(User.id == m.executor_id).first() if m.executor_id else None
    reviewer = db.query(User).filter(User.id == m.reviewer_id).first() if m.reviewer_id else None
    return MobileMissionOut(
        id=m.id,
        source="management",
        management_id=m.id,
        title=m.title,
        description=m.description,
        category=m.category,
        status=m.status,
        creator_id=m.creator_id,
        creator_name=f"{creator.name} {creator.surname}".strip() if creator else None,
        executor_id=m.executor_id,
        executor_name=f"{executor.name} {executor.surname}".strip() if executor else None,
        reviewer_id=m.reviewer_id,
        reviewer_name=f"{reviewer.name} {reviewer.surname}".strip() if reviewer else None,
        location_id=getattr(m, "location_id", None),
        branch_id=getattr(m, "branch_id", None),
        deadline=m.deadline,
        finish_date=getattr(m, "finish_date", None),
        kpi_weight=m.kpi_weight or 10,
        delay_days=m.delay_days or 0,
        final_sc=m.final_sc or 0,
        created_at=m.created_at,
    )


def _from_gennis(m: GennisMission, name_index: dict) -> MobileMissionOut:
    return MobileMissionOut(
        id=m.id,
        source="gennis",
        management_id=m.management_id,
        title=m.title,
        description=m.description,
        category=m.category,
        status=m.status,
        creator_id=m.creator_id,
        creator_name=name_index.get(m.creator_id) or m.creator_name,
        executor_id=m.executor_id,
        executor_name=name_index.get(m.executor_id),
        reviewer_id=m.reviewer_id,
        reviewer_name=name_index.get(m.reviewer_id) or m.reviewer_name,
        location_id=m.location_id,
        branch_id=None,
        deadline=m.deadline_datetime.date() if m.deadline_datetime else None,
        finish_date=m.finish_datetime.date() if m.finish_datetime else None,
        kpi_weight=m.kpi_weight or 10,
        delay_days=m.delay_days or 0,
        final_sc=m.final_sc or 0,
        created_at=m.created_at,
    )


def _from_turon(m: TuronMission, name_index: dict) -> MobileMissionOut:
    return MobileMissionOut(
        id=m.id,
        source="turon",
        management_id=m.management_id,
        title=m.title,
        description=m.description,
        category=m.category,
        status=m.status,
        creator_id=m.creator_id,
        creator_name=name_index.get(m.creator_id) or m.creator_name,
        executor_id=m.executor_id,
        executor_name=name_index.get(m.executor_id),
        reviewer_id=m.reviewer_id,
        reviewer_name=name_index.get(m.reviewer_id) or m.reviewer_name,
        location_id=None,
        branch_id=m.branch_id,
        deadline=m.deadline,
        finish_date=m.finish_date,
        kpi_weight=m.kpi_weight or 10,
        delay_days=m.delay_days or 0,
        final_sc=m.final_sc or 0,
        created_at=datetime.combine(m.created_at, datetime.min.time()) if m.created_at else None,
    )


# ── Per-system list helpers ──────────────────────────────────────────────────

def _list_management(
    identity: MobileIdentity,
    db: Session,
    status: Optional[str],
    role: Optional[str],
) -> List[MobileMissionOut]:
    q = db.query(Mission).filter(Mission.deleted == False)
    if role == "executor":
        q = q.filter(Mission.executor_id == identity.external_id)
    elif role == "creator":
        q = q.filter(Mission.creator_id == identity.external_id)
    elif role == "reviewer":
        q = q.filter(Mission.reviewer_id == identity.external_id)
    else:
        q = q.filter(
            (Mission.executor_id == identity.external_id)
            | (Mission.reviewer_id == identity.external_id)
            | (Mission.creator_id == identity.external_id)
        )
    if status:
        q = q.filter(Mission.status == status)
    rows = q.order_by(Mission.created_at.desc()).all()
    return [_from_management(m, db) for m in rows]


def _list_gennis(
    identity: MobileIdentity,
    gennis_db: Session,
    status: Optional[str],
    role: Optional[str],
) -> List[MobileMissionOut]:
    q = gennis_db.query(GennisMission)
    if role == "executor":
        q = q.filter(GennisMission.executor_id == identity.external_id)
    elif role == "creator":
        q = q.filter(GennisMission.creator_id == identity.external_id)
    elif role == "reviewer":
        q = q.filter(GennisMission.reviewer_id == identity.external_id)
    else:
        q = q.filter(
            (GennisMission.executor_id == identity.external_id)
            | (GennisMission.reviewer_id == identity.external_id)
            | (GennisMission.creator_id == identity.external_id)
        )
    if status:
        q = q.filter(GennisMission.status == status)
    rows = q.order_by(GennisMission.id.desc()).all()

    user_ids = {uid for m in rows for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index: dict = {}
    if user_ids:
        for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all():
            name_index[u.id] = f"{u.name or ''} {u.surname or ''}".strip() or None
    return [_from_gennis(m, name_index) for m in rows]


def _list_turon(
    identity: MobileIdentity,
    turon_db: Session,
    status: Optional[str],
    role: Optional[str],
) -> List[MobileMissionOut]:
    q = turon_db.query(TuronMission)
    if role == "executor":
        q = q.filter(TuronMission.executor_id == identity.external_id)
    elif role == "creator":
        q = q.filter(TuronMission.creator_id == identity.external_id)
    elif role == "reviewer":
        q = q.filter(TuronMission.reviewer_id == identity.external_id)
    else:
        q = q.filter(
            (TuronMission.executor_id == identity.external_id)
            | (TuronMission.reviewer_id == identity.external_id)
            | (TuronMission.creator_id == identity.external_id)
        )
    if status:
        q = q.filter(TuronMission.status == status)
    rows = q.order_by(TuronMission.id.desc()).all()

    user_ids = {uid for m in rows for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index: dict = {}
    if user_ids:
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all():
            name_index[u.id] = f"{u.name or ''} {u.surname or ''}".strip() or None
    return [_from_turon(m, name_index) for m in rows]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=MobileMissionList)
def list_missions(
    status: Optional[str] = Query(None, description="filter by mission status"),
    role: Optional[str] = Query(
        None,
        description="executor | reviewer | creator; defaults to any of the three",
    ),
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    """Missions visible to the caller, served from their home system."""
    if identity.system == "management":
        items = _list_management(identity, db, status, role)
    elif identity.system == "gennis":
        items = _list_gennis(identity, gennis_db, status, role)
    else:
        items = _list_turon(identity, turon_db, status, role)
    return MobileMissionList(total=len(items), results=items)


@router.get("/{mission_id}", response_model=MobileMissionOut)
def get_mission(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        return _from_gennis(m, name_index)

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    return _from_turon(m, name_index)


@router.post("/", response_model=MobileMissionOut, status_code=201)
def create_mission(
    data: MobileMissionCreate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Create a mission in the caller's home system."""
    now = datetime.utcnow()
    creator_display: Optional[str] = identity.name

    if identity.system == "management":
        creator = db.query(User).filter(User.id == identity.external_id).first()
        if not creator:
            raise HTTPException(status_code=404, detail="Creator not found")

        mission = Mission(
            title=data.title,
            description=data.description,
            category=data.category,
            status="pending",
            creator_id=identity.external_id,
            executor_id=data.executor_id,
            reviewer_id=data.reviewer_id,
            deadline=data.deadline,
            kpi_weight=data.kpi_weight,
        )
        db.add(mission)
        db.flush()
        db.refresh(mission)

        entry = _log_history(
            mission, db,
            changed_by_id=identity.external_id,
            note="initial assignment (mobile)",
        )
        db.flush()
        _sync_to_gennis(mission, gennis_db)
        _sync_to_turon(mission, turon_db)
        _sync_history_to_gennis(entry, mission, db, gennis_db)
        _sync_history_to_turon(entry, mission, db, turon_db)
        db.commit()
        db.refresh(mission)

        creator_name = f"{creator.name} {creator.surname or ''}".strip()
        _tg(db, mission.executor_id, tpl_assigned, mission.title, mission.deadline, creator_name)
        _tg(db, mission.reviewer_id, tpl_you_are_reviewer, mission.title, mission.deadline, creator_name)
        _tg_mission_externals(
            db, mission, gennis_db, turon_db,
            tpl_assigned, tpl_you_are_reviewer,
            mission.title, mission.deadline, creator_name,
        )

        return _from_management(mission, db)

    if identity.system == "gennis":
        record = GennisMission(
            title=data.title,
            description=data.description,
            category=data.category,
            status="pending",
            creator_id=identity.external_id,
            creator_name=creator_display,
            executor_id=data.executor_id,
            reviewer_id=data.reviewer_id,
            start_datetime=now,
            deadline_datetime=datetime.combine(data.deadline, datetime.min.time()) if data.deadline else None,
            kpi_weight=data.kpi_weight,
            created_at=now,
        )
        gennis_db.add(record)
        gennis_db.commit()
        gennis_db.refresh(record)
        user_ids = {uid for uid in (record.creator_id, record.executor_id, record.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        creator_name = name_index.get(identity.external_id) or creator_display or "User"
        if record.executor_id:
            _tg_external(
                db, "gennis", record.executor_id,
                name_index.get(record.executor_id),
                tpl_assigned, record.title, data.deadline, creator_name,
            )
        if record.reviewer_id:
            _tg_external(
                db, "gennis", record.reviewer_id,
                name_index.get(record.reviewer_id),
                tpl_you_are_reviewer, record.title, data.deadline, creator_name,
            )
        return _from_gennis(record, name_index)

    # turon
    record = TuronMission(
        title=data.title,
        description=data.description,
        category=data.category,
        status="pending",
        creator_id=identity.external_id,
        creator_name=creator_display,
        executor_id=data.executor_id,
        reviewer_id=data.reviewer_id,
        start_date=now.date(),
        deadline=data.deadline,
        kpi_weight=data.kpi_weight,
        created_at=now.date(),
        updated_at=now.date(),
    )
    turon_db.add(record)
    turon_db.commit()
    turon_db.refresh(record)
    user_ids = {uid for uid in (record.creator_id, record.executor_id, record.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    creator_name = name_index.get(identity.external_id) or creator_display or "User"
    if record.executor_id:
        _tg_external(
            db, "turon", record.executor_id,
            name_index.get(record.executor_id),
            tpl_assigned, record.title, data.deadline, creator_name,
        )
    if record.reviewer_id:
        _tg_external(
            db, "turon", record.reviewer_id,
            name_index.get(record.reviewer_id),
            tpl_you_are_reviewer, record.title, data.deadline, creator_name,
        )
    return _from_turon(record, name_index)


@router.patch("/{mission_id}/status", response_model=MobileMissionOut)
def change_status(
    mission_id: int,
    data: MobileStatusUpdate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Move a mission to a new status in its source system."""
    new_status = data.status.value
    finish_date = data.finish_date or (date.today() if new_status == "completed" else None)

    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")

        previous_status = m.status
        m.status = new_status
        if new_status == "completed" and m.finish_date is None:
            m.finish_date = finish_date or date.today()
            m.calculate_delay_days()
            m.final_sc = m.final_score()
        if new_status == "approved" and m.approved_date is None:
            m.approved_date = date.today()
        if new_status == "declined":
            m.finish_date = None
            m.approved_date = None
            m.delay_days = 0
        db.commit()
        db.refresh(m)

        if previous_status != m.status:
            entry = _log_history(
                m, db,
                changed_by_id=identity.external_id,
                note=f"status: {previous_status} -> {m.status} (mobile)",
                status=m.status,
            )
            db.commit()
            db.refresh(entry)
            _sync_history_to_gennis(entry, m, db, gennis_db)
            _sync_history_to_turon(entry, m, db, turon_db)

        _sync_to_gennis(m, gennis_db)
        _sync_to_turon(m, turon_db)

        _tg(db, m.executor_id, tpl_status_changed, m.title, m.status)
        _tg(db, m.reviewer_id, tpl_status_changed, m.title, m.status)
        _tg_mission_externals(
            db, m, gennis_db, turon_db,
            tpl_status_changed, tpl_status_changed,
            m.title, m.status,
        )

        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        m.status = new_status
        if new_status == "completed" and m.finish_datetime is None and finish_date:
            m.finish_datetime = datetime.combine(finish_date, datetime.min.time())
        gennis_db.commit()
        gennis_db.refresh(m)
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        _notify_external_pair(db, "gennis", m, name_index, tpl_status_changed, m.title, m.status)
        return _from_gennis(m, name_index)

    # turon
    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    m.status = new_status
    if new_status == "completed" and m.finish_date is None and finish_date:
        m.finish_date = finish_date
    turon_db.commit()
    turon_db.refresh(m)
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    _notify_external_pair(db, "turon", m, name_index, tpl_status_changed, m.title, m.status)
    return _from_turon(m, name_index)


# ── PATCH /mobile/missions/{id} ──────────────────────────────────────────────

@router.patch("/{mission_id}", response_model=MobileMissionOut)
def update_mission(
    mission_id: int,
    data: MobileMissionUpdate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Patch a mission's mutable fields in the caller's home system."""
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    changer_name = identity.name or "User"

    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        old_executor, old_reviewer = m.executor_id, m.reviewer_id
        for field, value in payload.items():
            setattr(m, field, value)
        db.commit()
        db.refresh(m)

        if m.executor_id != old_executor or m.reviewer_id != old_reviewer:
            entry = _log_history(
                m, db,
                changed_by_id=identity.external_id,
                note="reassigned (mobile)",
            )
            db.commit()
            db.refresh(entry)
            _sync_history_to_gennis(entry, m, db, gennis_db)
            _sync_history_to_turon(entry, m, db, turon_db)

        _sync_to_gennis(m, gennis_db)
        _sync_to_turon(m, turon_db)

        if m.executor_id != old_executor and m.executor_id:
            _tg(db, m.executor_id, tpl_assigned, m.title, m.deadline, changer_name)
        if m.reviewer_id != old_reviewer and m.reviewer_id:
            _tg(db, m.reviewer_id, tpl_you_are_reviewer, m.title, m.deadline, changer_name)
        if m.executor_id == old_executor and m.reviewer_id == old_reviewer:
            _tg(db, m.executor_id, tpl_updated, m.title, changer_name)
            _tg(db, m.reviewer_id, tpl_updated, m.title, changer_name)
            _tg_mission_externals(
                db, m, gennis_db, turon_db,
                tpl_updated, tpl_updated,
                m.title, changer_name,
            )

        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        for field, value in payload.items():
            if field == "deadline":
                m.deadline_datetime = (
                    datetime.combine(value, datetime.min.time()) if value else None
                )
            else:
                setattr(m, field, value)
        gennis_db.commit()
        gennis_db.refresh(m)
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        _notify_external_pair(db, "gennis", m, name_index, tpl_updated, m.title, changer_name)
        return _from_gennis(m, name_index)

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    for field, value in payload.items():
        setattr(m, field, value)
    turon_db.commit()
    turon_db.refresh(m)
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    _notify_external_pair(db, "turon", m, name_index, tpl_updated, m.title, changer_name)
    return _from_turon(m, name_index)


# ── DELETE /mobile/missions/{id} ─────────────────────────────────────────────

@router.delete("/{mission_id}", status_code=204)
def delete_mission(
    mission_id: int,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Soft-delete a mission in the caller's home system."""
    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        _sync_delete(m, gennis_db, turon_db)
        m.deleted = True
        db.commit()
        _tg(db, m.executor_id, tpl_deleted, m.title)
        _tg(db, m.reviewer_id, tpl_deleted, m.title)
        _tg_mission_externals(
            db, m, gennis_db, turon_db,
            tpl_deleted, tpl_deleted,
            m.title,
        )
        return

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        title = m.title
        executor_id, reviewer_id = m.executor_id, m.reviewer_id
        user_ids = {uid for uid in (executor_id, reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        gennis_db.delete(m)
        gennis_db.commit()
        if executor_id:
            _tg_external(db, "gennis", executor_id, name_index.get(executor_id), tpl_deleted, title)
        if reviewer_id and reviewer_id != executor_id:
            _tg_external(db, "gennis", reviewer_id, name_index.get(reviewer_id), tpl_deleted, title)
        return

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    title = m.title
    executor_id, reviewer_id = m.executor_id, m.reviewer_id
    user_ids = {uid for uid in (executor_id, reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    turon_db.delete(m)
    turon_db.commit()
    if executor_id:
        _tg_external(db, "turon", executor_id, name_index.get(executor_id), tpl_deleted, title)
    if reviewer_id and reviewer_id != executor_id:
        _tg_external(db, "turon", reviewer_id, name_index.get(reviewer_id), tpl_deleted, title)


# ── POST /mobile/missions/{id}/complete ──────────────────────────────────────

@router.post("/{mission_id}/complete", response_model=MobileMissionOut)
def complete_mission(
    mission_id: int,
    data: MobileMissionComplete,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Mark a mission completed with the given finish date."""
    finish_date = data.finish_date

    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        previous_status = m.status
        m.finish_date = finish_date
        m.status = "completed"
        m.calculate_delay_days()
        m.final_sc = m.final_score()
        db.commit()
        db.refresh(m)

        entry = _log_history(
            m, db,
            changed_by_id=identity.external_id,
            note=f"status: {previous_status} -> completed (mobile, finish={finish_date})",
            status="completed",
        )
        db.commit()
        db.refresh(entry)
        _sync_history_to_gennis(entry, m, db, gennis_db)
        _sync_history_to_turon(entry, m, db, turon_db)
        _sync_to_gennis(m, gennis_db)
        _sync_to_turon(m, turon_db)

        executor_name = identity.name or "User"
        _tg(db, m.reviewer_id, tpl_completed, m.title, executor_name, m.finish_date)
        _tg(db, m.creator_id, tpl_completed, m.title, executor_name, m.finish_date)
        _tg_mission_externals(
            db, m, gennis_db, turon_db,
            None, tpl_completed,
            m.title, executor_name, m.finish_date,
        )
        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        m.status = "completed"
        m.finish_datetime = datetime.combine(finish_date, datetime.min.time())
        gennis_db.commit()
        gennis_db.refresh(m)
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        executor_name = name_index.get(m.executor_id) or identity.name or "User"
        if m.reviewer_id:
            _tg_external(
                db, "gennis", m.reviewer_id, name_index.get(m.reviewer_id),
                tpl_completed, m.title, executor_name, finish_date,
            )
        return _from_gennis(m, name_index)

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    m.status = "completed"
    m.finish_date = finish_date
    turon_db.commit()
    turon_db.refresh(m)
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    executor_name = name_index.get(m.executor_id) or identity.name or "User"
    if m.reviewer_id:
        _tg_external(
            db, "turon", m.reviewer_id, name_index.get(m.reviewer_id),
            tpl_completed, m.title, executor_name, finish_date,
        )
    return _from_turon(m, name_index)


# ── PATCH /mobile/missions/{id}/approve ──────────────────────────────────────

@router.patch("/{mission_id}/approve", response_model=MobileMissionOut)
def approve_mission(
    mission_id: int,
    data: MobileMissionApprove,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Approve or decline a mission.

    Management missions track `approval_status` separately from `status`; the
    Gennis/Turon source schemas don't model this, so on those backends we
    fold an approval into the `status` field (approved → "approved",
    declined → "declined").
    """
    approval = data.approval_status.value
    approver_name = identity.name or "User"

    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        m.approval_status = approval
        m.approved_by_id = identity.external_id
        if approval == "approved":
            if m.approved_date is None:
                m.approved_date = date.today()
        else:
            m.finish_date = None
            m.approved_date = None
            m.delay_days = 0
        db.commit()
        db.refresh(m)

        entry = _log_history(
            m, db,
            changed_by_id=identity.external_id,
            note=f"approval: {approval} (mobile)",
            status=m.status,
        )
        db.commit()
        db.refresh(entry)
        _sync_history_to_gennis(entry, m, db, gennis_db)
        _sync_history_to_turon(entry, m, db, turon_db)

        if approval == "approved":
            _tg(db, m.executor_id, tpl_approved, m.title, approver_name)
            _tg(db, m.creator_id, tpl_approved, m.title, approver_name)
            _tg_mission_externals(
                db, m, gennis_db, turon_db,
                tpl_approved, None,
                m.title, approver_name,
            )
        else:
            _tg(db, m.executor_id, tpl_declined, m.title, approver_name)
            _tg_mission_externals(
                db, m, gennis_db, turon_db,
                tpl_declined, None,
                m.title, approver_name,
            )
        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        m.status = approval
        gennis_db.commit()
        gennis_db.refresh(m)
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        tpl = tpl_approved if approval == "approved" else tpl_declined
        if m.executor_id:
            _tg_external(
                db, "gennis", m.executor_id, name_index.get(m.executor_id),
                tpl, m.title, approver_name,
            )
        return _from_gennis(m, name_index)

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    m.status = approval
    turon_db.commit()
    turon_db.refresh(m)
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    tpl = tpl_approved if approval == "approved" else tpl_declined
    if m.executor_id:
        _tg_external(
            db, "turon", m.executor_id, name_index.get(m.executor_id),
            tpl, m.title, approver_name,
        )
    return _from_turon(m, name_index)


# ── PATCH /mobile/missions/{id}/redirect ─────────────────────────────────────

@router.patch("/{mission_id}/redirect", response_model=MobileMissionOut)
def redirect_mission(
    mission_id: int,
    data: MobileMissionRedirect,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Reassign a mission to a new executor inside the caller's home system."""
    redirected_by_name = identity.name or "User"
    new_executor_id = data.new_executor_id

    if identity.system == "management":
        m = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        new_executor = db.query(User).filter(User.id == new_executor_id).first()
        if not new_executor:
            raise HTTPException(status_code=404, detail="New executor not found")
        old_executor_id = m.executor_id
        old_executor_name = (
            db.query(User).filter(User.id == old_executor_id).first()
            if old_executor_id else None
        )
        old_executor_name = (
            f"{old_executor_name.name} {old_executor_name.surname or ''}".strip()
            if old_executor_name else ""
        )
        new_executor_name = f"{new_executor.name} {new_executor.surname or ''}".strip()
        m.executor_id = new_executor_id
        db.commit()
        db.refresh(m)

        entry = _log_history(
            m, db,
            changed_by_id=identity.external_id,
            note=f"redirected (mobile): {old_executor_name} -> {new_executor_name}",
        )
        db.commit()
        db.refresh(entry)
        _sync_history_to_gennis(entry, m, db, gennis_db)
        _sync_history_to_turon(entry, m, db, turon_db)
        _sync_to_gennis(m, gennis_db)
        _sync_to_turon(m, turon_db)

        _tg(db, new_executor_id, tpl_redirected_new, m.title, redirected_by_name)
        _tg(db, m.creator_id, tpl_redirected_creator, m.title, old_executor_name, new_executor_name)
        _tg(db, m.reviewer_id, tpl_redirected_creator, m.title, old_executor_name, new_executor_name)
        _tg_mission_externals(
            db, m, gennis_db, turon_db,
            tpl_redirected_creator, tpl_redirected_creator,
            m.title, old_executor_name, new_executor_name,
        )
        return _from_management(m, db)

    if identity.system == "gennis":
        m = gennis_db.query(GennisMission).filter(GennisMission.id == mission_id).first()
        if not m:
            raise HTTPException(status_code=404, detail="Mission not found")
        old_executor_id = m.executor_id
        m.executor_id = new_executor_id
        gennis_db.commit()
        gennis_db.refresh(m)
        user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id, old_executor_id) if uid}
        name_index = {
            u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
            for u in gennis_db.query(GennisUsers).filter(GennisUsers.id.in_(user_ids)).all()
        }
        old_name = name_index.get(old_executor_id) or ""
        new_name = name_index.get(new_executor_id) or ""
        _tg_external(
            db, "gennis", new_executor_id, new_name,
            tpl_redirected_new, m.title, redirected_by_name,
        )
        if m.reviewer_id:
            _tg_external(
                db, "gennis", m.reviewer_id, name_index.get(m.reviewer_id),
                tpl_redirected_creator, m.title, old_name, new_name,
            )
        return _from_gennis(m, name_index)

    m = turon_db.query(TuronMission).filter(TuronMission.id == mission_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    old_executor_id = m.executor_id
    m.executor_id = new_executor_id
    turon_db.commit()
    turon_db.refresh(m)
    user_ids = {uid for uid in (m.creator_id, m.executor_id, m.reviewer_id, old_executor_id) if uid}
    name_index = {
        u.id: f"{u.name or ''} {u.surname or ''}".strip() or None
        for u in turon_db.query(TuronUser).filter(TuronUser.id.in_(user_ids)).all()
    }
    old_name = name_index.get(old_executor_id) or ""
    new_name = name_index.get(new_executor_id) or ""
    _tg_external(
        db, "turon", new_executor_id, new_name,
        tpl_redirected_new, m.title, redirected_by_name,
    )
    if m.reviewer_id:
        _tg_external(
            db, "turon", m.reviewer_id, name_index.get(m.reviewer_id),
            tpl_redirected_creator, m.title, old_name, new_name,
        )
    return _from_turon(m, name_index)
