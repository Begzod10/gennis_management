from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from ...database import get_db
from ...models import Section, SectionMember, User
from ...schemas import SectionCreate, SectionUpdate, SectionOut, SectionMemberAdd, SectionMemberOut

router = APIRouter(prefix="/sections", tags=["Sections"])


def _get_section_or_404(db: Session, section_id: int) -> Section:
    section = db.query(Section).filter(Section.id == section_id, Section.deleted == False).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.post("/", response_model=SectionOut, status_code=201)
def create_section(data: SectionCreate, db: Session = Depends(get_db)):
    if data.leader_id and not db.query(User).filter(User.id == data.leader_id).first():
        raise HTTPException(status_code=404, detail="Leader not found")
    section = Section(**data.model_dump())
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@router.get("/", response_model=List[SectionOut])
def list_sections(
    leader_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Section).filter(Section.deleted == False)
    if leader_id:
        q = q.filter(Section.leader_id == leader_id)
    return q.order_by(Section.created_at.desc()).all()


@router.get("/{section_id}", response_model=SectionOut)
def get_section(section_id: int, db: Session = Depends(get_db)):
    return _get_section_or_404(db, section_id)


@router.patch("/{section_id}", response_model=SectionOut)
def update_section(section_id: int, data: SectionUpdate, db: Session = Depends(get_db)):
    section = _get_section_or_404(db, section_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(section, field, value)
    db.commit()
    db.refresh(section)
    return section


@router.delete("/{section_id}", status_code=204)
def delete_section(section_id: int, db: Session = Depends(get_db)):
    section = _get_section_or_404(db, section_id)
    section.deleted = True
    db.commit()


@router.post("/{section_id}/members", response_model=SectionMemberOut, status_code=201)
def add_member(section_id: int, data: SectionMemberAdd, db: Session = Depends(get_db)):
    _get_section_or_404(db, section_id)
    if not db.query(User).filter(User.id == data.user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    existing = (
        db.query(SectionMember)
        .filter(SectionMember.section_id == section_id, SectionMember.user_id == data.user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member of this section")
    member = SectionMember(section_id=section_id, user_id=data.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{section_id}/members/{user_id}", status_code=204)
def remove_member(section_id: int, user_id: int, db: Session = Depends(get_db)):
    _get_section_or_404(db, section_id)
    member = (
        db.query(SectionMember)
        .filter(SectionMember.section_id == section_id, SectionMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    db.commit()


@router.get("/{section_id}/members", response_model=List[SectionMemberOut])
def list_members(section_id: int, db: Session = Depends(get_db)):
    _get_section_or_404(db, section_id)
    return (
        db.query(SectionMember)
        .options(joinedload(SectionMember.user))
        .filter(SectionMember.section_id == section_id)
        .all()
    )
