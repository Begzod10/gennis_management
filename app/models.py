from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Date, DateTime, ForeignKey, Boolean, Integer, Text, Table, UniqueConstraint, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Job(Base):
    __tablename__ = "job"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    desc = Column(String(255), nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)

    users = relationship("User", back_populates="job")

class User(Base):
    __tablename__ = "user"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    surname = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=True, index=True)
    born_date = Column(Date, nullable=True)
    password = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    age = Column(BigInteger, nullable=True)
    job_id = Column(BigInteger, ForeignKey("job.id"), nullable=True)
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    role = Column(String(50), nullable=False, default="user")
    deleted = Column(Boolean, nullable=False, default=False)
    timezone = Column(String(100), nullable=False, default="Asia/Tashkent")
    auth_provider = Column(String(50), nullable=False, default="email")
    profile_photo_url = Column(String(500), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    last_logout_at = Column(DateTime, nullable=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True, index=True)
    salary = Column(BigInteger, nullable=True, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)

    job = relationship("Job", back_populates="users")
    salary_months = relationship("SalaryMonth", back_populates="user")
    salary_days = relationship("SalaryDay", back_populates="user")
    project_memberships = relationship("ProjectMember", foreign_keys="ProjectMember.user_id", back_populates="user")
    section_memberships = relationship("SectionMember", foreign_keys="SectionMember.user_id", back_populates="user")

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > datetime.utcnow()


Person = User


class SalaryMonth(Base):
    __tablename__ = "salary_month"

    id = Column(BigInteger, primary_key=True, index=True)
    salary = Column(BigInteger, nullable=False)
    taken_salary = Column(BigInteger, nullable=False, default=0)
    remaining_salary = Column(BigInteger, nullable=False, default=0)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    date = Column(Date, nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="salary_months")
    salary_days = relationship("SalaryDay", back_populates="salary_month")


class SalaryDay(Base):
    __tablename__ = "salary_day"

    id = Column(BigInteger, primary_key=True, index=True)
    salary_month_id = Column(BigInteger, ForeignKey("salary_month.id"), nullable=False)
    amount = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    date = Column(Date, nullable=False)
    payment_type = Column(String(255), nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)

    salary_month = relationship("SalaryMonth", back_populates="salary_days")
    user = relationship("User", back_populates="salary_days")


# ── Project module ────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "project"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    manager_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    description = Column(Text, nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    manager = relationship("User", foreign_keys=[manager_id])
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    missions = relationship("Mission", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_member"

    id = Column(BigInteger, primary_key=True, index=True)
    project_id = Column(BigInteger, ForeignKey("project.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships")


# ── Mission module ────────────────────────────────────────────────────────────

class SystemModel(Base):
    __tablename__ = "system_model"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    desc = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)

    branches = relationship("Branch", back_populates="system_model")


class Branch(Base):
    __tablename__ = "branch"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    system_model_id = Column(BigInteger, ForeignKey("system_model.id"), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)

    system_model = relationship("SystemModel", back_populates="branches")


class Tag(Base):
    __tablename__ = "tag"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)

    missions = relationship("Mission", secondary="mission_tag", back_populates="tags")


mission_tag = Table(
    "mission_tag",
    Base.metadata,
    Column("mission_id", BigInteger, ForeignKey("mission.id"), primary_key=True),
    Column("tag_id", BigInteger, ForeignKey("tag.id"), primary_key=True),
)


class Mission(Base):
    __tablename__ = "mission"

    id = Column(BigInteger, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    final_sc = Column(Integer, default=0)
    description = Column(Text, nullable=True)
    category = Column(String(50), default="academic")

    creator_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    executor_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    reviewer_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    original_executor_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    redirected_by_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)

    is_redirected = Column(Boolean, default=False)
    redirected_at = Column(DateTime, nullable=True)

    branch_id = Column(BigInteger, nullable=True)
    branch_name = Column(String(255), nullable=True)
    system_id = Column(BigInteger, ForeignKey("system_model.id"), nullable=True)
    location_id = Column(Integer, nullable=True)   # Gennis location ID for routing
    location_name = Column(String(255), nullable=True)

    channel = Column(String(30), default="line_management", nullable=False)
    project_id = Column(BigInteger, ForeignKey("project.id"), nullable=True)
    section_id = Column(BigInteger, ForeignKey("section.id"), nullable=True)
    approval_status = Column(String(20), nullable=True)
    approved_by_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    gennis_executor_id = Column(Integer, nullable=True)
    gennis_executor_name = Column(String(255), nullable=True)
    gennis_reviewer_id = Column(Integer, nullable=True)
    gennis_reviewer_name = Column(String(255), nullable=True)
    turon_executor_id = Column(BigInteger, nullable=True)
    turon_executor_name = Column(String(255), nullable=True)
    turon_reviewer_id = Column(BigInteger, nullable=True)
    turon_reviewer_name = Column(String(255), nullable=True)

    start_date = Column(Date, server_default=func.current_date())
    deadline = Column(Date, nullable=False)
    finish_date = Column(Date, nullable=True)
    approved_date = Column(Date, nullable=True)

    status = Column(String(30), default="not_started")

    kpi_weight = Column(Integer, default=10)
    penalty_per_day = Column(Integer, default=2)
    early_bonus_per_day = Column(Integer, default=1)
    max_bonus = Column(Integer, default=3)
    max_penalty = Column(Integer, default=10)
    delay_days = Column(Integer, default=0)

    is_recurring = Column(Boolean, default=False)
    recurring_type = Column(String(20), nullable=True)
    repeat_every = Column(Integer, default=1)
    last_generated = Column(Date, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted = Column(Boolean, nullable=False, default=False)

    creator = relationship("User", foreign_keys=[creator_id])
    executor = relationship("User", foreign_keys=[executor_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    original_executor = relationship("User", foreign_keys=[original_executor_id])
    redirected_by = relationship("User", foreign_keys=[redirected_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    system_model = relationship("SystemModel", foreign_keys=[system_id])
    project = relationship("Project", back_populates="missions")
    tags = relationship("Tag", secondary="mission_tag", back_populates="missions")
    subtasks = relationship("MissionSubtask", back_populates="mission", cascade="all, delete-orphan")
    attachments = relationship("MissionAttachment", back_populates="mission", cascade="all, delete-orphan")
    comments = relationship("MissionComment", back_populates="mission", cascade="all, delete-orphan")
    proofs = relationship("MissionProof", back_populates="mission", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="mission")

    def calculate_delay_days(self):
        if self.finish_date and self.deadline:
            self.delay_days = (self.finish_date - self.deadline).days
        else:
            self.delay_days = 0
        return self.delay_days

    def final_score(self):
        delay = self.delay_days
        base = self.kpi_weight
        if delay < 0:
            bonus = min(abs(delay) * self.early_bonus_per_day, self.max_bonus)
            return base + bonus
        if delay == 0:
            return base
        penalty = min(delay * self.penalty_per_day, self.max_penalty)
        return max(0, base - penalty)


class MissionSubtask(Base):
    __tablename__ = "mission_subtask"

    id = Column(BigInteger, primary_key=True, index=True)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=False)
    executor_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    title = Column(String(255), nullable=False)
    is_done = Column(Boolean, default=False)
    order = Column(Integer, default=0)
    deleted = Column(Boolean, nullable=False, default=False)

    mission = relationship("Mission", back_populates="subtasks")
    executor = relationship("User", foreign_keys=[executor_id])


class MissionAttachment(Base):
    __tablename__ = "mission_attachment"

    id = Column(BigInteger, primary_key=True, index=True)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=False)
    file = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())
    note = Column(String(255), nullable=True)
    creator_name = Column(String(255), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)

    mission = relationship("Mission", back_populates="attachments")


class MissionComment(Base):
    __tablename__ = "mission_comment"

    id = Column(BigInteger, primary_key=True, index=True)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    text = Column(Text, nullable=False)
    attachment = Column(String(500), nullable=True)
    creator_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    deleted = Column(Boolean, nullable=False, default=False)

    mission = relationship("Mission", back_populates="comments")
    user = relationship("User")


class MissionProof(Base):
    __tablename__ = "mission_proof"

    id = Column(BigInteger, primary_key=True, index=True)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=False)
    file = Column(String(500), nullable=False)
    comment = Column(String(255), nullable=True)
    creator_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    deleted = Column(Boolean, nullable=False, default=False)

    mission = relationship("Mission", back_populates="proofs")


class MissionHistory(Base):
    __tablename__ = "mission_history"

    id = Column(BigInteger, primary_key=True, index=True)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=False)
    changed_by_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    executor_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    reviewer_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    gennis_executor_id = Column(Integer, nullable=True)
    gennis_executor_name = Column(String(255), nullable=True)
    gennis_reviewer_id = Column(Integer, nullable=True)
    gennis_reviewer_name = Column(String(255), nullable=True)
    turon_executor_id = Column(BigInteger, nullable=True)
    turon_executor_name = Column(String(255), nullable=True)
    turon_reviewer_id = Column(BigInteger, nullable=True)
    turon_reviewer_name = Column(String(255), nullable=True)
    status = Column(String(30), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    mission = relationship("Mission", foreign_keys=[mission_id])
    changed_by = relationship("User", foreign_keys=[changed_by_id])
    executor = relationship("User", foreign_keys=[executor_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])


class Section(Base):
    __tablename__ = "section"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    leader_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    leader = relationship("User", foreign_keys=[leader_id])
    members = relationship("SectionMember", back_populates="section", cascade="all, delete-orphan")


class SectionMember(Base):
    __tablename__ = "section_member"

    id = Column(BigInteger, primary_key=True, index=True)
    section_id = Column(BigInteger, ForeignKey("section.id"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)

    __table_args__ = (UniqueConstraint("section_id", "user_id"),)

    section = relationship("Section", back_populates="members")
    user = relationship("User", back_populates="section_memberships")


class Dividend(Base):
    __tablename__ = "dividend"

    id = Column(BigInteger, primary_key=True, index=True)
    amount = Column(BigInteger, nullable=False)
    source = Column(String(50), nullable=False)  # "gennis" or "turon"
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    location_id = Column(Integer, nullable=True)   # Gennis: links to Gennis locations
    branch_id = Column(BigInteger, nullable=True)  # Turon: links to Turon branches
    deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())


class Investment(Base):
    __tablename__ = "investment"

    id = Column(BigInteger, primary_key=True, index=True)
    amount = Column(BigInteger, nullable=False)
    source = Column(String(50), nullable=False)  # "gennis" or "turon"
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    location_id = Column(Integer, nullable=True)   # Gennis: links to Gennis locations
    branch_id = Column(BigInteger, nullable=True)  # Turon: links to Turon branches
    deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())


class Notification(Base):
    __tablename__ = "notification"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("user.id"), nullable=False)
    mission_id = Column(BigInteger, ForeignKey("mission.id"), nullable=True)
    message = Column(Text, nullable=False)
    role = Column(String(20), nullable=False)
    deadline = Column(Date, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    deleted = Column(Boolean, nullable=False, default=False)

    user = relationship("User")
    mission = relationship("Mission", back_populates="notifications")


class OverheadType(Base):
    __tablename__ = "overhead_type"

    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    cost = Column(BigInteger, nullable=True)
    changeable = Column(Boolean, default=True, nullable=False)
    deleted = Column(Boolean, default=False, nullable=False)


class ApiLog(Base):
    __tablename__ = "api_log"

    id = Column(BigInteger, primary_key=True, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False, index=True)
    status_code = Column(Integer, nullable=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    response_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class BranchLoan(Base):
    """A loan agreement (branch-level). Each loan is a long-lived agreement
    settled by one or more BranchLoanTransaction rows on the source side."""
    __tablename__ = "branch_loan"

    id = Column(BigInteger, primary_key=True, index=True)
    source = Column(String(50), nullable=False)  # 'gennis' or 'turon'
    location_id = Column(Integer, nullable=True)   # Gennis: locations.id
    branch_id = Column(BigInteger, nullable=True)  # Turon: branch.id

    # Counterparty: either a User in the source system, or a manual name
    counterparty_user_id = Column(BigInteger, nullable=True)
    counterparty_name = Column(String(255), nullable=True)
    counterparty_surname = Column(String(255), nullable=True)
    counterparty_phone = Column(String(50), nullable=True)

    direction = Column(String(8), nullable=False)  # 'out' branch lent | 'in' branch borrowed
    principal_amount = Column(BigInteger, nullable=False)
    payment_type = Column(String(50), nullable=True)  # for the disbursement transaction

    issued_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)
    settled_date = Column(Date, nullable=True)

    reason = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    status = Column(String(12), nullable=False, default="active")  # active | settled | cancelled
    cancelled_reason = Column(String(500), nullable=True)

    created_by_id = Column(BigInteger, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    deleted = Column(Boolean, nullable=False, default=False)

    created_by = relationship("User", foreign_keys=[created_by_id])
