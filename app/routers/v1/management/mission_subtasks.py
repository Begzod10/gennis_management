from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional
from app.database import get_db, get_gennis_write_db, get_turon_write_db
from app.models import (
    Mission, MissionSubtask, MissionSubtaskComment,
    MissionSubtaskAttachment, MissionSubtaskProof, User,
)
from app.schemas import MissionSubtaskCreate, MissionSubtaskUpdate, MissionSubtaskOut
from app.external_models.gennis import GennisMission, GennisMissionSubtask
from app.external_models.turon import TuronMission, TuronMissionSubtask
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_subtask_added, tpl_subtask_assigned

_DONE_STATUSES = ("completed", "approved")


def _enrich(subtask: MissionSubtask, counts: dict[int, dict[str, int]]) -> MissionSubtaskOut:
    out = MissionSubtaskOut.model_validate(subtask)
    c = counts.get(subtask.id, {})
    out.comments_count = c.get("comments", 0)
    out.attachments_count = c.get("attachments", 0)
    out.proofs_count = c.get("proofs", 0)
    today = date.today()
    if subtask.deadline:
        out.days_left = (subtask.deadline - today).days
        is_done = subtask.is_done or (subtask.status in _DONE_STATUSES)
        out.is_overdue = (subtask.deadline < today) and not is_done
    return out


def _collect_counts(db: Session, subtask_ids: List[int]) -> dict[int, dict[str, int]]:
    if not subtask_ids:
        return {}
    counts: dict[int, dict[str, int]] = {sid: {"comments": 0, "attachments": 0, "proofs": 0} for sid in subtask_ids}

    comment_rows = (
        db.query(MissionSubtaskComment.subtask_id, func.count(MissionSubtaskComment.id))
        .filter(MissionSubtaskComment.subtask_id.in_(subtask_ids), MissionSubtaskComment.deleted == False)
        .group_by(MissionSubtaskComment.subtask_id).all()
    )
    for sid, n in comment_rows:
        counts[sid]["comments"] = n

    attachment_rows = (
        db.query(MissionSubtaskAttachment.subtask_id, func.count(MissionSubtaskAttachment.id))
        .filter(MissionSubtaskAttachment.subtask_id.in_(subtask_ids), MissionSubtaskAttachment.deleted == False)
        .group_by(MissionSubtaskAttachment.subtask_id).all()
    )
    for sid, n in attachment_rows:
        counts[sid]["attachments"] = n

    proof_rows = (
        db.query(MissionSubtaskProof.subtask_id, func.count(MissionSubtaskProof.id))
        .filter(MissionSubtaskProof.subtask_id.in_(subtask_ids), MissionSubtaskProof.deleted == False)
        .group_by(MissionSubtaskProof.subtask_id).all()
    )
    for sid, n in proof_rows:
        counts[sid]["proofs"] = n

    return counts

router = APIRouter(prefix="/missions/{mission_id}/subtasks", tags=["Mission Subtasks"])


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _sync_subtask_gennis(mission: Mission, subtask: MissionSubtask, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_mission = gennis_db.query(GennisMission).filter(GennisMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = gennis_db.query(GennisMissionSubtask).filter(GennisMissionSubtask.management_id == subtask.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    if ext:
        ext.title = subtask.title
        ext.is_done = subtask.is_done
        ext.order = subtask.order
    else:
        ext = GennisMissionSubtask(
            management_id=subtask.id,
            mission_id=ext_mission.id,
            title=subtask.title,
            is_done=subtask.is_done,
            order=subtask.order,
            created_at=subtask.created_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_subtask_turon(mission: Mission, subtask: MissionSubtask, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_mission = turon_db.query(TuronMission).filter(TuronMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = turon_db.query(TuronMissionSubtask).filter(TuronMissionSubtask.management_id == subtask.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    if ext:
        ext.title = subtask.title
        ext.is_done = subtask.is_done
        ext.order = subtask.order
    else:
        ext = TuronMissionSubtask(
            management_id=subtask.id,
            mission_id=ext_mission.id,
            title=subtask.title,
            is_done=subtask.is_done,
            order=subtask.order,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionSubtaskOut, status_code=201)
def create_subtask(
    mission_id: int,
    data: MissionSubtaskCreate,
    creator_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    payload = data.model_dump()
    payload.setdefault("creator_id", creator_id)
    subtask = MissionSubtask(**payload, mission_id=mission_id)
    db.add(subtask)
    db.commit()
    db.refresh(subtask)
    user = db.query(User).filter(User.id == creator_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_subtask_gennis(mission, subtask, gennis_db, creator_name=creator_name)
    _sync_subtask_turon(mission, subtask, turon_db, creator_name=creator_name)

    for uid in {mission.executor_id, mission.reviewer_id, mission.creator_id} - {creator_id}:
        if uid:
            u = db.query(User).filter(User.id == uid).first()
            if u and u.telegram_id:
                recipient_name = f"{u.name} {u.surname}".strip() if u.surname else u.name
                send_telegram_notification.delay(
                    u.telegram_id,
                    tpl_subtask_added(recipient_name, mission.title, subtask.title, creator_name or "—"),
                )

    # Notify subtask executor if assigned and different from creator
    if subtask.executor_id and subtask.executor_id != creator_id:
        executor = db.query(User).filter(User.id == subtask.executor_id).first()
        if executor and executor.telegram_id:
            recipient_name = f"{executor.name} {executor.surname}".strip() if executor.surname else executor.name
            send_telegram_notification.delay(
                executor.telegram_id,
                tpl_subtask_assigned(recipient_name, mission.title, subtask.title, creator_name or "—"),
            )

    return _enrich(subtask, _collect_counts(db, [subtask.id]))


@router.get("/", response_model=List[MissionSubtaskOut])
def list_subtasks(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    subtasks = (
        db.query(MissionSubtask)
        .options(
            selectinload(MissionSubtask.creator),
            selectinload(MissionSubtask.executor),
        )
        .filter(MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False)
        .order_by(MissionSubtask.order)
        .all()
    )
    counts = _collect_counts(db, [s.id for s in subtasks])
    return [_enrich(s, counts) for s in subtasks]


@router.get("/{subtask_id}", response_model=MissionSubtaskOut)
def get_subtask(mission_id: int, subtask_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    subtask = (
        db.query(MissionSubtask)
        .options(
            selectinload(MissionSubtask.creator),
            selectinload(MissionSubtask.executor),
        )
        .filter(
            MissionSubtask.id == subtask_id,
            MissionSubtask.mission_id == mission_id,
            MissionSubtask.deleted == False,
        )
        .first()
    )
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    counts = _collect_counts(db, [subtask.id])
    return _enrich(subtask, counts)


@router.patch("/{subtask_id}", response_model=MissionSubtaskOut)
def update_subtask(
    mission_id: int,
    subtask_id: int,
    data: MissionSubtaskUpdate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    subtask = db.query(MissionSubtask).filter(
        MissionSubtask.id == subtask_id, MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    old_executor_id = subtask.executor_id
    was_done = subtask.is_done or (subtask.status in _DONE_STATUSES)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(subtask, field, value)
    # Auto-fill finish_date the first time a subtask flips to done.
    now_done = subtask.is_done or (subtask.status in _DONE_STATUSES)
    if now_done and not was_done and subtask.finish_date is None:
        subtask.finish_date = date.today()
    db.commit()
    db.refresh(subtask)
    _sync_subtask_gennis(mission, subtask, gennis_db)
    _sync_subtask_turon(mission, subtask, turon_db)

    # Notify newly assigned executor
    new_executor_id = subtask.executor_id
    if new_executor_id and new_executor_id != old_executor_id:
        executor = db.query(User).filter(User.id == new_executor_id).first()
        if executor and executor.telegram_id:
            recipient_name = f"{executor.name} {executor.surname}".strip() if executor.surname else executor.name
            send_telegram_notification.delay(
                executor.telegram_id,
                tpl_subtask_assigned(recipient_name, mission.title, subtask.title, "—"),
            )

    return _enrich(subtask, _collect_counts(db, [subtask.id]))


@router.delete("/{subtask_id}", status_code=204)
def delete_subtask(
    mission_id: int,
    subtask_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    subtask = db.query(MissionSubtask).filter(
        MissionSubtask.id == subtask_id, MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    _sync_subtask_gennis(mission, subtask, gennis_db, deleted=True)
    _sync_subtask_turon(mission, subtask, turon_db, deleted=True)
    subtask.deleted = True
    db.commit()
