"""Admin Request proxy router.

Reads `admin_request` rows from the Gennis (Flask) and Turon (Django) source DBs
and lets management edit only `status` and `comment`. The records themselves
live in the source DBs — there is no mirror table in management.

Endpoints:
- GET    /admin-requests
- GET    /admin-requests/{source}/{request_id}
- PATCH  /admin-requests/{source}/{request_id}
"""

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_gennis_write_db, get_turon_write_db
from app.external_models.gennis import (
    GennisAdminRequest,
    Locations as GennisLocations,
    Users as GennisUsers,
)
from app.external_models.turon import (
    TuronAdminRequest,
    Branch as TuronBranch,
    TuronCustomUser,
)


router = APIRouter(prefix="/admin-requests", tags=["Admin Requests"])

Source = Literal["gennis", "turon"]


# ── Schemas ───────────────────────────────────────────────────────────────────


class AdminRequestUpdate(BaseModel):
    status: Optional[bool] = None
    comment: Optional[str] = None


class AdminRequestOut(BaseModel):
    source: Source
    id: int
    name: Optional[str]
    description: Optional[str]
    deadline: Optional[str]
    comment: Optional[str]
    status: bool
    branch_id: Optional[int]
    branch_name: Optional[str]
    user_id: Optional[int]
    user_name: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


# ── Serializers ───────────────────────────────────────────────────────────────


def _fmt_date(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d") if value else None


def _fmt_dt(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _serialize_gennis(req: GennisAdminRequest, db: Session) -> dict:
    branch_name = None
    if req.branch_id:
        loc = db.query(GennisLocations).filter(GennisLocations.id == req.branch_id).first()
        branch_name = loc.name if loc else None

    user_name = None
    if req.user_id:
        u = db.query(GennisUsers).filter(GennisUsers.id == req.user_id).first()
        if u:
            user_name = " ".join(p for p in (u.name, u.surname) if p) or None

    return {
        "source": "gennis",
        "id": req.id,
        "name": req.name,
        "description": req.description,
        "deadline": _fmt_date(req.deadline),
        "comment": req.comment,
        "status": bool(req.status),
        "branch_id": req.branch_id,
        "branch_name": branch_name,
        "user_id": req.user_id,
        "user_name": user_name,
        "created_at": _fmt_dt(req.created_at),
        "updated_at": _fmt_dt(req.updated_at),
    }


def _serialize_turon(req: TuronAdminRequest, db: Session) -> dict:
    branch_name = None
    if req.branch_id:
        br = db.query(TuronBranch).filter(TuronBranch.id == req.branch_id).first()
        branch_name = br.name if br else None

    user_name = None
    if req.user_id:
        u = db.query(TuronCustomUser).filter(TuronCustomUser.id == req.user_id).first()
        if u:
            user_name = " ".join(p for p in (u.name, u.surname) if p) or None

    return {
        "source": "turon",
        "id": req.id,
        "name": req.name,
        "description": req.description,
        "deadline": _fmt_date(req.deadline),
        "comment": req.comment,
        "status": bool(req.status),
        "branch_id": req.branch_id,
        "branch_name": branch_name,
        "user_id": req.user_id,
        "user_name": user_name,
        "created_at": _fmt_dt(req.created_at),
        "updated_at": _fmt_dt(req.updated_at),
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=List[AdminRequestOut])
def list_admin_requests(
    source: Optional[Source] = Query(None, description="Filter to one source: 'gennis' or 'turon'"),
    status: Optional[bool] = Query(None, description="Filter by status (true=resolved, false=open)"),
    branch_id: Optional[int] = Query(None, description="Filter to one Turon branch"),
    location_id: Optional[int] = Query(None, description="Filter to one Gennis location"),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Combined list across both source DBs, sorted by created_at desc."""
    rows: List[dict] = []

    if source in (None, "gennis"):
        q = gennis_db.query(GennisAdminRequest)
        if status is not None:
            q = q.filter(GennisAdminRequest.status == status)
        if location_id is not None:
            q = q.filter(GennisAdminRequest.branch_id == location_id)
        rows.extend(_serialize_gennis(r, gennis_db) for r in q.all())

    if source in (None, "turon"):
        q = turon_db.query(TuronAdminRequest)
        if status is not None:
            q = q.filter(TuronAdminRequest.status == status)
        if branch_id is not None:
            q = q.filter(TuronAdminRequest.branch_id == branch_id)
        rows.extend(_serialize_turon(r, turon_db) for r in q.all())

    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return rows


@router.get("/{source}/{request_id}", response_model=AdminRequestOut)
def get_admin_request(
    source: Source,
    request_id: int,
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    if source == "gennis":
        req = gennis_db.query(GennisAdminRequest).filter(GennisAdminRequest.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Gennis admin request not found")
        return _serialize_gennis(req, gennis_db)

    req = turon_db.query(TuronAdminRequest).filter(TuronAdminRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Turon admin request not found")
    return _serialize_turon(req, turon_db)


@router.patch("/{source}/{request_id}", response_model=AdminRequestOut)
def update_admin_request(
    source: Source,
    request_id: int,
    data: AdminRequestUpdate,
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Update only `status` and/or `comment` on an admin request in its source DB."""
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No updatable fields provided")

    if source == "gennis":
        req = gennis_db.query(GennisAdminRequest).filter(GennisAdminRequest.id == request_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Gennis admin request not found")
        for field, value in payload.items():
            setattr(req, field, value)
        req.updated_at = datetime.utcnow()
        gennis_db.commit()
        gennis_db.refresh(req)
        return _serialize_gennis(req, gennis_db)

    req = turon_db.query(TuronAdminRequest).filter(TuronAdminRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Turon admin request not found")
    for field, value in payload.items():
        setattr(req, field, value)
    req.updated_at = datetime.utcnow()
    turon_db.commit()
    turon_db.refresh(req)
    return _serialize_turon(req, turon_db)
