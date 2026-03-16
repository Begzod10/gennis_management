from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract
from typing import Optional

from ...database import get_db, get_gennis_write_db, get_turon_write_db
from ...models import Investment
from ...external_models.gennis import GennisInvestment
from ...external_models.turon import TuronInvestment
from ...schemas import InvestmentCreate, InvestmentUpdate, InvestmentOut
from ...dependencies import get_current_user

router = APIRouter(prefix="/investments", tags=["Investments"])


def _sync_create(external_db: Session, external_model, local_obj: Investment):
    kwargs = dict(
        management_id=local_obj.id,
        amount=local_obj.amount,
        date=local_obj.date,
        description=local_obj.description,
        payment_type=local_obj.payment_type,
        deleted=False,
    )
    if hasattr(external_model, "location_id"):
        kwargs["location_id"] = local_obj.location_id
    if hasattr(external_model, "branch_id"):
        kwargs["branch_id"] = local_obj.branch_id
    external_db.add(external_model(**kwargs))
    external_db.commit()


def _sync_update(external_db: Session, external_model, local_obj: Investment):
    record = external_db.query(external_model).filter(
        external_model.management_id == local_obj.id
    ).first()
    if record:
        record.amount = local_obj.amount
        record.date = local_obj.date
        record.description = local_obj.description
        record.payment_type = local_obj.payment_type
        if hasattr(external_model, "location_id"):
            record.location_id = local_obj.location_id
        if hasattr(external_model, "branch_id"):
            record.branch_id = local_obj.branch_id
        external_db.commit()


def _sync_delete(external_db: Session, external_model, management_id: int):
    record = external_db.query(external_model).filter(
        external_model.management_id == management_id
    ).first()
    if record:
        record.deleted = True
        external_db.commit()


@router.get("", response_model=list[InvestmentOut])
def list_investments(
    source: Optional[str] = Query(None, description="Filter by source: gennis or turon"),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Investment).filter(Investment.deleted == False)
    if source:
        q = q.filter(Investment.source == source)
    if month:
        q = q.filter(extract("month", Investment.date) == month)
    if year:
        q = q.filter(extract("year", Investment.date) == year)
    return q.order_by(Investment.date.desc()).all()


@router.post("", response_model=InvestmentOut)
def create_investment(
    data: InvestmentCreate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
    _=Depends(get_current_user),
):
    if data.source not in ("gennis", "turon"):
        raise HTTPException(status_code=400, detail="source must be 'gennis' or 'turon'")

    obj = Investment(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)

    if data.source == "gennis":
        _sync_create(gennis_db, GennisInvestment, obj)
    else:
        _sync_create(turon_db, TuronInvestment, obj)

    return obj


@router.get("/{investment_id}", response_model=InvestmentOut)
def get_investment(
    investment_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    obj = db.query(Investment).filter(Investment.id == investment_id, Investment.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Investment not found")
    return obj


@router.patch("/{investment_id}", response_model=InvestmentOut)
def update_investment(
    investment_id: int,
    data: InvestmentUpdate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
    _=Depends(get_current_user),
):
    obj = db.query(Investment).filter(Investment.id == investment_id, Investment.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Investment not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)

    external_db = gennis_db if obj.source == "gennis" else turon_db
    external_model = GennisInvestment if obj.source == "gennis" else TuronInvestment
    _sync_update(external_db, external_model, obj)

    return obj


@router.delete("/{investment_id}")
def delete_investment(
    investment_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
    _=Depends(get_current_user),
):
    obj = db.query(Investment).filter(Investment.id == investment_id, Investment.deleted == False).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Investment not found")

    if obj.source == "gennis":
        _sync_delete(gennis_db, GennisInvestment, obj.id)
    else:
        _sync_delete(turon_db, TuronInvestment, obj.id)

    obj.deleted = True
    db.commit()
    return {"detail": "Investment deleted"}
