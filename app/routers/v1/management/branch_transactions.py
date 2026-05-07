"""Branch Transactions proxy router.

Read-only listing of cash-flow transactions from the Gennis (Flask) and Turon
(Django) source DBs. Records live in the source DBs — there is no mirror table
in management.

Endpoints:
- GET /branch-transactions
- GET /branch-transactions/{source}/{tx_id}
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_gennis_write_db, get_turon_write_db
from app.external_models.gennis import (
    CalendarDay as GennisCalendarDay,
    GennisBranchTransaction,
    Locations as GennisLocations,
    PaymentTypes as GennisPaymentTypes,
    Users as GennisUsers,
)
from app.external_models.turon import (
    Branch as TuronBranch,
    PaymentTypes as TuronPaymentTypes,
    TuronBranchTransaction,
    TuronCustomUser,
)

router = APIRouter(prefix="/branch-transactions", tags=["Branch Transactions"])

Source = Literal["gennis", "turon"]


# ── Schemas ───────────────────────────────────────────────────────────────────


class PartySummary(BaseModel):
    id: Optional[int]
    name: Optional[str]
    surname: Optional[str]
    phone: Optional[str]


class BranchTransactionOut(BaseModel):
    source: Source
    id: int
    management_id: Optional[int]
    amount: int
    is_give: bool
    direction: str
    reason: Optional[str]
    person: PartySummary
    payment_type_id: Optional[int]
    payment_type_name: Optional[str]
    branch_id: Optional[int]
    branch_name: Optional[str]
    location_id: Optional[int]
    location_name: Optional[str]
    loan_id: Optional[int]
    date: Optional[str]
    deleted: bool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fmt_date(value) -> Optional[str]:
    return value.strftime("%Y-%m-%d") if value else None


def _gennis_user_name(db: Session, user_id: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    if not user_id:
        return None, None
    u = db.query(GennisUsers).filter(GennisUsers.id == user_id).first()
    if not u:
        return None, None
    return u.name, u.surname


def _turon_user_name(db: Session, user_id: Optional[int]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not user_id:
        return None, None, None
    u = db.query(TuronCustomUser).filter(TuronCustomUser.id == user_id).first()
    if not u:
        return None, None, None
    return u.name, u.surname, getattr(u, "phone", None)


# ── Serializers ───────────────────────────────────────────────────────────────


def _serialize_gennis_tx(tx: GennisBranchTransaction, db: Session) -> dict:
    pt = (
        db.query(GennisPaymentTypes).filter(GennisPaymentTypes.id == tx.payment_type_id).first()
        if tx.payment_type_id else None
    )
    loc = (
        db.query(GennisLocations).filter(GennisLocations.id == tx.location_id).first()
        if tx.location_id else None
    )
    day = (
        db.query(GennisCalendarDay).filter(GennisCalendarDay.id == tx.calendar_day).first()
        if tx.calendar_day else None
    )

    person_name, person_surname = _gennis_user_name(db, tx.person_id)
    person = {
        "id": tx.person_id,
        "name": person_name or tx.person_name,
        "surname": person_surname or tx.person_surname,
        "phone": tx.person_phone,
    }

    return {
        "source": "gennis",
        "id": tx.id,
        "management_id": tx.management_id,
        "amount": tx.amount,
        "is_give": bool(tx.is_give),
        "direction": "give" if tx.is_give else "receive",
        "reason": tx.reason,
        "person": person,
        "payment_type_id": tx.payment_type_id,
        "payment_type_name": pt.name if pt else None,
        "branch_id": None,
        "branch_name": None,
        "location_id": tx.location_id,
        "location_name": loc.name if loc else None,
        "loan_id": tx.loan_id,
        "date": _fmt_date(day.date) if day else None,
        "deleted": bool(tx.deleted),
    }


def _serialize_turon_tx(tx: TuronBranchTransaction, db: Session) -> dict:
    pt = (
        db.query(TuronPaymentTypes).filter(TuronPaymentTypes.id == tx.payment_type_id).first()
        if tx.payment_type_id else None
    )
    br = (
        db.query(TuronBranch).filter(TuronBranch.id == tx.branch_id).first()
        if tx.branch_id else None
    )

    person_name, person_surname, person_phone = _turon_user_name(db, tx.person_id)
    person = {
        "id": tx.person_id,
        "name": person_name or tx.person_name,
        "surname": person_surname or tx.person_surname,
        "phone": person_phone or tx.person_phone,
    }

    return {
        "source": "turon",
        "id": tx.id,
        "management_id": tx.management_id,
        "amount": tx.amount,
        "is_give": bool(tx.is_give),
        "direction": "give" if tx.is_give else "receive",
        "reason": tx.reason,
        "person": person,
        "payment_type_id": tx.payment_type_id,
        "payment_type_name": pt.name if pt else None,
        "branch_id": tx.branch_id,
        "branch_name": br.name if br else None,
        "location_id": None,
        "location_name": None,
        "loan_id": tx.loan_id,
        "date": _fmt_date(tx.date),
        "deleted": bool(tx.deleted),
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=List[BranchTransactionOut])
def list_branch_transactions(
    source: Optional[Source] = Query(None, description="Filter to one source: 'gennis' or 'turon'"),
    branch_id: Optional[int] = Query(None, description="Filter to one Turon branch"),
    location_id: Optional[int] = Query(None, description="Filter to one Gennis location"),
    loan_id: Optional[int] = Query(None, description="Filter to one loan (within source)"),
    is_give: Optional[bool] = Query(None, description="true = give/lent, false = receive"),
    include_deleted: bool = Query(False, description="Include soft-deleted rows"),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    if source == "gennis" and branch_id is not None:
        raise HTTPException(status_code=400, detail="branch_id does not apply to source=gennis (use location_id)")
    if source == "turon" and location_id is not None:
        raise HTTPException(status_code=400, detail="location_id does not apply to source=turon (use branch_id)")
    if loan_id is not None and source is None:
        raise HTTPException(status_code=400, detail="loan_id requires source (loan IDs are not unique across systems)")

    if source is not None:
        include_gennis = source == "gennis"
        include_turon = source == "turon"
    else:
        scope_to_turon = branch_id is not None and location_id is None
        scope_to_gennis = location_id is not None and branch_id is None
        include_gennis = not scope_to_turon
        include_turon = not scope_to_gennis

    rows: List[dict] = []

    if include_gennis:
        q = gennis_db.query(GennisBranchTransaction)
        if not include_deleted:
            q = q.filter(GennisBranchTransaction.deleted.is_(False))
        if location_id is not None:
            q = q.filter(GennisBranchTransaction.location_id == location_id)
        if loan_id is not None and source == "gennis":
            q = q.filter(GennisBranchTransaction.loan_id == loan_id)
        if is_give is not None:
            q = q.filter(GennisBranchTransaction.is_give == is_give)
        rows.extend(_serialize_gennis_tx(t, gennis_db) for t in q.order_by(GennisBranchTransaction.id.desc()).all())

    if include_turon:
        q = turon_db.query(TuronBranchTransaction)
        if not include_deleted:
            q = q.filter(TuronBranchTransaction.deleted.is_(False))
        if branch_id is not None:
            q = q.filter(TuronBranchTransaction.branch_id == branch_id)
        if loan_id is not None and source == "turon":
            q = q.filter(TuronBranchTransaction.loan_id == loan_id)
        if is_give is not None:
            q = q.filter(TuronBranchTransaction.is_give == is_give)
        rows.extend(_serialize_turon_tx(t, turon_db) for t in q.order_by(TuronBranchTransaction.id.desc()).all())

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


@router.get("/{source}/{tx_id}", response_model=BranchTransactionOut)
def get_branch_transaction(
    source: Source,
    tx_id: int,
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    if source == "gennis":
        tx = gennis_db.query(GennisBranchTransaction).filter(GennisBranchTransaction.id == tx_id).first()
        if not tx:
            raise HTTPException(status_code=404, detail="Gennis branch transaction not found")
        return _serialize_gennis_tx(tx, gennis_db)

    tx = turon_db.query(TuronBranchTransaction).filter(TuronBranchTransaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Turon branch transaction not found")
    return _serialize_turon_tx(tx, turon_db)
