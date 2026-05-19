import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db, get_gennis_write_db, get_turon_write_db
from app.models import Mission, MissionSubtask, MissionSubtaskProof, User
from app.schemas import MissionSubtaskProofOut
from app.config import settings
from app.external_models.gennis import GennisMissionSubtask, GennisMissionSubtaskProof
from app.external_models.turon import TuronMissionSubtask, TuronMissionSubtaskProof
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_proof_added

router = APIRouter(
    prefix="/missions/{mission_id}/subtasks/{subtask_id}/proofs",
    tags=["Mission Subtask Proofs"],
)

UPLOAD_DIR = "uploads/mission_subtask_proofs"
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


def _sync_gennis(mission: Mission, subtask: MissionSubtask, proof: MissionSubtaskProof, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_subtask = gennis_db.query(GennisMissionSubtask).filter(GennisMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = gennis_db.query(GennisMissionSubtaskProof).filter(GennisMissionSubtaskProof.management_id == proof.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    file_url = f"{settings.BASE_URL}/{proof.file}" if proof.file else None
    if ext:
        ext.file_path = file_url
        ext.comment = proof.comment
    else:
        ext = GennisMissionSubtaskProof(
            management_id=proof.id,
            subtask_id=ext_subtask.id,
            file_path=file_url,
            comment=proof.comment,
            created_at=proof.created_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_turon(mission: Mission, subtask: MissionSubtask, proof: MissionSubtaskProof, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_subtask = turon_db.query(TuronMissionSubtask).filter(TuronMissionSubtask.management_id == subtask.id).first()
    if not ext_subtask:
        return
    ext = turon_db.query(TuronMissionSubtaskProof).filter(TuronMissionSubtaskProof.management_id == proof.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    file_url = f"{settings.BASE_URL}/{proof.file}" if proof.file else None
    if ext:
        ext.file = file_url
        ext.comment = proof.comment
    else:
        ext = TuronMissionSubtaskProof(
            management_id=proof.id,
            subtask_id=ext_subtask.id,
            file=file_url,
            comment=proof.comment,
            created_at=proof.created_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionSubtaskProofOut, status_code=201)
async def upload_proof(
    mission_id: int,
    subtask_id: int,
    file: UploadFile = File(...),
    comment: str = Form(None),
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
    proof = MissionSubtaskProof(subtask_id=subtask_id, file=path, comment=comment, creator_name=creator_name)
    db.add(proof)
    db.commit()
    db.refresh(proof)
    _sync_gennis(mission, subtask, proof, gennis_db, creator_name=creator_name)
    _sync_turon(mission, subtask, proof, turon_db, creator_name=creator_name)

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
                tpl_proof_added(recipient_name, f"{mission.title} / {subtask.title}", creator_name or "—", comment),
            )

    out = MissionSubtaskProofOut.model_validate(proof)
    out.file = _file_url(out.file)
    return out


@router.get("/", response_model=List[MissionSubtaskProofOut])
def list_proofs(mission_id: int, subtask_id: int, db: Session = Depends(get_db)):
    _get_subtask(db, mission_id, subtask_id)
    rows = db.query(MissionSubtaskProof).filter(
        MissionSubtaskProof.subtask_id == subtask_id,
        MissionSubtaskProof.deleted == False,
    ).all()
    result = []
    for row in rows:
        out = MissionSubtaskProofOut.model_validate(row)
        out.file = _file_url(out.file)
        result.append(out)
    return result


@router.patch("/{proof_id}", response_model=MissionSubtaskProofOut)
async def update_proof(
    mission_id: int,
    subtask_id: int,
    proof_id: int,
    file: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    proof = db.query(MissionSubtaskProof).filter(
        MissionSubtaskProof.id == proof_id,
        MissionSubtaskProof.subtask_id == subtask_id,
        MissionSubtaskProof.deleted == False,
    ).first()
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")
    if file:
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        path = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(path, "wb") as f:
            await f.write(await file.read())
        proof.file = path
    if comment is not None:
        proof.comment = comment
    db.commit()
    db.refresh(proof)
    _sync_gennis(mission, subtask, proof, gennis_db)
    _sync_turon(mission, subtask, proof, turon_db)
    out = MissionSubtaskProofOut.model_validate(proof)
    out.file = _file_url(out.file)
    return out


@router.delete("/{proof_id}", status_code=204)
def delete_proof(
    mission_id: int,
    subtask_id: int,
    proof_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission, subtask = _get_subtask(db, mission_id, subtask_id)
    proof = db.query(MissionSubtaskProof).filter(
        MissionSubtaskProof.id == proof_id,
        MissionSubtaskProof.subtask_id == subtask_id,
        MissionSubtaskProof.deleted == False,
    ).first()
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")
    _sync_gennis(mission, subtask, proof, gennis_db, deleted=True)
    _sync_turon(mission, subtask, proof, turon_db, deleted=True)
    proof.deleted = True
    db.commit()
