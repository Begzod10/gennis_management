"""Mobile profile endpoints — `/mobile/me`.

The shape of "me" depends on which system the caller logged in from:
  * management → email / role / telegram_id
  * gennis     → username
  * turon      → phone

Updates are scoped to each system's user row. Password changes preserve the
source-system's hash scheme so the user can still log in via the native
Flask (Gennis) or Django (Turon) UIs after rotating their password here.
"""
import base64
import hashlib
import hmac
import os
import secrets
import string
from typing import Optional


_SALT_ALPHABET = string.ascii_letters + string.digits  # what Django's get_random_string uses by default


def _random_salt(length: int) -> str:
    return "".join(secrets.choice(_SALT_ALPHABET) for _ in range(length))

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_password_hash, verify_password
from app.database import (
    get_db,
    get_gennis_db,
    get_gennis_write_db,
    get_turon_db,
    get_turon_write_db,
)
from app.external_models.gennis import Users as GennisUsers
from app.external_models.turon import CustomUser as TuronUser
from app.mobile.auth import _verify_external
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import (
    MobileIdentity,
    MobileMeOut,
    MobileMeUpdate,
    MobilePasswordChange,
)
from app.mobile.telegram import _lookup_telegram_id


router = APIRouter(prefix="/mobile/me", tags=["Mobile - Me"])


# ── Password hashers (per source system) ─────────────────────────────────────
#
# Each external system reads back hashes in its native format from its own UI,
# so when the mobile app rotates a password we must encode it the same way
# the native app would. Otherwise the user gets locked out of the source app.

_PBKDF2_ITERS = 600_000  # match Werkzeug / Django current defaults


def _hash_werkzeug(password: str) -> str:
    """Produce `pbkdf2:sha256:<iters>$<salt>$<hex>` — what Flask/Werkzeug writes.

    Werkzeug's `gen_salt` uses an alphanumeric alphabet; mirror that so the
    `$`-delimited format is unambiguous when re-parsed.
    """
    salt = _random_salt(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERS}${salt}${digest.hex()}"


def _hash_django(password: str) -> str:
    """Produce `pbkdf2_sha256$<iters>$<salt>$<b64>` — Django's default.

    Django's `get_random_string` defaults to an alphanumeric alphabet, and
    passlib's `django_pbkdf2_sha256` parser rejects salts containing `-` or
    other non-alnum characters, so don't use `secrets.token_urlsafe`.
    """
    salt = _random_salt(12)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt}${base64.b64encode(digest).decode('ascii').strip()}"


# ── /me ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=MobileMeOut)
def get_me(
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    if identity.system == "management":
        u = db.query(models.User).filter(models.User.id == identity.external_id).first()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        return MobileMeOut(
            id=u.id, system="management",
            name=u.name, surname=u.surname, email=u.email,
            phone=None, username=None, role=u.role,
            telegram_linked=u.telegram_id is not None, telegram_id=u.telegram_id,
        )
    if identity.system == "gennis":
        u = gennis_db.query(GennisUsers).filter(GennisUsers.id == identity.external_id).first()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        tg = _lookup_telegram_id(identity, db)
        return MobileMeOut(
            id=u.id, system="gennis",
            name=u.name, surname=u.surname,
            email=None, phone=None,
            username=u.username, role=None,
            telegram_linked=tg is not None, telegram_id=tg,
        )
    u = turon_db.query(TuronUser).filter(TuronUser.id == identity.external_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    tg = _lookup_telegram_id(identity, db)
    return MobileMeOut(
        id=u.id, system="turon",
        name=u.name, surname=u.surname,
        email=None, phone=u.phone,
        username=None, role=None,
        telegram_linked=tg is not None, telegram_id=tg,
    )


@router.patch("", response_model=MobileMeOut)
def update_me(
    data: MobileMeUpdate,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Partially update the caller's own profile fields.

    Each system exposes a different subset of editable fields — extra fields
    in the payload are silently ignored for that system rather than 422'd, so
    a mobile client can send a single PATCH shape against any backend.
    """
    payload = data.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")

    if identity.system == "management":
        u = db.query(models.User).filter(models.User.id == identity.external_id).first()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        for field in ("name", "surname", "email"):
            if field in payload:
                setattr(u, field, payload[field])
        db.commit()
        db.refresh(u)
        return MobileMeOut(
            id=u.id, system="management",
            name=u.name, surname=u.surname, email=u.email,
            phone=None, username=None, role=u.role,
            telegram_linked=u.telegram_id is not None, telegram_id=u.telegram_id,
        )

    if identity.system == "gennis":
        u = gennis_db.query(GennisUsers).filter(GennisUsers.id == identity.external_id).first()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        for field in ("name", "surname"):
            if field in payload:
                setattr(u, field, payload[field])
        gennis_db.commit()
        gennis_db.refresh(u)
        tg = _lookup_telegram_id(identity, db)
        return MobileMeOut(
            id=u.id, system="gennis",
            name=u.name, surname=u.surname,
            email=None, phone=None,
            username=u.username, role=None,
            telegram_linked=tg is not None, telegram_id=tg,
        )

    u = turon_db.query(TuronUser).filter(TuronUser.id == identity.external_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    for field in ("name", "surname", "phone"):
        if field in payload:
            setattr(u, field, payload[field])
    turon_db.commit()
    turon_db.refresh(u)
    tg = _lookup_telegram_id(identity, db)
    return MobileMeOut(
        id=u.id, system="turon",
        name=u.name, surname=u.surname,
        email=None, phone=u.phone,
        username=None, role=None,
        telegram_linked=tg is not None, telegram_id=tg,
    )


@router.post("/change-password", status_code=204)
def change_password(
    data: MobilePasswordChange,
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_write_db),
    turon_db: Session = Depends(get_turon_write_db),
):
    """Change the caller's password.

    Verifies the current password using each system's native scheme, then
    writes the new hash in the SAME scheme so the user can still log in via
    the source-system's native UI.
    """
    if identity.system == "management":
        u = db.query(models.User).filter(models.User.id == identity.external_id).first()
        if not u or not u.hashed_password or not verify_password(data.current_password, u.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
        u.hashed_password = get_password_hash(data.new_password)
        db.commit()
        return

    if identity.system == "gennis":
        u = gennis_db.query(GennisUsers).filter(GennisUsers.id == identity.external_id).first()
        if not u or not _verify_external(data.current_password, getattr(u, "password", None)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
        u.password = _hash_werkzeug(data.new_password)
        gennis_db.commit()
        return

    u = turon_db.query(TuronUser).filter(TuronUser.id == identity.external_id).first()
    if not u or not _verify_external(data.current_password, getattr(u, "password", None)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    u.password = _hash_django(data.new_password)
    turon_db.commit()
