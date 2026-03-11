from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ...database import get_db
from ...models import Tag
from ...schemas import TagCreate, TagOut

router = APIRouter(prefix="/tags", tags=["Tags"])


@router.post("/", response_model=TagOut, status_code=201)
def create_tag(data: TagCreate, db: Session = Depends(get_db)):
    existing = db.query(Tag).filter(Tag.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tag already exists")
    tag = Tag(**data.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.get("/", response_model=List[TagOut])
def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).filter(Tag.deleted == False).all()


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.deleted == False).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    tag.deleted = True
    db.commit()
