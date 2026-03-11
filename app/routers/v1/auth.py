import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
import re

from app import models
from app.database import get_db
from app.dependencies import get_current_user
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    verify_google_token
)
from app.config import settings

router = APIRouter(
    prefix="/auth",
    tags=["authentication"]
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ========== SCHEMAS ==========

class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    timezone: str = Field(default="Asia/Tashkent")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    token: str = Field(..., description="Google ID token from frontend")


class UserData(BaseModel):
    id: int
    name: str
    email: str
    timezone: str
    profile_photo_url: Optional[str] = None
    is_verified: bool
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserData


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


# ========== HELPER FUNCTIONS ==========

def validate_password_strength(password: str) -> bool:
    """Validate password meets security requirements"""
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True


# ========== ENDPOINTS ==========

@router.post('/register', response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register a new user with email and password"""

    # Check if email already exists
    existing_user = db.query(models.User).filter(
        models.User.email == user_data.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Validate password strength
    if not validate_password_strength(user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters and contain uppercase, lowercase, and numbers"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)

    new_user = models.User(
        name=user_data.name,
        email=user_data.email,
        hashed_password=hashed_password,
        timezone=user_data.timezone,
        auth_provider="email",
        is_active=True,
        is_verified=False,
        failed_login_attempts=0
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Generate tokens
    token_data = {"sub": new_user.email, "user_id": new_user.id}
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(data=token_data)

    user_response = UserData(
        id=new_user.id,
        name=new_user.name,
        email=new_user.email,
        timezone=new_user.timezone,
        profile_photo_url=new_user.profile_photo_url,
        is_verified=new_user.is_verified,
        created_at=new_user.created_at.isoformat() if new_user.created_at else None
    )

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response
    )


@router.post('/login', response_model=AuthResponse)
def login(
        login_data: UserLogin,
        db: Session = Depends(get_db)
):
    """Login with email and password"""

    user = db.query(models.User).filter(
        models.User.email == login_data.email
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    # Reset expired lockout before checking
    if user.locked_until and user.locked_until <= datetime.utcnow():
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()

    # Check if account is still locked
    if user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is locked due to too many failed login attempts. Please try again later."
        )

    # Check if user registered with Google (no password)
    if user.auth_provider == "google" and not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account was created with Google. Please use Google Sign-In."
        )

    # Verify password
    if not verify_password(login_data.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reset failed login attempts on successful login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    # Generate tokens
    token_data = {"sub": user.email, "user_id": user.id}
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(data=token_data)

    user_response = UserData(
        id=user.id,
        name=user.name,
        email=user.email,
        timezone=user.timezone,
        profile_photo_url=user.profile_photo_url,
        is_verified=user.is_verified,
        created_at=user.created_at.isoformat() if user.created_at else None
    )

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response
    )


@router.post('/google', response_model=AuthResponse)
def google_auth(auth_request: GoogleAuthRequest, db: Session = Depends(get_db)):
    """Authenticate with Google OAuth"""
    try:
        # Verify Google token
        google_user_info = verify_google_token(auth_request.token)

        email = google_user_info.get('email')
        name = google_user_info.get('name')
        google_id = google_user_info.get('sub')
        picture = google_user_info.get('picture')
        email_verified = google_user_info.get('email_verified', 'false') == 'true'

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by Google"
            )

        # Check if user exists
        user = db.query(models.User).filter(models.User.email == email).first()

        if user:
            # Update existing user
            user.name = name or user.name
            user.google_id = google_id
            user.profile_photo_url = picture
            user.is_verified = email_verified
            user.last_login = datetime.utcnow()
            user.updated_at = datetime.utcnow()

            # If user was created with email but now using Google, update auth_provider
            if user.auth_provider == "email":
                user.auth_provider = "google"
        else:
            # Create new Google user with a random unusable password
            random_password = secrets.token_urlsafe(32)

            user = models.User(
                name=name or "User",
                surname="",
                email=email,
                hashed_password=get_password_hash(random_password),
                auth_provider="google",
                google_id=google_id,
                profile_photo_url=picture,
                is_verified=email_verified,
                timezone="Asia/Tashkent",
                is_active=True,
                last_login=datetime.utcnow()
            )
            db.add(user)
        db.commit()
        db.refresh(user)

        # Generate tokens
        token_data = {"sub": user.email, "user_id": user.id}
        access_token = create_access_token(
            data=token_data,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        refresh_token = create_refresh_token(data=token_data)

        user_response = UserData(
            id=user.id,
            name=user.name,
            email=user.email,
            timezone=user.timezone,
            profile_photo_url=user.profile_photo_url,
            is_verified=user.is_verified,
            created_at=user.created_at.isoformat() if user.created_at else None
        )

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user_response
        )

    except HTTPException:
        raise
    except ValueError as e:
        # Invalid / expired Google token — client error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected authentication error: {type(e).__name__}: {str(e)}"
        )


@router.get('/me', response_model=UserData)
def get_current_user_info(
        current_user: models.User = Depends(get_current_user)
):
    """Get current user information"""
    return UserData(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        timezone=current_user.timezone,
        profile_photo_url=current_user.profile_photo_url,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None
    )


@router.post('/change-password')
def change_password(
        password_data: PasswordChange,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Change password for authenticated user"""

    # Check if user uses Google OAuth
    if current_user.auth_provider == "google":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change password for Google OAuth users"
        )

    # Verify old password
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect current password"
        )

    # Validate new password strength
    if not validate_password_strength(password_data.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters and contain uppercase, lowercase, and numbers"
        )

    # Update password
    current_user.hashed_password = get_password_hash(password_data.new_password)
    current_user.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Password changed successfully"}


@router.post('/refresh', response_model=AuthResponse)
def refresh_token(
        body: TokenRefreshRequest,
        db: Session = Depends(get_db)
):
    """Get a new access token using a refresh token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = verify_refresh_token(body.refresh_token)
    except ValueError:
        raise credentials_exception

    email: str = payload.get("sub")
    if not email:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    if user.is_locked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is locked")

    # Reject refresh tokens issued before the last logout
    iat = payload.get("iat")
    if iat and user.last_logout_at:
        token_issued_at = datetime.utcfromtimestamp(iat)
        if token_issued_at <= user.last_logout_at:
            raise credentials_exception

    # Issue new access token and rotate the refresh token
    token_data = {"sub": user.email, "user_id": user.id}
    new_access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    new_refresh_token = create_refresh_token(data=token_data)

    user_response = UserData(
        id=user.id,
        name=user.name,
        email=user.email,
        timezone=user.timezone,
        profile_photo_url=user.profile_photo_url,
        is_verified=user.is_verified,
        created_at=user.created_at.isoformat() if user.created_at else None
    )

    return AuthResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response
    )


@router.post('/logout')
def logout(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Logout — invalidates the current token by recording logout timestamp"""
    current_user.last_logout_at = datetime.utcnow()
    db.commit()
    return {"message": "Logged out successfully"}
