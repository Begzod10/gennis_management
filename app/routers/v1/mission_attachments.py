import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db
from ...models import Mission, MissionAttachment
from ...schemas import MissionAttachmentOut

router = APIRouter(prefix="/missions/{mission_id}/attachments", tags=["Mission Attachments"])

UPLOAD_DIR = "uploads/mission_attachments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/", response_model=MissionAttachmentOut, status_code=201)
async def upload_attachment(
    mission_id: int,
    file: UploadFile = File(...),
    note: str = Form(None),
    db: Session = Depends(get_db),
):
    _get_mission(db, mission_id)
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(path, "wb") as f:
        await f.write(await file.read())
    attachment = MissionAttachment(mission_id=mission_id, file=path, note=note)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/", response_model=List[MissionAttachmentOut])
def list_attachments(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionAttachment).filter(
        MissionAttachment.mission_id == mission_id, MissionAttachment.deleted == False
    ).all()


@router.patch("/{attachment_id}", response_model=MissionAttachmentOut)
async def update_attachment(
    mission_id: int,
    attachment_id: int,
    file: Optional[UploadFile] = File(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _get_mission(db, mission_id)
    attachment = db.query(MissionAttachment).filter(
        MissionAttachment.id == attachment_id, MissionAttachment.mission_id == mission_id, MissionAttachment.deleted == False
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if file:
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(path, "wb") as f:
            await f.write(await file.read())
        attachment.file = path
    if note is not None:
        attachment.note = note
    db.commit()
    db.refresh(attachment)
    return attachment


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(mission_id: int, attachment_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    attachment = db.query(MissionAttachment).filter(
        MissionAttachment.id == attachment_id, MissionAttachment.mission_id == mission_id, MissionAttachment.deleted == False
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    attachment.deleted = True
    db.commit()
