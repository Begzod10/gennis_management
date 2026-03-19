import os
import uuid
import aiofiles
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, MissionAttachment, User
from ...schemas import MissionAttachmentOut
from ...external_models.gennis import GennisMission, GennisMissionAttachment
from ...external_models.turon import TuronMission, TuronMissionAttachment

router = APIRouter(prefix="/missions/{mission_id}/attachments", tags=["Mission Attachments"])

UPLOAD_DIR = "uploads/mission_attachments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _sync_attachment_gennis(mission: Mission, attachment: MissionAttachment, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_mission = gennis_db.query(GennisMission).filter(GennisMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = gennis_db.query(GennisMissionAttachment).filter(GennisMissionAttachment.management_id == attachment.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    if ext:
        ext.file_path = attachment.file
        ext.note = attachment.note
    else:
        ext = GennisMissionAttachment(
            management_id=attachment.id,
            mission_id=ext_mission.id,
            file_path=attachment.file,
            note=attachment.note,
            uploaded_at=attachment.uploaded_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_attachment_turon(mission: Mission, attachment: MissionAttachment, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_mission = turon_db.query(TuronMission).filter(TuronMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = turon_db.query(TuronMissionAttachment).filter(TuronMissionAttachment.management_id == attachment.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    if ext:
        ext.file = attachment.file
        ext.note = attachment.note
    else:
        ext = TuronMissionAttachment(
            management_id=attachment.id,
            mission_id=ext_mission.id,
            file=attachment.file,
            note=attachment.note,
            uploaded_at=attachment.uploaded_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionAttachmentOut, status_code=201)
async def upload_attachment(
    mission_id: int,
    file: UploadFile = File(...),
    note: str = Form(None),
    creator_id: int = Form(...),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(path, "wb") as f:
        await f.write(await file.read())
    attachment = MissionAttachment(mission_id=mission_id, file=path, note=note)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    user = db.query(User).filter(User.id == creator_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_attachment_gennis(mission, attachment, gennis_db, creator_name=creator_name)
    _sync_attachment_turon(mission, attachment, turon_db, creator_name=creator_name)
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
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
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
    _sync_attachment_gennis(mission, attachment, gennis_db)
    _sync_attachment_turon(mission, attachment, turon_db)
    return attachment


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(
    mission_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    attachment = db.query(MissionAttachment).filter(
        MissionAttachment.id == attachment_id, MissionAttachment.mission_id == mission_id, MissionAttachment.deleted == False
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _sync_attachment_gennis(mission, attachment, gennis_db, deleted=True)
    _sync_attachment_turon(mission, attachment, turon_db, deleted=True)
    attachment.deleted = True
    db.commit()
