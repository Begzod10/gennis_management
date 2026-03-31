from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ...database import get_db
from sqlalchemy.orm import joinedload
from ...models import User, Section, Project, ProjectMember, SectionMember
from ...schemas import UserCreate, UserUpdate, UserOut, UserProfileOut, UserProjectOut, UserSectionOut
from app.core.security import get_password_hash

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    payload = data.model_dump()
    if not payload.get("job_id"):
        payload["job_id"] = None
    if payload.get("password"):
        payload["hashed_password"] = get_password_hash(payload["password"])
    user = User(**payload)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/", response_model=List[UserOut])
def list_users(role: str = None, db: Session = Depends(get_db)):
    q = db.query(User).filter(User.deleted == False)
    if role:
        q = q.filter(User.role == role)
    return q.all()


@router.get("/project-managers", response_model=List[UserOut])
def list_project_managers(db: Session = Depends(get_db)):
    return (
        db.query(User)
        .join(Project, Project.manager_id == User.id)
        .filter(Project.deleted == False, User.deleted == False)
        .distinct()
        .all()
    )


@router.get("/section-leaders", response_model=List[UserOut])
def list_section_leaders(db: Session = Depends(get_db)):
    return (
        db.query(User)
        .join(Section, Section.leader_id == User.id)
        .filter(Section.deleted == False, User.deleted == False)
        .distinct()
        .all()
    )


@router.get("/{user_id}", response_model=UserProfileOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    projects = (
        db.query(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(ProjectMember.user_id == user_id, Project.deleted == False)
        .all()
    )
    managed_projects = db.query(Project).filter(
        Project.manager_id == user_id, Project.deleted == False
    ).all()
    all_project_ids = {p.id for p in projects}
    for p in managed_projects:
        if p.id not in all_project_ids:
            projects.append(p)

    sections = (
        db.query(Section)
        .join(SectionMember, SectionMember.section_id == Section.id)
        .filter(SectionMember.user_id == user_id, Section.deleted == False)
        .all()
    )
    led_sections = db.query(Section).filter(
        Section.leader_id == user_id, Section.deleted == False
    ).all()
    all_section_ids = {s.id for s in sections}
    for s in led_sections:
        if s.id not in all_section_ids:
            sections.append(s)

    profile = UserProfileOut.model_validate(user)
    profile.projects = [UserProjectOut.model_validate(p) for p in projects]
    profile.sections = [UserSectionOut.model_validate(s) for s in sections]
    return profile


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.deleted = True
    db.commit()
