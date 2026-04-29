from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db, get_gennis_write_db, get_turon_write_db
from app.models import OverheadType
from app.external_models.gennis import (
    OverheadType as GennisOverheadType, Overhead as GennisOverhead, Locations as GennisLocations,
)
from app.external_models.turon import OverheadType as TuronOverheadType, Branch as TuronBranch
from app.schemas import OverheadTypeCreate, OverheadTypeUpdate, OverheadTypeOut


class CopyUpdate(BaseModel):
    cost: Optional[int] = None
    changeable: Optional[bool] = None

router = APIRouter(prefix="/overhead-types", tags=["Overhead Types"])


def _get_or_404(db: Session, overhead_type_id: int) -> OverheadType:
    obj = db.query(OverheadType).filter(
        OverheadType.id == overhead_type_id,
        OverheadType.deleted == False,
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Overhead type not found")
    return obj


def _sync_create(gennis_db: Session, turon_db: Session, local_obj: OverheadType):
    """Create per-location copies in Gennis and per-branch copies in Turon.
    All copies share the same management_id so future updates propagate to all of them.
    Costs are intentionally inherited from the management row; if `changeable=False`
    the user is expected to override costs per location/branch via the copy-edit routes.
    """
    for loc in gennis_db.query(GennisLocations).all():
        gennis_db.add(GennisOverheadType(
            management_id=local_obj.id,
            name=local_obj.name,
            cost=local_obj.cost,
            changeable=local_obj.changeable,
            location_id=loc.id,
            deleted=False,
        ))
    gennis_db.commit()

    for br in turon_db.query(TuronBranch).all():
        turon_db.add(TuronOverheadType(
            management_id=local_obj.id,
            name=local_obj.name,
            cost=local_obj.cost,
            changeable=local_obj.changeable,
            branch_id=br.id,
            deleted=False,
        ))
    turon_db.commit()


def _sync_update(gennis_db: Session, turon_db: Session, local_obj: OverheadType):
    """Propagate name + changeable to every per-location/per-branch copy.
    Cost is intentionally NOT synced — each copy is edited individually because
    fixed (non-changeable) types have different costs per location/branch.
    """
    gennis_records = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.management_id == local_obj.id
    ).all()
    for g in gennis_records:
        g.name = local_obj.name
        g.changeable = local_obj.changeable
    gennis_db.commit()

    turon_records = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.management_id == local_obj.id
    ).all()
    for t in turon_records:
        t.name = local_obj.name
        t.changeable = local_obj.changeable
    turon_db.commit()


def _sync_delete(gennis_db: Session, turon_db: Session, management_id: int):
    gennis_records = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.management_id == management_id
    ).all()
    for g in gennis_records:
        g.deleted = True
    gennis_db.commit()

    turon_records = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.management_id == management_id
    ).all()
    for t in turon_records:
        t.deleted = True
    turon_db.commit()


@router.get("/from-gennis")
def list_gennis_overhead_types(gennis_db: Session = Depends(get_gennis_write_db)):
    subq = gennis_db.query(GennisOverhead.overhead_type_id).filter(
        GennisOverhead.overhead_type_id != None
    ).distinct().subquery()

    rows = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.id.in_(subq),
        GennisOverheadType.deleted == False,
    ).order_by(GennisOverheadType.id).all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "cost": r.cost,
            "changeable": r.changeable,
            "management_id": r.management_id,
        }
        for r in rows
    ]


@router.get("", response_model=List[OverheadTypeOut])
def list_overhead_types(db: Session = Depends(get_db)):
    return db.query(OverheadType).filter(OverheadType.deleted == False).all()


@router.post("", response_model=OverheadTypeOut, status_code=201)
def create_overhead_type(
    data: OverheadTypeCreate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    obj = OverheadType(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    _sync_create(gennis_db, turon_db, obj)
    return obj


@router.post("/import-from-turon", status_code=200)
def import_overhead_types_from_turon(
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    turon_types = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.deleted == False
    ).all()

    created = []
    skipped = []

    for t in turon_types:
        if t.management_id:
            skipped.append(t.name)
            continue

        existing = db.query(OverheadType).filter(
            OverheadType.name == t.name,
            OverheadType.deleted == False,
        ).first()

        if existing:
            t.management_id = existing.id
            gennis_exists = gennis_db.query(GennisOverheadType).filter(
                GennisOverheadType.management_id == existing.id
            ).first()
            if not gennis_exists:
                gennis_db.add(GennisOverheadType(
                    management_id=existing.id,
                    name=existing.name,
                    cost=existing.cost,
                    changeable=existing.changeable,
                    deleted=False,
                ))
            skipped.append(t.name)
            continue

        obj = OverheadType(name=t.name, changeable=True, deleted=False)
        db.add(obj)
        db.flush()

        gennis_db.add(GennisOverheadType(
            management_id=obj.id,
            name=obj.name,
            cost=obj.cost,
            changeable=obj.changeable,
            deleted=False,
        ))

        t.management_id = obj.id
        created.append(t.name)

    db.commit()
    gennis_db.commit()
    turon_db.commit()

    return {"created": created, "skipped": skipped}


# ── Flat lists across all locations / branches ────────────────────────────────


@router.get("/gennis")
def list_all_gennis_overhead_types(
    location_id: Optional[int] = Query(None, description="Filter to one location"),
    gennis_db: Session = Depends(get_gennis_write_db),
):
    """List every Gennis OverheadType copy, optionally filtered by location."""
    q = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.deleted == False,
    )
    if location_id:
        q = q.filter(GennisOverheadType.location_id == location_id)
    rows = q.order_by(GennisOverheadType.location_id, GennisOverheadType.id).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "cost": r.cost,
            "changeable": r.changeable,
            "location_id": r.location_id,
            "management_id": r.management_id,
        }
        for r in rows
    ]


@router.get("/turon")
def list_all_turon_overhead_types(
    branch_id: Optional[int] = Query(None, description="Filter to one branch"),
    turon_db: Session = Depends(get_turon_write_db),
):
    """List every Turon OverheadType copy, optionally filtered by branch."""
    q = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.deleted == False,
    )
    if branch_id:
        q = q.filter(TuronOverheadType.branch_id == branch_id)
    rows = q.order_by(TuronOverheadType.branch_id, TuronOverheadType.id).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "cost": r.cost,
            "changeable": r.changeable,
            "branch_id": r.branch_id,
            "management_id": r.management_id,
        }
        for r in rows
    ]


# ── Per-location / per-branch copies ──────────────────────────────────────────
# Each management OverheadType has N copies in Gennis (one per location) and
# M copies in Turon (one per branch). These routes let the accountant view and
# edit the cost per location/branch — used when `changeable=False` (fixed/recurring
# expenses where each location pays a different fixed amount).


@router.get("/{management_id}/gennis-copies")
def list_gennis_copies(
    management_id: int,
    location_id: Optional[int] = Query(None, description="Filter to one location"),
    gennis_db: Session = Depends(get_gennis_write_db),
):
    """List per-location Gennis copies of a management OverheadType."""
    q = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.management_id == management_id,
        GennisOverheadType.deleted == False,
    )
    if location_id:
        q = q.filter(GennisOverheadType.location_id == location_id)
    rows = q.order_by(GennisOverheadType.location_id).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "cost": r.cost,
            "changeable": r.changeable,
            "location_id": r.location_id,
            "management_id": r.management_id,
        }
        for r in rows
    ]


@router.get("/{management_id}/turon-copies")
def list_turon_copies(
    management_id: int,
    branch_id: Optional[int] = Query(None, description="Filter to one branch"),
    turon_db: Session = Depends(get_turon_write_db),
):
    """List per-branch Turon copies of a management OverheadType."""
    q = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.management_id == management_id,
        TuronOverheadType.deleted == False,
    )
    if branch_id:
        q = q.filter(TuronOverheadType.branch_id == branch_id)
    rows = q.order_by(TuronOverheadType.branch_id).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "cost": r.cost,
            "changeable": r.changeable,
            "branch_id": r.branch_id,
            "management_id": r.management_id,
        }
        for r in rows
    ]


@router.patch("/gennis-copies/{gennis_id}")
def update_gennis_copy(
    gennis_id: int,
    data: CopyUpdate,
    gennis_db: Session = Depends(get_gennis_write_db),
):
    """Update one Gennis copy (typically `cost`). Use this when `changeable=False`
    and a specific location pays a different fixed amount."""
    obj = gennis_db.query(GennisOverheadType).filter(
        GennisOverheadType.id == gennis_id,
        GennisOverheadType.deleted == False,
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Gennis OverheadType copy not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    gennis_db.commit()
    gennis_db.refresh(obj)
    return {
        "id": obj.id,
        "name": obj.name,
        "cost": obj.cost,
        "changeable": obj.changeable,
        "location_id": obj.location_id,
        "management_id": obj.management_id,
    }


@router.patch("/turon-copies/{turon_id}")
def update_turon_copy(
    turon_id: int,
    data: CopyUpdate,
    turon_db: Session = Depends(get_turon_write_db),
):
    """Update one Turon copy (typically `cost`). Use this when `changeable=False`
    and a specific branch pays a different fixed amount."""
    obj = turon_db.query(TuronOverheadType).filter(
        TuronOverheadType.id == turon_id,
        TuronOverheadType.deleted == False,
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Turon OverheadType copy not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    turon_db.commit()
    turon_db.refresh(obj)
    return {
        "id": obj.id,
        "name": obj.name,
        "cost": obj.cost,
        "changeable": obj.changeable,
        "branch_id": obj.branch_id,
        "management_id": obj.management_id,
    }


@router.get("/{overhead_type_id}", response_model=OverheadTypeOut)
def get_overhead_type(overhead_type_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, overhead_type_id)


@router.patch("/{overhead_type_id}", response_model=OverheadTypeOut)
def update_overhead_type(
    overhead_type_id: int,
    data: OverheadTypeUpdate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    obj = _get_or_404(db, overhead_type_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    _sync_update(gennis_db, turon_db, obj)
    return obj


@router.delete("/{overhead_type_id}", status_code=204)
def delete_overhead_type(
    overhead_type_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    obj = _get_or_404(db, overhead_type_id)
    _sync_delete(gennis_db, turon_db, obj.id)
    obj.deleted = True
    db.commit()
