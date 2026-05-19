import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.database import get_db, get_gennis_write_db, get_turon_write_db
from app.models import Mission, MissionSubtask, MissionSubtaskComment, User
from app.schemas import MissionSubtaskCommentOut
from app.config import settings
from app.external_models.gennis import GennisMissionSubtask, GennisMissionSubtaskComment
from app.external_models.turon import TuronMissionSubtask, TuronMissionSubtaskComment
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_comment_added

router = APIRouter(
    prefix="/missions/{mission_id}/subtasks/{subtask_id}/comments",
    tags=["Mission Subtask Comments"],
)

UPLOAD_DIR = "uploads/mission_subtask_comments"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _attachment_url(path: Optional[str]) -> Optional[str]:
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


def _sync_comment_gennis(mission: Mission, subtask: MissionSubtask, comment: MissionSubtaskComment, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_subtask = gennis_db.query(GennisMissionSubtask).filter(GennisMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = gennis_db.query(GennisMissionSubtaskComment).filter(GennisMissionSubtaskComment.management_id == comment.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    attachment_url = f"{settings.BASE_URL}/{comment.attachment}" if comment.attachment else None
    if ext:
        ext.text = comment.text
        ext.attachment_path = attachment_url
        ext.creator_name = creator_name
    else:
        ext = GennisMissionSubtaskComment(
            management_id=comment.id,
            subtask_id=ext_subtask.id,
            user_id=None,
            text=comment.text,
            attachment_path=attachment_url,
            created_at=comment.created_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_comment_turon(mission: Mission, subtask: MissionSubtask, comment: MissionSubtaskComment, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_subtask = turon_db.query(TuronMissionSubtask).filter(TuronMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = turon_db.query(TuronMissionSubtaskComment).filter(TuronMissionSubtaskComment.management_id == comment.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    attachment_url = f"{settings.BASE_URL}/{comment.attachment}" if comment.attachment else None
    if ext:
        ext.text = comment.text
        ext.attachment = attachment_url
        ext.creator_name = creator_name
    else:
        ext = TuronMissionSubtaskComment(
            management_id=comment.id,
            subtask_id=ext_subtask.id,
            user_id=None,
            text=comment.text,
            attachment=attachment_url,
            created_at=comment.created_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionSubtaskCommentOut, status_code=201)
async def create_comment(
    mission_id: int,
    subtask_id: int,
    user_id: int = Form(...),
    text: str = Form(...),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    attachment_path = None
    if attachment:
        ext = os.path.splitext(attachment.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        attachment_path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(attachment_path, "wb") as f:
            await f.write(await attachment.read())

    user = db.query(User).filter(User.id == user_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    comment = MissionSubtaskComment(
        subtask_id=subtask_id,
        user_id=user_id,
        text=text,
        attachment=attachment_path,
        creator_name=creator_name,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    _sync_comment_gennis(mission, subtask, comment, gennis_db, creator_name=creator_name)
    _sync_comment_turon(mission, subtask, comment, turon_db, creator_name=creator_name)

    recipients = {
        mission.executor_id, mission.reviewer_id, mission.creator_id,
        subtask.executor_id, subtask.creator_id, subtask.reviewer_id,
    } - {user_id, None}
    for uid in recipients:
        u = db.query(User).filter(User.id == uid).first()
        if u and u.telegram_id:
            recipient_name = f"{u.name} {u.surname}".strip() if u.surname else u.name
            send_telegram_notification.delay(
                u.telegram_id,
                tpl_comment_added(recipient_name, f"{mission.title} / {subtask.title}", creator_name or "—", text),
            )

    out = MissionSubtaskCommentOut.model_validate(comment)
    out.attachment = _attachment_url(out.attachment)
    return out


@router.get("/", response_model=List[MissionSubtaskCommentOut])
def list_comments(mission_id: int, subtask_id: int, db: Session = Depends(get_db)):
    _get_subtask(db, mission_id, subtask_id)
    rows = db.query(MissionSubtaskComment).options(
        joinedload(MissionSubtaskComment.user)
    ).filter(
        MissionSubtaskComment.subtask_id == subtask_id,
        MissionSubtaskComment.deleted == False,
    ).order_by(MissionSubtaskComment.created_at).all()
    result = []
    for row in rows:
        out = MissionSubtaskCommentOut.model_validate(row)
        out.attachment = _attachment_url(out.attachment)
        result.append(out)
    return result


@router.patch("/{comment_id}", response_model=MissionSubtaskCommentOut)
async def update_comment(
    mission_id: int,
    subtask_id: int,
    comment_id: int,
    text: Optional[str] = Form(None),
    attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    comment = db.query(MissionSubtaskComment).filter(
        MissionSubtaskComment.id == comment_id,
        MissionSubtaskComment.subtask_id == subtask_id,
        MissionSubtaskComment.deleted == False,
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
    _sync_comment_gennis(mission, subtask, comment, gennis_db, creator_name=creator_name)
    _sync_comment_turon(mission, subtask, comment, turon_db, creator_name=creator_name)
    out = MissionSubtaskCommentOut.model_validate(comment)
    out.attachment = _attachment_url(out.attachment)
    return out


@router.delete("/{comment_id}", status_code=204)
def delete_comment(
    mission_id: int,
    subtask_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    comment = db.query(MissionSubtaskComment).filter(
        MissionSubtaskComment.id == comment_id,
        MissionSubtaskComment.subtask_id == subtask_id,
        MissionSubtaskComment.deleted == False,
    ).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    _sync_comment_gennis(mission, subtask, comment, gennis_db, deleted=True)
    _sync_comment_turon(mission, subtask, comment, turon_db, deleted=True)
    comment.deleted = True
    db.commit()
