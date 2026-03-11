from datetime import datetime, timedelta, timezone
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
    """Verify a Google ID token by calling Google's tokeninfo endpoint."""
    with httpx.Client() as client:
        resp = client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
        )

    if resp.status_code != 200:
        raise ValueError("Invalid or expired Google token")

    info = resp.json()

    # Validate audience matches our client ID
    if settings.GOOGLE_CLIENT_ID and info.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise ValueError("Token audience mismatch")

    return info
