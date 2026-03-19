import os
import uuid
import aiofiles
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from ...database import get_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, MissionComment, User
from ...schemas import MissionCommentOut
from ...external_models.gennis import GennisMission, GennisMissionComment
from ...external_models.turon import TuronMission, TuronMissionComment

router = APIRouter(prefix="/missions/{mission_id}/comments", tags=["Mission Comments"])

UPLOAD_DIR = "uploads/mission_comments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _sync_comment_gennis(mission: Mission, comment: MissionComment, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_mission = gennis_db.query(GennisMission).filter(GennisMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = gennis_db.query(GennisMissionComment).filter(GennisMissionComment.management_id == comment.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    if ext:
        ext.text = comment.text
        ext.attachment_path = comment.attachment
        ext.creator_name = creator_name
    else:
        ext = GennisMissionComment(
            management_id=comment.id,
            mission_id=ext_mission.id,
            user_id=None,
            text=comment.text,
            attachment_path=comment.attachment,
            created_at=comment.created_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_comment_turon(mission: Mission, comment: MissionComment, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_mission = turon_db.query(TuronMission).filter(TuronMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = turon_db.query(TuronMissionComment).filter(TuronMissionComment.management_id == comment.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    if ext:
        ext.text = comment.text
        ext.attachment = comment.attachment
        ext.creator_name = creator_name
    else:
        ext = TuronMissionComment(
            management_id=comment.id,
            mission_id=ext_mission.id,
            user_id=None,
            text=comment.text,
            attachment=comment.attachment,
            created_at=comment.created_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionCommentOut, status_code=201)
async def create_comment(
    mission_id: int,
    user_id: int = Form(...),
    text: str = Form(...),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    attachment_path = None
    if attachment:
        ext = os.path.splitext(attachment.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        attachment_path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(attachment_path, "wb") as f:
            await f.write(await attachment.read())

    comment = MissionComment(
        mission_id=mission_id,
        user_id=user_id,
        text=text,
        attachment=attachment_path,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    user = db.query(User).filter(User.id == user_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_comment_gennis(mission, comment, gennis_db, creator_name=creator_name)
    _sync_comment_turon(mission, comment, turon_db, creator_name=creator_name)
    return comment


@router.get("/", response_model=List[MissionCommentOut])
def list_comments(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionComment).options(
        joinedload(MissionComment.user)
    ).filter(
        MissionComment.mission_id == mission_id, MissionComment.deleted == False
    ).order_by(MissionComment.created_at).all()


@router.patch("/{comment_id}", response_model=MissionCommentOut)
async def update_comment(
    mission_id: int,
    comment_id: int,
    text: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    comment = db.query(MissionComment).filter(
        MissionComment.id == comment_id, MissionComment.mission_id == mission_id, MissionComment.deleted == False
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if text is not None:
        comment.text = text
    if attachment:
        ext = os.path.splitext(attachment.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        attachment_path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(attachment_path, "wb") as f:
            await f.write(await attachment.read())
        comment.attachment = attachment_path
    db.commit()
    db.refresh(comment)
    user = db.query(User).filter(User.id == comment.user_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_comment_gennis(mission, comment, gennis_db, creator_name=creator_name)
    _sync_comment_turon(mission, comment, turon_db, creator_name=creator_name)
    return comment


@router.delete("/{comment_id}", status_code=204)
def delete_comment(
    mission_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    comment = db.query(MissionComment).filter(
        MissionComment.id == comment_id, MissionComment.mission_id == mission_id, MissionComment.deleted == False
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    _sync_comment_gennis(mission, comment, gennis_db, deleted=True)
    _sync_comment_turon(mission, comment, turon_db, deleted=True)
    comment.deleted = True
    db.commit()
