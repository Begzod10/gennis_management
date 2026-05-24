from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.config import settings
from app.mobile.schemas import MobileIdentity


mobile_oauth_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/mobile/auth/login")


def get_mobile_identity(token: str = Depends(mobile_oauth_scheme)) -> MobileIdentity:
    """Decode the mobile JWT and return the caller's system + external id.

    Mobile tokens are signed with the same secret as the regular management
    JWTs (we reuse the existing `SECRET_KEY` / `ALGORITHM`) but carry an
    additional `system` claim. Tokens without `system` are rejected so that
    a stolen management web token cannot be replayed against the mobile
    surface.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    system = payload.get("system")
    external_id = payload.get("external_id")
    if system not in {"management", "gennis", "turon"} or not isinstance(external_id, int):
        raise credentials_exception

    return MobileIdentity(
        system=system,
        external_id=external_id,
        management_user_id=payload.get("management_user_id"),
        name=payload.get("name"),
        role=payload.get("role"),
    )
