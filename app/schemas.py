from pydantic import BaseModel, field_validator
from .config import settings as _settings
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
    job_id: Optional[int] = None


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
    job_id: Optional[int] = None
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

class ChannelEnum(str, Enum):
    line_management = "line_management"
    project = "project"
    service_request = "service_request"


class ApprovalStatusEnum(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


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
    executor_ids: List[int]
    reviewer_id: Optional[int] = None
    branch_id: Optional[int] = None
    system_id: Optional[int] = None
    location_id: Optional[int] = None
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
    channel: ChannelEnum = ChannelEnum.line_management
    project_id: Optional[int] = None
    gennis_executor_id: Optional[int] = None
    gennis_reviewer_id: Optional[int] = None
    turon_executor_id: Optional[int] = None
    turon_reviewer_id: Optional[int] = None

    @field_validator("project_id", "branch_id", "system_id", "location_id", "reviewer_id", "gennis_executor_id", "gennis_reviewer_id", "turon_executor_id", "turon_reviewer_id", mode="before")
    @classmethod
    def zero_to_none(cls, v):
        return None if v == 0 else v


class GennisExecutorItem(BaseModel):

    id: int
    location_id: Optional[int] = None
    location_name: Optional[str] = None


class TuronExecutorItem(BaseModel):
    id: int
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None


class MissionBulkCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: CategoryEnum = CategoryEnum.ACADEMIC
    executor_ids: List[int] = []
    reviewer_id: Optional[int] = None
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
    channel: ChannelEnum = ChannelEnum.line_management
    project_id: Optional[int] = None
    system_id: Optional[int] = None
    gennis_executor_ids: List[GennisExecutorItem] = []
    gennis_reviewer_id: Optional[int] = None
    turon_executor_ids: List[TuronExecutorItem] = []
    turon_reviewer_id: Optional[int] = None

    @field_validator("project_id", "system_id", "reviewer_id", "gennis_reviewer_id", "turon_reviewer_id", mode="before")
    @classmethod
    def zero_to_none(cls, v):
        return None if v == 0 else v


class MissionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[CategoryEnum] = None
    executor_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    branch_id: Optional[int] = None
    system_id: Optional[int] = None
    location_id: Optional[int] = None
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
    channel: Optional[ChannelEnum] = None
    project_id: Optional[int] = None
    gennis_executor_id: Optional[int] = None
    gennis_reviewer_id: Optional[int] = None
    turon_executor_id: Optional[int] = None
    turon_reviewer_id: Optional[int] = None

    @field_validator("project_id", "branch_id", "system_id", "location_id", "reviewer_id", "executor_id", "gennis_executor_id", "gennis_reviewer_id", "turon_executor_id", "turon_reviewer_id", mode="before")
    @classmethod
    def zero_to_none(cls, v):
        return None if v == 0 else v


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
    branch_name: Optional[str]
    system_id: Optional[int]
    location_id: Optional[int]
    location_name: Optional[str]
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
    channel: str
    project_id: Optional[int]
    approval_status: Optional[str]
    approved_by_id: Optional[int]
    gennis_executor_id: Optional[int]
    gennis_executor_name: Optional[str]
    gennis_reviewer_id: Optional[int]
    gennis_reviewer_name: Optional[str]
    turon_executor_id: Optional[int]
    turon_executor_name: Optional[str]
    turon_reviewer_id: Optional[int]
    turon_reviewer_name: Optional[str]
    creator: Optional[UserOut] = None
    executor: Optional[UserOut] = None
    reviewer: Optional[UserOut] = None

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

    @field_validator("file", mode="before")
    @classmethod
    def make_file_url(cls, v):
        if v and not str(v).startswith(("http://", "https://")):
            return f"{_settings.BASE_URL}/{v}"
        return v


# --- MissionComment ---
class MissionCommentCreate(BaseModel):
    text: str


class MissionCommentUpdate(BaseModel):
    text: Optional[str] = None
    attachment: Optional[str] = None


class MissionCommentOut(BaseModel):
    id: int
    mission_id: int
    user_id: Optional[int] = None
    user: Optional["UserOut"] = None
    creator_name: Optional[str] = None
    text: str
    attachment: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("attachment", mode="before")
    @classmethod
    def make_attachment_url(cls, v):
        if v and not str(v).startswith(("http://", "https://")):
            return f"{_settings.BASE_URL}/{v}"
        return v


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

    @field_validator("file", mode="before")
    @classmethod
    def make_file_url(cls, v):
        if v and not str(v).startswith(("http://", "https://")):
            return f"{_settings.BASE_URL}/{v}"
        return v


# --- Dividend ---
class DividendCreate(BaseModel):
    amount: int
    source: str  # "gennis" or "turon"
    date: date
    description: Optional[str] = None
    payment_type: Optional[str] = None
    location_id: Optional[int] = None  # for source="gennis"
    branch_id: Optional[int] = None    # for source="turon"


class DividendUpdate(BaseModel):
    amount: Optional[int] = None
    date: Optional[date] = None
    description: Optional[str] = None
    payment_type: Optional[str] = None
    location_id: Optional[int] = None
    branch_id: Optional[int] = None


class DividendOut(BaseModel):
    id: int
    amount: int
    source: str
    date: date
    description: Optional[str]
    payment_type: Optional[str]
    location_id: Optional[int]
    branch_id: Optional[int]
    deleted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Investment ---
class InvestmentCreate(BaseModel):
    amount: int
    source: str  # "gennis" or "turon"
    date: date
    description: Optional[str] = None
    payment_type: Optional[str] = None
    location_id: Optional[int] = None  # for source="gennis"
    branch_id: Optional[int] = None    # for source="turon"


class InvestmentUpdate(BaseModel):
    amount: Optional[int] = None
    date: Optional[date] = None
    description: Optional[str] = None
    payment_type: Optional[str] = None
    location_id: Optional[int] = None
    branch_id: Optional[int] = None


class InvestmentOut(BaseModel):
    id: int
    amount: int
    source: str
    date: date
    description: Optional[str]
    payment_type: Optional[str]
    location_id: Optional[int]
    branch_id: Optional[int]
    deleted: bool
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


# --- Project ---
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectMemberAdd(BaseModel):
    user_id: int


class ProjectMemberOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    user: Optional["UserOut"] = None

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    name: str
    manager_id: int
    description: Optional[str]
    deleted: bool
    created_at: datetime
    members: List[ProjectMemberOut] = []

    model_config = {"from_attributes": True}


# --- Section ---
class SectionCreate(BaseModel):
    name: str
    leader_id: Optional[int] = None


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    leader_id: Optional[int] = None


class SectionMemberAdd(BaseModel):
    user_id: int


class SectionMemberOut(BaseModel):
    id: int
    section_id: int
    user_id: int
    user: Optional["UserOut"] = None

    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: int
    name: str
    leader_id: Optional[int]
    deleted: bool
    created_at: datetime
    members: List[SectionMemberOut] = []

    model_config = {"from_attributes": True}


# --- MissionHistory ---
class MissionHistoryOut(BaseModel):
    id: int
    mission_id: int
    changed_by_id: Optional[int]
    executor_id: Optional[int]
    reviewer_id: Optional[int]
    gennis_executor_id: Optional[int]
    gennis_executor_name: Optional[str]
    gennis_reviewer_id: Optional[int]
    gennis_reviewer_name: Optional[str]
    turon_executor_id: Optional[int]
    turon_executor_name: Optional[str]
    turon_reviewer_id: Optional[int]
    turon_reviewer_name: Optional[str]
    note: Optional[str]
    created_at: datetime
    changed_by: Optional[UserOut] = None
    executor: Optional[UserOut] = None
    reviewer: Optional[UserOut] = None

    model_config = {"from_attributes": True}


# --- Mission Approval ---
class MissionApprove(BaseModel):
    approval_status: ApprovalStatusEnum
