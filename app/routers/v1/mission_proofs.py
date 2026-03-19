import os
import uuid
import aiofiles
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db, get_gennis_write_db, get_turon_write_db
from ...models import Mission, MissionProof, User
from ...schemas import MissionProofOut
from ...external_models.gennis import GennisMission, GennisMissionProof
from ...external_models.turon import TuronMission, TuronMissionProof

router = APIRouter(prefix="/missions/{mission_id}/proofs", tags=["Mission Proofs"])

UPLOAD_DIR = "uploads/mission_proofs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _sync_proof_gennis(mission: Mission, proof: MissionProof, gennis_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.gennis_executor_id:
        return
    ext_mission = gennis_db.query(GennisMission).filter(GennisMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = gennis_db.query(GennisMissionProof).filter(GennisMissionProof.management_id == proof.id).first()
    if deleted:
        if ext:
            gennis_db.delete(ext)
            gennis_db.commit()
        return
    if ext:
        ext.file_path = proof.file
        ext.comment = proof.comment
    else:
        ext = GennisMissionProof(
            management_id=proof.id,
            mission_id=ext_mission.id,
            file_path=proof.file,
            comment=proof.comment,
            created_at=proof.created_at,
            creator_name=creator_name,
        )
        gennis_db.add(ext)
    gennis_db.commit()


def _sync_proof_turon(mission: Mission, proof: MissionProof, turon_db: Session, creator_name: Optional[str] = None, deleted: bool = False):
    if not mission.turon_executor_id:
        return
    ext_mission = turon_db.query(TuronMission).filter(TuronMission.management_id == mission.id).first()
    if not ext_mission:
        return
    ext = turon_db.query(TuronMissionProof).filter(TuronMissionProof.management_id == proof.id).first()
    if deleted:
        if ext:
            turon_db.delete(ext)
            turon_db.commit()
        return
    if ext:
        ext.file = proof.file
        ext.comment = proof.comment
    else:
        ext = TuronMissionProof(
            management_id=proof.id,
            mission_id=ext_mission.id,
            file=proof.file,
            comment=proof.comment,
            created_at=proof.created_at,
            creator_name=creator_name,
        )
        turon_db.add(ext)
    turon_db.commit()


@router.post("/", response_model=MissionProofOut, status_code=201)
async def upload_proof(
    mission_id: int,
    file: UploadFile = File(...),
    comment: str = Form(None),
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
    proof = MissionProof(mission_id=mission_id, file=path, comment=comment)
    db.add(proof)
    db.commit()
    db.refresh(proof)
    user = db.query(User).filter(User.id == creator_id).first()
    creator_name = f"{user.name} {user.surname}".strip() if user else None
    _sync_proof_gennis(mission, proof, gennis_db, creator_name=creator_name)
    _sync_proof_turon(mission, proof, turon_db, creator_name=creator_name)
    return proof


@router.get("/", response_model=List[MissionProofOut])
def list_proofs(mission_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    return db.query(MissionProof).filter(
        MissionProof.mission_id == mission_id, MissionProof.deleted == False
    ).all()


@router.patch("/{proof_id}", response_model=MissionProofOut)
async def update_proof(
    mission_id: int,
    proof_id: int,
    file: Optional[UploadFile] = File(None),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    proof = db.query(MissionProof).filter(
        MissionProof.id == proof_id, MissionProof.mission_id == mission_id, MissionProof.deleted == False
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
    _sync_proof_gennis(mission, proof, gennis_db)
    _sync_proof_turon(mission, proof, turon_db)
    return proof


@router.delete("/{proof_id}", status_code=204)
def delete_proof(
    mission_id: int,
    proof_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    mission = _get_mission(db, mission_id)
    proof = db.query(MissionProof).filter(
        MissionProof.id == proof_id, MissionProof.mission_id == mission_id, MissionProof.deleted == False
    ).first()
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")
    _sync_proof_gennis(mission, proof, gennis_db, deleted=True)
    _sync_proof_turon(mission, proof, turon_db, deleted=True)
    proof.deleted = True
    db.commit()
