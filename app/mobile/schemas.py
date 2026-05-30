from datetime import date, datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


SystemLiteral = Literal["management", "gennis", "turon"]


# ── Identity ─────────────────────────────────────────────────────────────────

class MobileIdentity(BaseModel):
    """Decoded mobile JWT payload, attached to the request via dependency."""
    system: SystemLiteral
    external_id: int
    management_user_id: Optional[int] = None
    name: Optional[str] = None
    role: Optional[str] = None


# ── Auth ─────────────────────────────────────────────────────────────────────

class MobileLoginRequest(BaseModel):
    system: SystemLiteral
    username: str = Field(..., description="email (management), username (Gennis), username or phone (Turon)")
    password: str


class MobileUserOut(BaseModel):
    id: int
    system: SystemLiteral
    name: Optional[str] = None
    surname: Optional[str] = None
    role: Optional[str] = None


class MobileAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: MobileUserOut


# ── Missions ─────────────────────────────────────────────────────────────────

class MobileMissionStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    approved = "approved"
    declined = "declined"


class MobileMissionOut(BaseModel):
    """Normalised mission row across the three backends.

    `source` is the system the row physically lives in. `id` is the row's
    primary key in that backend; for Gennis/Turon native missions the
    `management_id` field is None.
    """
    id: int
    source: SystemLiteral
    management_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    creator_id: Optional[int] = None
    creator_name: Optional[str] = None
    executor_id: Optional[int] = None
    executor_name: Optional[str] = None
    reviewer_id: Optional[int] = None
    reviewer_name: Optional[str] = None
    location_id: Optional[int] = None
    branch_id: Optional[int] = None
    deadline: Optional[date] = None
    finish_date: Optional[date] = None
    kpi_weight: int = 10
    delay_days: int = 0
    final_sc: int = 0
    created_at: Optional[datetime] = None


class MobileMissionList(BaseModel):
    total: int
    results: List[MobileMissionOut]


class MobileMissionCreate(BaseModel):
    """Create a mission in the caller's own system.

    A management user creates a management-side mission (which then syncs
    down). A Gennis user creates a native Gennis mission. A Turon user
    creates a native Turon mission. Cross-system creation is intentionally
    not supported on this surface — that is what the management owner flow
    is for.
    """
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    executor_id: int = Field(..., description="executor id in the caller's system")
    reviewer_id: Optional[int] = None
    deadline: Optional[date] = None
    kpi_weight: int = 10


class MobileStatusUpdate(BaseModel):
    status: MobileMissionStatus
    finish_date: Optional[date] = None


class MobileMissionUpdate(BaseModel):
    """Partial-update payload for an existing mission."""
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    deadline: Optional[date] = None
    kpi_weight: Optional[int] = None


class MobileMissionComplete(BaseModel):
    finish_date: date


class MobileApprovalStatus(str, Enum):
    approved = "approved"
    declined = "declined"


class MobileMissionApprove(BaseModel):
    approval_status: MobileApprovalStatus


class MobileMissionRedirect(BaseModel):
    new_executor_id: int


# ── Auth (refresh + me) ──────────────────────────────────────────────────────

class MobileRefreshRequest(BaseModel):
    refresh_token: str


class MobileMeOut(BaseModel):
    id: int
    system: SystemLiteral
    name: Optional[str] = None
    surname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    telegram_linked: bool = False
    telegram_id: Optional[int] = None


class MobileMeUpdate(BaseModel):
    name: Optional[str] = None
    surname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class MobilePasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


# ── Mission history & related "events" ───────────────────────────────────────

class MobileHistoryEntry(BaseModel):
    id: int
    source: SystemLiteral
    status: Optional[str] = None
    note: Optional[str] = None
    changed_by_name: Optional[str] = None
    executor_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    created_at: Optional[datetime] = None


class MobileCommentOut(BaseModel):
    id: int
    source: SystemLiteral
    text: str
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    attachment_path: Optional[str] = None
    created_at: Optional[datetime] = None


class MobileAttachmentOut(BaseModel):
    id: int
    source: SystemLiteral
    file_path: str
    note: Optional[str] = None
    creator_name: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class MobileProofOut(BaseModel):
    id: int
    source: SystemLiteral
    file_path: str
    comment: Optional[str] = None
    creator_name: Optional[str] = None
    created_at: Optional[datetime] = None


# ── Subtasks ─────────────────────────────────────────────────────────────────

class MobileSubtaskOut(BaseModel):
    id: int
    source: SystemLiteral
    mission_id: int
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    is_done: bool = False
    order: int = 0
    deadline: Optional[date] = None
    finish_date: Optional[date] = None
    creator_name: Optional[str] = None
    executor_name: Optional[str] = None
    created_at: Optional[datetime] = None


# ── Event-write payloads (POSTs) ─────────────────────────────────────────────

class MobileCommentCreate(BaseModel):
    text: str = Field(..., min_length=1)
    attachment_path: Optional[str] = None


class MobileAttachmentCreate(BaseModel):
    file_path: str = Field(..., min_length=1)
    note: Optional[str] = None


class MobileProofCreate(BaseModel):
    file_path: str = Field(..., min_length=1)
    comment: Optional[str] = None


class MobileSubtaskCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    deadline: Optional[date] = None
    order: int = 0
    executor_id: Optional[int] = None


class MobileSubtaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    is_done: Optional[bool] = None
    order: Optional[int] = None
    deadline: Optional[date] = None
    finish_date: Optional[date] = None
    executor_id: Optional[int] = None

