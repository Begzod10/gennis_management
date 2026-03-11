from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ...database import get_db
from ...models import Mission, MissionSubtask
from ...schemas import MissionSubtaskCreate, MissionSubtaskUpdate, MissionSubtaskOut

router = APIRouter(prefix="/missions/{mission_id}/subtasks", tags=["Mission Subtasks"])


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/", response_model=MissionSubtaskOut, status_code=201)
def create_subtask(mission_id: int, data: MissionSubtaskCreate, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    subtask = MissionSubtask(**data.model_dump(), mission_id=mission_id)
    db.add(subtask)
    db.commit()
    db.refresh(subtask)
    return subtask


@router.get("/", response_model=List[MissionSubtaskOut])
def list_subtasks(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionSubtask).filter(
        MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).order_by(MissionSubtask.order).all()


@router.patch("/{subtask_id}", response_model=MissionSubtaskOut)
def update_subtask(mission_id: int, subtask_id: int, data: MissionSubtaskUpdate, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    subtask = db.query(MissionSubtask).filter(
        MissionSubtask.id == subtask_id, MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(subtask, field, value)
    db.commit()
    db.refresh(subtask)
    return subtask


@router.delete("/{subtask_id}", status_code=204)
def delete_subtask(mission_id: int, subtask_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    subtask = db.query(MissionSubtask).filter(
        MissionSubtask.id == subtask_id, MissionSubtask.mission_id == mission_id, MissionSubtask.deleted == False
    ).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    subtask.deleted = True
    db.commit()
