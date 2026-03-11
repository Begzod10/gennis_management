from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List
from enum import Enum


# --- Job ---
class JobCreate(BaseModel):
    name: str
    desc: str


class JobUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None


class JobOut(BaseModel):
    id: int
    name: str
    desc: str

    model_config = {"from_attributes": True}


# --- Auth ---
class RegisterRequest(BaseModel):
    name: str
    surname: str
    email: str
    password: str
    born_date: Optional[date] = None
    age: Optional[int] = None
    job_id: int


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- User ---
class UserCreate(BaseModel):
    name: str
    surname: str
    email: Optional[str] = None
    born_date: Optional[date] = None
    password: Optional[str] = None
    age: Optional[int] = None
    job_id: int
    salary: Optional[int] = None
    role: Optional[str] = "user"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    surname: Optional[str] = None
    born_date: Optional[date] = None
    password: Optional[str] = None
    age: Optional[int] = None
    job_id: Optional[int] = None
    salary: Optional[int] = None
    role: Optional[str] = None


class UserOut(BaseModel):
    id: int
    name: str
    surname: str
    email: Optional[str]
    born_date: Optional[date]
    age: Optional[int]
    job_id: Optional[int]
    salary: Optional[int]
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


# --- SalaryMonth ---
class SalaryMonthCreate(BaseModel):
    salary: int
    user_id: int
    date: date


class SalaryMonthUpdate(BaseModel):
    salary: Optional[int] = None
    date: Optional[date] = None


class SalaryMonthOut(BaseModel):
    id: int
    salary: int
    taken_salary: int
    remaining_salary: int
    user_id: int
    date: date

    model_config = {"from_attributes": True}


# --- SalaryDay ---
class SalaryDayCreate(BaseModel):
    salary_month_id: int
    amount: int
    user_id: int
    date: date
    payment_type: str


class SalaryDayUpdate(BaseModel):
    amount: Optional[int] = None
    date: Optional[date] = None
    payment_type: Optional[str] = None


class SalaryDayOut(BaseModel):
    id: int
    salary_month_id: int
    amount: int
    user_id: int
    date: date
    payment_type: str

    model_config = {"from_attributes": True}


# ── Mission module ────────────────────────────────────────────────────────────

class CategoryEnum(str, Enum):
    ACADEMIC = "academic"
    ADMIN = "admin"
    STUDENT = "student"
    REPORT = "report"
    MEETING = "meeting"
    MARKETING = "marketing"
    MAINTENANCE = "maintenance"
    FINANCE = "finance"


class MissionStatusEnum(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    APPROVED = "approved"
    DECLINED = "declined"
    RECHECK = "recheck"


class RecurringTypeEnum(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


# --- SystemModel ---
class SystemModelCreate(BaseModel):
    name: str
    desc: Optional[str] = None


class SystemModelUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None


class SystemModelOut(BaseModel):
    id: int
    name: str
    desc: Optional[str]
    deleted: bool

    model_config = {"from_attributes": True}


# --- Branch ---
class BranchCreate(BaseModel):
    name: str
    system_model_id: Optional[int] = None


class BranchOut(BaseModel):
    id: int
    name: str
    system_model_id: Optional[int]
    deleted: bool

    model_config = {"from_attributes": True}


# --- Tag ---
class TagCreate(BaseModel):
    name: str


class TagOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# --- Mission ---
class MissionCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: CategoryEnum = CategoryEnum.ACADEMIC
    executor_id: int
    reviewer_id: Optional[int] = None
    branch_id: Optional[int] = None
    deadline: date
    kpi_weight: int = 10
    penalty_per_day: int = 2
    early_bonus_per_day: int = 1
    max_bonus: int = 3
    max_penalty: int = 10
    is_recurring: bool = False
    recurring_type: Optional[RecurringTypeEnum] = None
    repeat_every: int = 1
    tag_ids: List[int] = []


class MissionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[CategoryEnum] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    branch_id: Optional[int] = None
    deadline: Optional[date] = None
    finish_date: Optional[date] = None
    status: Optional[MissionStatusEnum] = None
    kpi_weight: Optional[int] = None
    penalty_per_day: Optional[int] = None
    early_bonus_per_day: Optional[int] = None
    max_bonus: Optional[int] = None
    max_penalty: Optional[int] = None
    is_recurring: Optional[bool] = None
    recurring_type: Optional[RecurringTypeEnum] = None
    repeat_every: Optional[int] = None
    tag_ids: Optional[List[int]] = None


class MissionOut(BaseModel):
    id: int
    title: str
    final_sc: int
    description: Optional[str]
    category: str
    creator_id: int
    executor_id: int
    reviewer_id: Optional[int]
    original_executor_id: Optional[int]
    redirected_by_id: Optional[int]
    is_redirected: bool
    redirected_at: Optional[datetime]
    branch_id: Optional[int]
    start_date: date
    deadline: date
    finish_date: Optional[date]
    status: str
    kpi_weight: int
    penalty_per_day: int
    early_bonus_per_day: int
    max_bonus: int
    max_penalty: int
    delay_days: int
    is_recurring: bool
    recurring_type: Optional[str]
    repeat_every: int
    last_generated: Optional[date]
    created_at: datetime
    updated_at: datetime
    tags: List[TagOut] = []

    model_config = {"from_attributes": True}


# --- MissionSubtask ---
class MissionSubtaskCreate(BaseModel):
    title: str
    order: int = 0


class MissionSubtaskUpdate(BaseModel):
    title: Optional[str] = None
    is_done: Optional[bool] = None
    order: Optional[int] = None


class MissionSubtaskOut(BaseModel):
    id: int
    mission_id: int
    title: str
    is_done: bool
    order: int

    model_config = {"from_attributes": True}


# --- MissionAttachment ---
class MissionAttachmentUpdate(BaseModel):
    note: Optional[str] = None
    file: Optional[str] = None


class MissionAttachmentOut(BaseModel):
    id: int
    mission_id: int
    file: str
    uploaded_at: datetime
    note: Optional[str]

    model_config = {"from_attributes": True}


# --- MissionComment ---
class MissionCommentCreate(BaseModel):
    text: str


class MissionCommentUpdate(BaseModel):
    text: Optional[str] = None
    attachment: Optional[str] = None


class MissionCommentOut(BaseModel):
    id: int
    mission_id: int
    user_id: int
    text: str
    attachment: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# --- MissionProof ---
class MissionProofUpdate(BaseModel):
    comment: Optional[str] = None
    file: Optional[str] = None


class MissionProofOut(BaseModel):
    id: int
    mission_id: int
    file: str
    comment: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Notification ---
class NotificationOut(BaseModel):
    id: int
    user_id: int
    mission_id: Optional[int]
    message: str
    role: str
    deadline: Optional[date]
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
