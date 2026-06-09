import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_apple_token,
    verify_google_token,
    verify_password,
    verify_refresh_token,
)
from app.database import get_db, get_gennis_db, get_turon_db
from app.external_models.gennis import Users as GennisUsers
from app.external_models.turon import CustomUser as TuronUser
from app.mobile.schemas import (
    MobileAppleAuthRequest,
    MobileAuthResponse,
    MobileGoogleAuthRequest,
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

    # Werkzeug's legacy non-pbkdf2 format uses HMAC(salt, password, algo).
    try:
        digest = hmac.new(salt.encode("utf-8"), plain.encode("utf-8"), method_part).hexdigest()
    except (ValueError, LookupError):
        return False
    return hmac.compare_digest(digest, expected)


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
    """Return (user_row, stored_hash) for the Gennis DB by username.

    NULL `deleted` is treated as not-deleted (most rows in the legacy table
    were never backfilled to `false`). Newest id wins when the same username
    exists multiple times.
    """
    user = (
        gennis_db.query(GennisUsers)
        .filter(
            GennisUsers.username == username,
            or_(GennisUsers.deleted == False, GennisUsers.deleted.is_(None)),
        )
        .order_by(GennisUsers.id.desc())
        .first()
    )
    if not user:
        return None, None
    return user, getattr(user, "password", None)


def _lookup_turon(username: str, turon_db: Session) -> Tuple[Optional[object], Optional[str]]:
    """Return (user_row, stored_hash) for the Turon DB by username or phone.

    Most staff log in with a Django username; legacy clients used phone.
    """
    user = (
        turon_db.query(TuronUser)
        .filter(
            or_(TuronUser.username == username, TuronUser.phone == username),
            or_(TuronUser.is_active == True, TuronUser.is_active.is_(None)),
        )
        .order_by(TuronUser.id.desc())
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


@router.post("/google", response_model=MobileAuthResponse)
def mobile_google_auth(
    payload: MobileGoogleAuthRequest,
    db: Session = Depends(get_db),
):
    """Sign in (or auto-register) a management user from a Google ID token.

    Mirrors the web `/auth/google` flow but returns the mobile token shape.
    Gennis and Turon users are not supported here — Google identities only
    map to the management system, which is the only one keyed by email.
    """
    try:
        info = verify_google_token(payload.token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email not provided by Google",
        )

    google_id = info.get("sub")
    picture = info.get("picture")
    email_verified = info.get("email_verified", "false") == "true"

    given_name = (info.get("given_name") or "").strip()
    family_name = (info.get("family_name") or "").strip()
    full_name = (info.get("name") or "").strip()
    if not given_name and not family_name and full_name:
        parts = full_name.split(None, 1)
        given_name = parts[0]
        family_name = parts[1] if len(parts) > 1 else ""

    user = db.query(models.User).filter(models.User.email == email).first()
    now = datetime.utcnow()
    if user:
        if not (user.name or "").strip() and given_name:
            user.name = given_name
        if not (user.surname or "").strip() and family_name:
            user.surname = family_name
        user.google_id = google_id
        user.profile_photo_url = picture
        user.is_verified = email_verified
        user.last_login = now
        user.updated_at = now
        if user.auth_provider == "email":
            user.auth_provider = "google"
    else:
        user = models.User(
            name=given_name or "User",
            surname=family_name,
            email=email,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            auth_provider="google",
            google_id=google_id,
            profile_photo_url=picture,
            is_verified=email_verified,
            timezone="Asia/Tashkent",
            is_active=True,
            last_login=now,
        )
        db.add(user)
    db.commit()
    db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    token_claims = {
        "sub": f"management:{user.id}",
        "system": "management",
        "external_id": user.id,
        "management_user_id": user.id,
        "name": f"{user.name or ''} {user.surname or ''}".strip() or None,
        "role": user.role,
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
            id=user.id,
            system="management",
            name=user.name,
            surname=user.surname,
            role=user.role,
        ),
    )


@router.post("/apple", response_model=MobileAuthResponse)
def mobile_apple_auth(
    payload: MobileAppleAuthRequest,
    db: Session = Depends(get_db),
):
    """Sign in a management staff user from an Apple identity token.

    Required by App Store Guideline 4.8 (apps offering third-party login must
    also offer Sign in with Apple). The iOS app runs native Sign in with Apple,
    receives an `identityToken`, and sends it here. We verify the token against
    Apple's public keys, then match the email to an existing staff account.

    Unlike `/auth/google`, no auto-registration: an unmatched email returns
    401. This mirrors the spec's "EXISTING staff user" rule — the org app has
    no self-signup surface, so any new staff must be created by an admin
    first. (Apple Private Relay emails will not match by definition; that's a
    known trade-off and is documented in the spec.)
    """
    try:
        claims = verify_apple_token(payload.token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    # Apple omits `email` on returning sign-ins; fall back to what the iOS app
    # forwarded from the first authorization, if anything.
    email = (claims.get("email") or payload.email or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Apple token did not provide an email and none was forwarded",
        )

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No staff account is linked to this Apple ID",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    now = datetime.utcnow()
    # Backfill name from Apple's first-auth payload if missing on the staff
    # record; do not overwrite an admin-curated name.
    forwarded_name = (payload.name or "").strip()
    if forwarded_name and not (user.name or "").strip():
        parts = forwarded_name.split(None, 1)
        user.name = parts[0]
        if len(parts) > 1 and not (user.surname or "").strip():
            user.surname = parts[1]
    if claims.get("email_verified") in ("true", True):
        user.is_verified = True
    user.last_login = now
    user.updated_at = now
    if user.auth_provider == "email":
        user.auth_provider = "apple"
    db.commit()
    db.refresh(user)

    token_claims = {
        "sub": f"management:{user.id}",
        "system": "management",
        "external_id": user.id,
        "management_user_id": user.id,
        "name": f"{user.name or ''} {user.surname or ''}".strip() or None,
        "role": user.role,
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
            id=user.id,
            system="management",
            name=user.name,
            surname=user.surname,
            role=user.role,
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
            .filter(
                GennisUsers.id == external_id,
                or_(GennisUsers.deleted == False, GennisUsers.deleted.is_(None)),
            )
            .first()
        )
        if user:
            name, surname = user.name, user.surname
        management_user_id = None
    else:
        user = (
            turon_db.query(TuronUser)
            .filter(
                TuronUser.id == external_id,
                or_(TuronUser.is_active == True, TuronUser.is_active.is_(None)),
            )
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
