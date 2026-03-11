import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db
from ...models import Mission, MissionComment
from ...schemas import MissionCommentOut

router = APIRouter(prefix="/missions/{mission_id}/comments", tags=["Mission Comments"])

UPLOAD_DIR = "uploads/mission_comments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/", response_model=MissionCommentOut, status_code=201)
async def create_comment(
    mission_id: int,
    user_id: int = Form(...),
    text: str = Form(...),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _get_mission(db, mission_id)
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
    return comment


@router.get("/", response_model=List[MissionCommentOut])
def list_comments(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionComment).filter(
        MissionComment.mission_id == mission_id, MissionComment.deleted == False
    ).order_by(MissionComment.created_at).all()


@router.patch("/{comment_id}", response_model=MissionCommentOut)
async def update_comment(
    mission_id: int,
    comment_id: int,
    text: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    _get_mission(db, mission_id)
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
    return comment


@router.delete("/{comment_id}", status_code=204)
def delete_comment(mission_id: int, comment_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    comment = db.query(MissionComment).filter(
        MissionComment.id == comment_id, MissionComment.mission_id == mission_id, MissionComment.deleted == False
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.deleted = True
    db.commit()
