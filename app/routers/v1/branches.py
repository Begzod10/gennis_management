from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ...database import get_db
from ...models import Branch
from ...schemas import BranchCreate, BranchOut

router = APIRouter(prefix="/branches", tags=["Branches"])


@router.post("/", response_model=BranchOut, status_code=201)
def create_branch(data: BranchCreate, db: Session = Depends(get_db)):
    branch = Branch(**data.model_dump())
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch


@router.get("/", response_model=List[BranchOut])
def list_branches(db: Session = Depends(get_db)):
    return db.query(Branch).filter(Branch.deleted == False).all()


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(branch_id: int, db: Session = Depends(get_db)):
    branch = db.query(Branch).filter(Branch.id == branch_id, Branch.deleted == False).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch


@router.patch("/{branch_id}", response_model=BranchOut)
def update_branch(branch_id: int, data: BranchCreate, db: Session = Depends(get_db)):
    branch = db.query(Branch).filter(Branch.id == branch_id, Branch.deleted == False).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(branch, field, value)
    db.commit()
    db.refresh(branch)
    return branch


@router.delete("/{branch_id}", status_code=204)
def delete_branch(branch_id: int, db: Session = Depends(get_db)):
    branch = db.query(Branch).filter(Branch.id == branch_id, Branch.deleted == False).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    branch.deleted = True
    db.commit()
