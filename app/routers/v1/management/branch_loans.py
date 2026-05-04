from datetime import date as dt_date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import (
    get_db,
    get_gennis_write_db,
    get_turon_write_db,
)
from app.external_models.gennis import GennisBranchLoan
from app.external_models.turon import TuronBranchLoan
from app.models import BranchLoan
from app.schemas import (
    BranchLoanCancel,
    BranchLoanCreate,
    BranchLoanOut,
    BranchLoanRepay,
    BranchLoanUpdate,
)

router = APIRouter(prefix="/branch-loans", tags=["Branch Loans"])


# ── Sync helpers ──────────────────────────────────────────────────────────────


def _sync_to_gennis(loan: BranchLoan, gennis_db: Session) -> None:
    """Push management BranchLoan into Gennis branch_loan table."""
    if loan.source != "gennis" or not loan.location_id:
        return

    existing = (
        gennis_db.query(GennisBranchLoan)
        .filter(GennisBranchLoan.management_id == loan.id)
        .first()
    )

    payload = {
        "location_id": loan.location_id,
        "counterparty_id": loan.counterparty_user_id,
        "counterparty_name": loan.counterparty_name,
        "counterparty_surname": loan.counterparty_surname,
        "counterparty_phone": loan.counterparty_phone,
        "direction": loan.direction,
        "principal_amount": loan.principal_amount,
        "issued_date": loan.issued_date,
        "due_date": loan.due_date,
        "settled_date": loan.settled_date,
        "reason": loan.reason,
        "notes": loan.notes,
        "status": loan.status,
        "cancelled_reason": loan.cancelled_reason,
        "deleted": loan.deleted,
    }

    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
    else:
        gennis_db.add(GennisBranchLoan(management_id=loan.id, **payload))

    gennis_db.commit()


def _sync_to_turon(loan: BranchLoan, turon_db: Session) -> None:
    """Push management BranchLoan into Turon branch_branchloan table."""
    if loan.source != "turon" or not loan.branch_id:
        return

    existing = (
        turon_db.query(TuronBranchLoan)
        .filter(TuronBranchLoan.management_id == loan.id)
        .first()
    )

    payload = {
        "branch_id": loan.branch_id,
        "counterparty_id": loan.counterparty_user_id,
        "counterparty_name": loan.counterparty_name,
        "counterparty_surname": loan.counterparty_surname,
        "counterparty_phone": loan.counterparty_phone,
        "direction": loan.direction,
        "principal_amount": loan.principal_amount,
        "issued_date": loan.issued_date,
        "due_date": loan.due_date,
        "settled_date": loan.settled_date,
        "reason": loan.reason,
        "notes": loan.notes,
        "status": loan.status,
        "cancelled_reason": loan.cancelled_reason,
        "deleted": loan.deleted,
    }

    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
    else:
        turon_db.add(TuronBranchLoan(management_id=loan.id, **payload))

    turon_db.commit()


def _sync_delete(loan: BranchLoan, gennis_db: Session, turon_db: Session) -> None:
    """Mark the linked external row as cancelled (audit-friendly soft delete)."""
    if loan.source == "gennis":
        row = (
            gennis_db.query(GennisBranchLoan)
            .filter(GennisBranchLoan.management_id == loan.id)
            .first()
        )
        if row:
            row.status = "cancelled"
            row.deleted = True
            gennis_db.commit()
    elif loan.source == "turon":
        row = (
            turon_db.query(TuronBranchLoan)
            .filter(TuronBranchLoan.management_id == loan.id)
            .first()
        )
        if row:
            row.status = "cancelled"
            row.deleted = True
            turon_db.commit()


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_target(payload: BranchLoanCreate) -> None:
    if payload.source == "gennis" and not payload.location_id:
        raise HTTPException(status_code=400, detail="location_id is required when source='gennis'")
    if payload.source == "turon" and not payload.branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required when source='turon'")
    if payload.principal_amount <= 0:
        raise HTTPException(status_code=400, detail="principal_amount must be > 0")
    if payload.counterparty_user_id and payload.counterparty_name:
        raise HTTPException(status_code=400, detail="Provide counterparty_user_id OR counterparty_name, not both")
    if not payload.counterparty_user_id and not payload.counterparty_name:
        raise HTTPException(status_code=400, detail="counterparty_user_id or counterparty_name is required")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=List[BranchLoanOut])
def list_loans(
    source: Optional[str] = Query(None, regex="^(gennis|turon)$"),
    location_id: Optional[int] = Query(None),
    branch_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, regex="^(active|settled|cancelled)$"),
    direction: Optional[str] = Query(None, regex="^(out|in)$"),
    counterparty_user_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(BranchLoan).filter(BranchLoan.deleted.is_(False))
    if source:
        q = q.filter(BranchLoan.source == source)
    if location_id is not None:
        q = q.filter(BranchLoan.location_id == location_id)
    if branch_id is not None:
        q = q.filter(BranchLoan.branch_id == branch_id)
    if status:
        q = q.filter(BranchLoan.status == status)
    if direction:
        q = q.filter(BranchLoan.direction == direction)
    if counterparty_user_id is not None:
        q = q.filter(BranchLoan.counterparty_user_id == counterparty_user_id)

    return q.order_by(BranchLoan.id.desc()).all()


@router.get("/{loan_id}", response_model=BranchLoanOut)
def get_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = (
        db.query(BranchLoan)
        .filter(BranchLoan.id == loan_id, BranchLoan.deleted.is_(False))
        .first()
    )
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    return loan


@router.post("", response_model=BranchLoanOut, status_code=201)
def create_loan(
    payload: BranchLoanCreate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    _validate_target(payload)

    loan = BranchLoan(
        source=payload.source.value,
        location_id=payload.location_id,
        branch_id=payload.branch_id,
        counterparty_user_id=payload.counterparty_user_id,
        counterparty_name=payload.counterparty_name,
        counterparty_surname=payload.counterparty_surname,
        counterparty_phone=payload.counterparty_phone,
        direction=payload.direction.value,
        principal_amount=payload.principal_amount,
        payment_type=payload.payment_type,
        issued_date=payload.issued_date,
        due_date=payload.due_date,
        reason=payload.reason,
        notes=payload.notes,
        status="active",
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)

    _sync_to_gennis(loan, gennis_db)
    _sync_to_turon(loan, turon_db)

    return loan


@router.patch("/{loan_id}", response_model=BranchLoanOut)
def update_loan(
    loan_id: int,
    payload: BranchLoanUpdate,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    loan = (
        db.query(BranchLoan)
        .filter(BranchLoan.id == loan_id, BranchLoan.deleted.is_(False))
        .first()
    )
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cancelled loan cannot be updated")

    if payload.due_date is not None:
        loan.due_date = payload.due_date
    if payload.reason is not None:
        loan.reason = payload.reason
    if payload.notes is not None:
        loan.notes = payload.notes

    db.commit()
    db.refresh(loan)

    _sync_to_gennis(loan, gennis_db)
    _sync_to_turon(loan, turon_db)

    return loan


@router.post("/{loan_id}/settle", response_model=BranchLoanOut)
def mark_settled(
    loan_id: int,
    settled_date: Optional[dt_date] = None,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Mark a loan as fully settled at the management level. The actual cash
    transactions live in the source project (Gennis/Turon). This endpoint just
    flips status — useful when an out-of-band settlement happens (e.g. write-off
    or external clearance)."""
    loan = (
        db.query(BranchLoan)
        .filter(BranchLoan.id == loan_id, BranchLoan.deleted.is_(False))
        .first()
    )
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cancelled loan cannot be settled")

    loan.status = "settled"
    loan.settled_date = settled_date or dt_date.today()
    db.commit()
    db.refresh(loan)

    _sync_to_gennis(loan, gennis_db)
    _sync_to_turon(loan, turon_db)

    return loan


@router.post("/{loan_id}/cancel", response_model=BranchLoanOut)
def cancel_loan(
    loan_id: int,
    payload: BranchLoanCancel,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    loan = (
        db.query(BranchLoan)
        .filter(BranchLoan.id == loan_id, BranchLoan.deleted.is_(False))
        .first()
    )
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    loan.status = "cancelled"
    loan.cancelled_reason = payload.cancelled_reason
    loan.settled_date = None
    db.commit()
    db.refresh(loan)

    _sync_to_gennis(loan, gennis_db)
    _sync_to_turon(loan, turon_db)

    return loan


@router.delete("/{loan_id}", status_code=204)
def delete_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    loan = (
        db.query(BranchLoan)
        .filter(BranchLoan.id == loan_id, BranchLoan.deleted.is_(False))
        .first()
    )
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    loan.deleted = True
    loan.status = "cancelled"
    db.commit()

    _sync_delete(loan, gennis_db, turon_db)
    return None
