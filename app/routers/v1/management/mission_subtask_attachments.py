import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db, get_gennis_write_db, get_turon_write_db
from app.models import Mission, MissionSubtask, MissionSubtaskAttachment, User
from app.schemas import MissionSubtaskAttachmentOut
from app.config import settings
from app.external_models.gennis import GennisMissionSubtask, GennisMissionSubtaskAttachment
from app.external_models.turon import TuronMissionSubtask, TuronMissionSubtaskAttachment
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_attachment_added

router = APIRouter(
    prefix="/missions/{mission_id}/subtasks/{subtask_id}/attachments",
    tags=["Mission Subtask Attachments"],
)

UPLOAD_DIR = "uploads/mission_subtask_attachments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _file_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return path
    if path.startswith(("http://", "https://")):
        return path
    return f"{settings.BASE_URL}/{path}"


def _get_subtask(db: Session, mission_id: int, subtask_id: int) -> tuple[Mission, MissionSubtask]:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    subtask = db.query(MissionSubtask).filter(
        MissionSubtask.id == subtask_id,
        MissionSubtask.mission_id == mission_id,
        MissionSubtask.deleted == False,
    ).first()
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")
    return mission, subtask


def _sync_gennis(mission: Mission, subtask: MissionSubtask, attachment: MissionSubtaskAttachment, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_subtask = gennis_db.query(GennisMissionSubtask).filter(GennisMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = gennis_db.query(GennisMissionSubtaskAttachment).filter(GennisMissionSubtaskAttachment.management_id == attachment.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    file_url = f"{settings.BASE_URL}/{attachment.file}" if attachment.file else None
    if ext:
        ext.file_path = file_url
        ext.note = attachment.note
    else:
        ext = GennisMissionSubtaskAttachment(
            management_id=attachment.id,
            subtask_id=ext_subtask.id,
            file_path=file_url,
            note=attachment.note,
            uploaded_at=attachment.uploaded_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_turon(mission: Mission, subtask: MissionSubtask, attachment: MissionSubtaskAttachment, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_subtask = turon_db.query(TuronMissionSubtask).filter(TuronMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = turon_db.query(TuronMissionSubtaskAttachment).filter(TuronMissionSubtaskAttachment.management_id == attachment.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    file_url = f"{settings.BASE_URL}/{attachment.file}" if attachment.file else None
    if ext:
        ext.file = file_url
        ext.note = attachment.note
    else:
        ext = TuronMissionSubtaskAttachment(
            management_id=attachment.id,
            subtask_id=ext_subtask.id,
            file=file_url,
            note=attachment.note,
            uploaded_at=attachment.uploaded_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionSubtaskAttachmentOut, status_code=201)
async def upload_attachment(
    mission_id: int,
    subtask_id: int,
    file: UploadFile = File(...),
    note: str = Form(None),
    creator_id: int = Form(...),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(path, "wb") as f:
        await f.write(await file.read())

    user = db.query(User).filter(User.id == creator_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    attachment = MissionSubtaskAttachment(subtask_id=subtask_id, file=path, note=note, creator_name=creator_name)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    _sync_gennis(mission, subtask, attachment, gennis_db, creator_name=creator_name)
    _sync_turon(mission, subtask, attachment, turon_db, creator_name=creator_name)

    recipients = {
        mission.executor_id, mission.reviewer_id, mission.creator_id,
        subtask.executor_id, subtask.creator_id, subtask.reviewer_id,
    } - {creator_id, None}
    for uid in recipients:
        u = db.query(User).filter(User.id == uid).first()
        if u and u.telegram_id:
            recipient_name = f"{u.name} {u.surname}".strip() if u.surname else u.name
            send_telegram_notification.delay(
                u.telegram_id,
                tpl_attachment_added(recipient_name, f"{mission.title} / {subtask.title}", creator_name or "—"),
            )

    out = MissionSubtaskAttachmentOut.model_validate(attachment)
    out.file = _file_url(out.file)
    return out


@router.get("/", response_model=List[MissionSubtaskAttachmentOut])
def list_attachments(mission_id: int, subtask_id: int, db: Session = Depends(get_db)):
    _get_subtask(db, mission_id, subtask_id)
    rows = db.query(MissionSubtaskAttachment).filter(
        MissionSubtaskAttachment.subtask_id == subtask_id,
        MissionSubtaskAttachment.deleted == False,
    ).all()
    result = []
    for row in rows:
        out = MissionSubtaskAttachmentOut.model_validate(row)
        out.file = _file_url(out.file)
        result.append(out)
    return result


@router.patch("/{attachment_id}", response_model=MissionSubtaskAttachmentOut)
async def update_attachment(
    mission_id: int,
    subtask_id: int,
    attachment_id: int,
    file: Optional[UploadFile] = File(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    attachment = db.query(MissionSubtaskAttachment).filter(
        MissionSubtaskAttachment.id == attachment_id,
        MissionSubtaskAttachment.subtask_id == subtask_id,
        MissionSubtaskAttachment.deleted == False,
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
    _sync_gennis(mission, subtask, attachment, gennis_db)
    _sync_turon(mission, subtask, attachment, turon_db)
    out = MissionSubtaskAttachmentOut.model_validate(attachment)
    out.file = _file_url(out.file)
    return out


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(
    mission_id: int,
    subtask_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    attachment = db.query(MissionSubtaskAttachment).filter(
        MissionSubtaskAttachment.id == attachment_id,
        MissionSubtaskAttachment.subtask_id == subtask_id,
        MissionSubtaskAttachment.deleted == False,
    ).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")
    _sync_gennis(mission, subtask, attachment, gennis_db, deleted=True)
    _sync_turon(mission, subtask, attachment, turon_db, deleted=True)
    attachment.deleted = True
    db.commit()
