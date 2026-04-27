from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, aliased
from typing import List, Optional
from app.database import get_db
from app.models import Project, ProjectMember, User
from app.schemas import ProjectCreate, ProjectUpdate, ProjectOut, ProjectMemberAdd, ProjectMemberOut

router = APIRouter(prefix="/projects", tags=["Projects"])


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted == False).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, manager_id: int, db: Session = Depends(get_db)):
    manager = db.query(User).filter(User.id == manager_id).first()
    if not manager:
        raise HTTPException(status_code=404, detail="Manager not found")
    manager.role = "manager"
    project = Project(**data.model_dump(), manager_id=manager_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/", response_model=List[ProjectOut])
def list_projects(
    manager_id: Optional[int] = None,
    leader_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Project).options(joinedload(Project.manager)).filter(Project.deleted == False)
    if manager_id:
        q = q.filter(Project.manager_id == manager_id)
    if leader_id:
        MemberUser = aliased(User)
        q = (
            q.join(ProjectMember, ProjectMember.project_id == Project.id)
            .join(MemberUser, MemberUser.id == ProjectMember.user_id)
            .filter(
                ProjectMember.user_id == leader_id,
                MemberUser.role.in_(["team_lead", "project_manager"]),
                MemberUser.deleted == False,
            )
        )
    return q.order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .options(joinedload(Project.manager))
        .filter(Project.id == project_id, Project.deleted == False)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    project.deleted = True
    db.commit()


@router.post("/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
def add_member(project_id: int, data: ProjectMemberAdd, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    if not db.query(User).filter(User.id == data.user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    existing = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == data.user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member of this project")
    member = ProjectMember(project_id=project_id, user_id=data.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: int, user_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    db.commit()


@router.get("/{project_id}/members", response_model=List[ProjectMemberOut])
def list_members(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(db, project_id)
    return (
        db.query(ProjectMember)
        .options(joinedload(ProjectMember.user))
        .filter(ProjectMember.project_id == project_id)
        .all()
    )


@router.get("/{project_id}/manager")
def get_project_manager(project_id: int, db: Session = Depends(get_db)):
    """Return the manager user of a project."""
    project = _get_project_or_404(db, project_id)
    user = db.query(User).filter(User.id == project.manager_id, User.deleted == False).first()
    if not user:
        raise HTTPException(status_code=404, detail="Manager not found")
    return {
        "id": user.id,
        "name": user.name,
        "surname": user.surname,
        "email": user.email,
        "role": user.role,
    }


@router.get("/{project_id}/leaders")
def list_leaders(project_id: int, db: Session = Depends(get_db)):
    """Return project members whose role is team_lead or project_manager."""
    _get_project_or_404(db, project_id)
    rows = (
        db.query(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .filter(
            ProjectMember.project_id == project_id,
            User.role.in_(["team_lead", "project_manager"]),
            User.deleted == False,
        )
        .all()
    )
    return [
        {
            "id": u.id,
            "name": u.name,
            "surname": u.surname,
            "email": u.email,
            "role": u.role,
        }
        for u in rows
    ]
