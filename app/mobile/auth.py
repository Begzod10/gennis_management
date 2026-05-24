import hashlib
import hmac
from datetime import timedelta
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_refresh_token,
)
from app.database import get_db, get_gennis_db, get_turon_db
from app.external_models.gennis import Users as GennisUsers
from app.external_models.turon import CustomUser as TuronUser
from app.mobile.schemas import (
    MobileAuthResponse,
    MobileLoginRequest,
    MobileRefreshRequest,
    MobileUserOut,
    SystemLiteral,
)


router = APIRouter(prefix="/mobile/auth", tags=["Mobile - Auth"])


# Multi-scheme verifier for external sources. Gennis/Turon store password
# hashes in their own format (Flask app + Django app respectively); passlib
# auto-detects the scheme from the hash prefix and falls through if unknown.
# Note: Werkzeug's `pbkdf2:sha256:N$salt$hash` format is not natively
# supported here — if Gennis uses that format you will need a small custom
# verifier; the bcrypt and django_pbkdf2_sha256 schemes cover the common case.
external_pwd_context = CryptContext(
    schemes=[
        "bcrypt",
        "django_pbkdf2_sha256",
        "pbkdf2_sha256",
    ],
    deprecated="auto",
)


def _verify_werkzeug(plain: str, hashed: str) -> bool:
    """Verify a Werkzeug-style hash (`method$salt$hex` or `method:iters$salt$hex`).

    Covers the two formats Flask apps actually produce:
      * `sha256$<salt>$<hex>`            — single-pass salted SHA-256
      * `pbkdf2:sha256:<iters>$<salt>$<hex>` — Werkzeug's modern default
    """
    try:
        method_part, salt, expected = hashed.split("$", 2)
    except ValueError:
        return False

    if method_part.startswith("pbkdf2:"):
        _, algo, iters_str = method_part.split(":")
        try:
            iters = int(iters_str)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac(algo, plain.encode("utf-8"), salt.encode("utf-8"), iters)
        return hmac.compare_digest(digest.hex(), expected)

    # plain algo like "sha256", "sha1", "md5"
    try:
        h = hashlib.new(method_part)
    except (ValueError, LookupError):
        return False
    h.update(salt.encode("utf-8"))
    h.update(plain.encode("utf-8"))
    return hmac.compare_digest(h.hexdigest(), expected)


def _verify_external(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    # Werkzeug formats (`sha256$...`, `pbkdf2:sha256:...$...`) are not
    # recognised by passlib, so try the custom verifier first.
    if "$" in hashed and not hashed.startswith("$"):
        prefix = hashed.split("$", 1)[0]
        if prefix.startswith(("pbkdf2:", "sha", "md5")):
            return _verify_werkzeug(plain, hashed)
    try:
        return external_pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


# ── Per-system credential lookup ─────────────────────────────────────────────

def _lookup_management(username: str, db: Session) -> Tuple[Optional[object], Optional[str]]:
    """Return (user_row, stored_hash) for the management DB by email."""
    user = db.query(models.User).filter(models.User.email == username).first()
    if not user:
        return None, None
    return user, user.hashed_password


def _lookup_gennis(username: str, gennis_db: Session) -> Tuple[Optional[object], Optional[str]]:
    """Return (user_row, stored_hash) for the Gennis DB by username."""
    user = (
        gennis_db.query(GennisUsers)
        .filter(GennisUsers.username == username, GennisUsers.deleted == False)
        .first()
    )
    if not user:
        return None, None
    # `Users` model in external_models doesn't currently map a password column.
    # We pull it lazily via raw attribute access so we don't have to alter the
    # schema mapping just for this. If `password` is not mapped, this returns
    # None and verification will fail cleanly.
    return user, getattr(user, "password", None)


def _lookup_turon(username: str, turon_db: Session) -> Tuple[Optional[object], Optional[str]]:
    """Return (user_row, stored_hash) for the Turon DB by phone."""
    user = (
        turon_db.query(TuronUser)
        .filter(TuronUser.phone == username, TuronUser.is_active == True)
        .first()
    )
    if not user:
        return None, None
    return user, getattr(user, "password", None)


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=MobileAuthResponse)
def mobile_login(
    payload: MobileLoginRequest,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    """Login against the system the user belongs to.

    The mobile client picks `system` on its login screen and submits the
    matching identifier (email / username / phone) together with the plain
    password. Management uses bcrypt via the existing helper; Gennis and
    Turon are verified through a multi-scheme `passlib` context.
    """
    system: SystemLiteral = payload.system

    if system == "management":
        user, hashed = _lookup_management(payload.username, db)
        verified = bool(hashed) and verify_password(payload.password, hashed)
        if not user or not verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        external_id = user.id
        management_user_id = user.id
        name = user.name
        surname = user.surname
        role = user.role

    elif system == "gennis":
        user, hashed = _lookup_gennis(payload.username, gennis_db)
        if not user or not _verify_external(payload.password, hashed):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        external_id = user.id
        management_user_id = None
        name = user.name
        surname = user.surname
        role = None

    else:  # turon
        user, hashed = _lookup_turon(payload.username, turon_db)
        if not user or not _verify_external(payload.password, hashed):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        external_id = user.id
        management_user_id = None
        name = user.name
        surname = user.surname
        role = None

    token_claims = {
        "sub": f"{system}:{external_id}",
        "system": system,
        "external_id": external_id,
        "management_user_id": management_user_id,
        "name": f"{name or ''} {surname or ''}".strip() or None,
        "role": role,
    }

    access_token = create_access_token(
        data=token_claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data=token_claims)

    return MobileAuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=MobileUserOut(
            id=external_id,
            system=system,
            name=name,
            surname=surname,
            role=role,
        ),
    )


@router.post("/refresh", response_model=MobileAuthResponse)
def mobile_refresh(
    payload: MobileRefreshRequest,
    db: Session = Depends(get_db),
    gennis_db: Session = Depends(get_gennis_db),
    turon_db: Session = Depends(get_turon_db),
):
    """Exchange a valid refresh token for a fresh access token.

    Validates the refresh token, re-loads the user from the source DB to pick
    up any name/role changes, and re-issues both tokens (rotation). If the
    user has been deactivated or deleted since the refresh token was minted,
    the request is rejected.
    """
    try:
        claims = verify_refresh_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    system = claims.get("system")
    external_id = claims.get("external_id")
    if system not in {"management", "gennis", "turon"} or not isinstance(external_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing system / external_id",
        )

    user = None
    role = None
    name: Optional[str] = None
    surname: Optional[str] = None
    if system == "management":
        user = db.query(models.User).filter(models.User.id == external_id).first()
        if user and not user.is_active:
            user = None
        if user:
            name, surname, role = user.name, user.surname, user.role
        management_user_id = user.id if user else None
    elif system == "gennis":
        user = (
            gennis_db.query(GennisUsers)
            .filter(GennisUsers.id == external_id, GennisUsers.deleted == False)
            .first()
        )
        if user:
            name, surname = user.name, user.surname
        management_user_id = None
    else:
        user = (
            turon_db.query(TuronUser)
            .filter(TuronUser.id == external_id, TuronUser.is_active == True)
            .first()
        )
        if user:
            name, surname = user.name, user.surname
        management_user_id = None

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer active",
        )

    token_claims = {
        "sub": f"{system}:{external_id}",
        "system": system,
        "external_id": external_id,
        "management_user_id": management_user_id,
        "name": f"{name or ''} {surname or ''}".strip() or None,
        "role": role,
    }
    access_token = create_access_token(
        data=token_claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    new_refresh_token = create_refresh_token(data=token_claims)

    return MobileAuthResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=MobileUserOut(
            id=external_id,
            system=system,
            name=name,
            surname=surname,
            role=role,
        ),
    )
