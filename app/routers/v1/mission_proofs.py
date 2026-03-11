import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ...database import get_db
from ...models import Mission, MissionProof
from ...schemas import MissionProofOut

router = APIRouter(prefix="/missions/{mission_id}/proofs", tags=["Mission Proofs"])

UPLOAD_DIR = "uploads/mission_proofs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_mission(db: Session, mission_id: int) -> Mission:
    mission = db.query(Mission).filter(Mission.id == mission_id, Mission.deleted == False).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


@router.post("/", response_model=MissionProofOut, status_code=201)
async def upload_proof(
    mission_id: int,
    file: UploadFile = File(...),
    comment: str = Form(None),
    db: Session = Depends(get_db),
):
    _get_mission(db, mission_id)
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(path, "wb") as f:
        await f.write(await file.read())
    proof = MissionProof(mission_id=mission_id, file=path, comment=comment)
    db.add(proof)
    db.commit()
    db.refresh(proof)
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
):
    _get_mission(db, mission_id)
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
    return proof


@router.delete("/{proof_id}", status_code=204)
def delete_proof(mission_id: int, proof_id: int, db: Session = Depends(get_db)):
    _get_mission(db, mission_id)
    proof = db.query(MissionProof).filter(
        MissionProof.id == proof_id, MissionProof.mission_id == mission_id, MissionProof.deleted == False
    ).first()
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")
    proof.deleted = True
    db.commit()
