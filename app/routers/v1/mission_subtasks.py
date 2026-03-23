from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, MissionSubtask, User
from ...schemas import MissionSubtaskCreate, MissionSubtaskUpdate, MissionSubtaskOut
from ...external_models.gennis import GennisMission, GennisMissionSubtask
from ...external_models.turon import TuronMission, TuronMissionSubtask

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
    subtask = MissionSubtask(**data.model_dump(), mission_id=mission_id)
    db.add(subtask)
    db.commit()
    db.refresh(subtask)
    user = db.query(User).filter(User.id == creator_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_subtask_gennis(mission, subtask, gennis_db, creator_name=creator_name)
    _sync_subtask_turon(mission, subtask, turon_db, creator_name=creator_name)
    return subtask


@router.get("/", response_model=List[MissionSubtaskOut])
def list_subtasks(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionSubtask).filter(
        MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).order_by(MissionSubtask.order).all()


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
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(subtask, field, value)
    db.commit()
    db.refresh(subtask)
    _sync_subtask_gennis(mission, subtask, gennis_db)
    _sync_subtask_turon(mission, subtask, turon_db)
    return subtask


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
