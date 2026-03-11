from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ...database import get_db
from ...models import Mission, Tag, User
from ...schemas import MissionCreate, MissionUpdate, MissionOut, MissionStatusEnum

router = APIRouter(prefix="/missions", tags=["Missions"])


def _get_or_404(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/", response_model=MissionOut, status_code=201)
def create_mission(data: MissionCreate, creator_id: int, db: Session = Depends(get_db)):
    if not db.query(User).filter(User.id == creator_id).first():
        raise HTTPException(status_code=404, detail="Creator not found")
    if not db.query(User).filter(User.id == data.executor_id).first():
        raise HTTPException(status_code=404, detail="Executor not found")

    payload = data.model_dump(exclude={"tag_ids"})
    mission = Mission(**payload, creator_id=creator_id)

    if data.tag_ids:
        tags = db.query(Tag).filter(Tag.id.in_(data.tag_ids)).all()
        mission.tags = tags

    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission


@router.get("/", response_model=List[MissionOut])
def list_missions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    creator_id: Optional[int] = Query(None),
    executor_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
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
    return q.order_by(Mission.created_at.desc()).all()


@router.get("/{mission_id}", response_model=MissionOut)
def get_mission(mission_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, mission_id)


@router.patch("/{mission_id}", response_model=MissionOut)
def update_mission(mission_id: int, data: MissionUpdate, db: Session = Depends(get_db)):
    mission = _get_or_404(db, mission_id)

    tag_ids = data.tag_ids
    payload = data.model_dump(exclude_none=True, exclude={"tag_ids"})
    for field, value in payload.items():
        setattr(mission, field, value)

    if tag_ids is not None:
        tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        mission.tags = tags

    # recalculate delay if finish_date or deadline changed
    if "finish_date" in payload or "deadline" in payload:
        mission.calculate_delay_days()
        mission.final_sc = mission.final_score()

    db.commit()
    db.refresh(mission)
    return mission


@router.delete("/{mission_id}", status_code=204)
def delete_mission(mission_id: int, db: Session = Depends(get_db)):
    mission = _get_or_404(db, mission_id)
    mission.deleted = True
    db.commit()


@router.patch("/{mission_id}/status", response_model=MissionOut)
def change_status(mission_id: int, status: MissionStatusEnum, db: Session = Depends(get_db)):
    mission = _get_or_404(db, mission_id)
    mission.status = status.value
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
def complete_mission(mission_id: int, finish_date: str, db: Session = Depends(get_db)):
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
    return mission
