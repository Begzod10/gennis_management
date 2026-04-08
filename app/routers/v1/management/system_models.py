from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models import SystemModel
from app.schemas import SystemModelCreate, SystemModelUpdate, SystemModelOut

router = APIRouter(prefix="/system-models", tags=["System Models"])


@router.post("/", response_model=SystemModelOut, status_code=201)
def create_system_model(data: SystemModelCreate, db: Session = Depends(get_db)):
    obj = SystemModel(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/", response_model=List[SystemModelOut])
def list_system_models(db: Session = Depends(get_db)):
    return db.query(SystemModel).filter(SystemModel.deleted == False).all()


@router.get("/{system_model_id}", response_model=SystemModelOut)
def get_system_model(system_model_id: int, db: Session = Depends(get_db)):
    obj = db.query(SystemModel).filter(SystemModel.id == system_model_id, SystemModel.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="SystemModel not found")
    return obj


@router.patch("/{system_model_id}", response_model=SystemModelOut)
def update_system_model(system_model_id: int, data: SystemModelUpdate, db: Session = Depends(get_db)):
    obj = db.query(SystemModel).filter(SystemModel.id == system_model_id, SystemModel.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="SystemModel not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{system_model_id}", status_code=204)
def delete_system_model(system_model_id: int, db: Session = Depends(get_db)):
    obj = db.query(SystemModel).filter(SystemModel.id == system_model_id, SystemModel.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="SystemModel not found")
    obj.deleted = True
    db.commit()
