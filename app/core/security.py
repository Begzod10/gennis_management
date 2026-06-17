import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ── Access token --------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return payload
    except JWTError as e:
        raise ValueError(str(e))


# ── Refresh token -------------------------------------------------------------

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc).timestamp(),
        "type": "refresh",
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("Not a refresh token")
        return payload
    except JWTError as e:
        raise ValueError(str(e))


# ── Google token --------------------------------------------------------------

def verify_google_token(id_token: str) -> dict:
    """Verify a Google ID token by calling Google's tokeninfo endpoint.

    Accepts tokens issued for any of our configured OAuth clients (web +
    each mobile platform). Tokens whose `aud` claim is outside that set are
    rejected, even if otherwise valid.
    """
    with httpx.Client(trust_env=False, timeout=10.0) as client:
        resp = client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
        )

    if resp.status_code != 200:
        raise ValueError("Invalid or expired Google token")

    info = resp.json()

    allowed = {cid.strip() for cid in (
        settings.GOOGLE_CLIENT_ID,
        settings.MOBILE_CLIENT_ID,
        *settings.GOOGLE_ALLOWED_CLIENT_IDS.split(","),
    ) if cid and cid.strip()}
    if allowed and info.get("aud") not in allowed:
        raise ValueError("Token audience mismatch")

    return info


# ── Apple token --------------------------------------------------------------

_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"
_APPLE_JWKS_TTL_SECONDS = 3600

_apple_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_apple_jwks_lock = Lock()


def _fetch_apple_jwks(force: bool = False) -> list:
    """Fetch Apple's JWKS, caching in-process for an hour.

    Apple rotates signing keys but slowly; a one-hour TTL avoids hammering
    `appleid.apple.com` on every login while still picking up rotations.
    `force=True` bypasses the cache, used as a single retry when a token's
    `kid` is unknown (likely a freshly rotated key).
    """
    now = time.time()
    if not force and _apple_jwks_cache["keys"] is not None and (
        now - _apple_jwks_cache["fetched_at"] < _APPLE_JWKS_TTL_SECONDS
    ):
        return _apple_jwks_cache["keys"]

    with _apple_jwks_lock:
        now = time.time()
        if not force and _apple_jwks_cache["keys"] is not None and (
            now - _apple_jwks_cache["fetched_at"] < _APPLE_JWKS_TTL_SECONDS
        ):
            return _apple_jwks_cache["keys"]

        with httpx.Client(trust_env=False, timeout=10.0) as client:
            resp = client.get(_APPLE_JWKS_URL)
        if resp.status_code != 200:
            raise ValueError("Unable to fetch Apple public keys")
        keys = resp.json().get("keys") or []
        _apple_jwks_cache["keys"] = keys
        _apple_jwks_cache["fetched_at"] = time.time()
        return keys


def _apple_key_for_kid(kid: str, *, allow_refresh: bool = True) -> Optional[dict]:
    keys = _fetch_apple_jwks()
    for key in keys:
        if key.get("kid") == kid:
            return key
    if allow_refresh:
        keys = _fetch_apple_jwks(force=True)
        for key in keys:
            if key.get("kid") == kid:
                return key
    return None


def verify_apple_token(identity_token: str) -> dict:
    """Verify an Apple Sign In identity token against Apple's public keys.

    Returns the decoded claims (`sub`, `email`, `email_verified`, ...) on
    success and raises `ValueError` with a short reason on any failure
    (bad signature, wrong issuer/audience, expired, no matching key).

    `aud` must match `APPLE_ALLOWED_CLIENT_IDS` (for the native iOS app this
    is the bundle id, e.g. `uz.gennis.todo`).
    """
    if not identity_token:
        raise ValueError("Missing Apple identity token")

    try:
        header = jwt.get_unverified_header(identity_token)
    except JWTError as exc:
        raise ValueError(f"Malformed Apple token: {exc}")

    kid = header.get("kid")
    if not kid:
        raise ValueError("Apple token missing 'kid' header")

    jwk = _apple_key_for_kid(kid)
    if jwk is None:
        raise ValueError("Apple signing key not found for token 'kid'")

    allowed = {cid.strip() for cid in settings.APPLE_ALLOWED_CLIENT_IDS.split(",") if cid and cid.strip()}
    if not allowed:
        raise ValueError("APPLE_ALLOWED_CLIENT_IDS is not configured")

    try:
        claims = jwt.decode(
            identity_token,
            jwk,
            algorithms=["RS256"],
            audience=list(allowed) if len(allowed) > 1 else next(iter(allowed)),
            issuer=_APPLE_ISSUER,
            options={"require_exp": True, "require_iat": False},
        )
    except JWTError as exc:
        raise ValueError(f"Invalid Apple token: {exc}")

    if "sub" not in claims:
        raise ValueError("Apple token missing 'sub' claim")

    return claims
