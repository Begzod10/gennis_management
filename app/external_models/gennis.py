"""
Read-only SQLAlchemy models mapped to the Gennis education center database.
Only columns needed for statistics are declared.
"""
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Date, ForeignKey, Text, Float
from sqlalchemy.orm import DeclarativeBase


class GennisBase(DeclarativeBase):
    pass


# ── Calendar ──────────────────────────────────────────────────────────────────

class CalendarYear(GennisBase):
    __tablename__ = "calendaryear"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)


class CalendarMonth(GennisBase):
    __tablename__ = "calendarmonth"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    year_id = Column(Integer, ForeignKey("calendaryear.id"))


class CalendarDay(GennisBase):
    __tablename__ = "calendarday"
    id = Column(Integer, primary_key=True)
    date = Column(DateTime)


# ── Lookup ────────────────────────────────────────────────────────────────────

class Locations(GennisBase):
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class PaymentTypes(GennisBase):
    __tablename__ = "paymenttypes"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Subjects(GennisBase):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    name = Column(String)


# ── Users / people ────────────────────────────────────────────────────────────

class GennisRoles(GennisBase):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    role = Column(String)
    type_role = Column(String)


class EducationLanguage(GennisBase):
    __tablename__ = "educationlanguage"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Users(GennisBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    surname = Column(String)
    username = Column(String)
    age = Column(Integer)
    location_id = Column(Integer, ForeignKey("locations.id"))
    education_language = Column(Integer, ForeignKey("educationlanguage.id"))
    role_id = Column(Integer, ForeignKey("roles.id"))
    calendar_day = Column(Integer, ForeignKey("calendarday.id"))
    director = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)


class Students(GennisBase):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))


class DeletedStudents(GennisBase):
    __tablename__ = "deleted_students"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    calendar_day = Column(Integer, ForeignKey("calendarday.id"))


class Teachers(GennisBase):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))


class DeletedTeachers(GennisBase):
    __tablename__ = "deletedteachers"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    calendar_day = Column(Integer, ForeignKey("calendarday.id"))


class Assistent(GennisBase):
    __tablename__ = "assistent"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    deleted = Column(Boolean, default=False)


class GennisProfessions(GennisBase):
    __tablename__ = "professions"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Staff(GennisBase):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    profession_id = Column(Integer, ForeignKey("professions.id"))
    deleted = Column(Boolean, default=False)
    deleted_comment = Column(String)
    deleted_date = Column(DateTime)


# ── Groups ────────────────────────────────────────────────────────────────────

class Groups(GennisBase):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    status = Column(Boolean, default=False)


# ── Attendance ────────────────────────────────────────────────────────────────

class AttendanceHistoryStudent(GennisBase):
    __tablename__ = "attendancehistorystudent"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    total_debt = Column(Integer)
    payment = Column(Integer, default=0)
    remaining_debt = Column(Integer)
    total_discount = Column(Integer)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


# ── Payments ──────────────────────────────────────────────────────────────────

class StudentPayments(GennisBase):
    __tablename__ = "studentpayments"
    id = Column(Integer, primary_key=True)
    payment_sum = Column(Integer)
    payment_type_id = Column(Integer, ForeignKey("paymenttypes.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    payment = Column(Boolean)
    payment_data = Column(DateTime)
    student_id = Column(Integer, ForeignKey("students.id"))


# ── Salaries ──────────────────────────────────────────────────────────────────

class TeacherSalary(GennisBase):
    __tablename__ = "teachersalary"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    total_salary = Column(Integer)
    taken_money = Column(Integer)
    remaining_salary = Column(Integer)
    debt = Column(Integer, default=0)
    total_fine = Column(Integer, default=0)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


class TeacherBlackSalary(GennisBase):
    __tablename__ = "teacher_black_salary"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    total_salary = Column(Integer)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


class TeacherSalaries(GennisBase):
    """Individual teacher salary payment transactions."""
    __tablename__ = "teachersalaries"
    id = Column(Integer, primary_key=True)
    payment_sum = Column(Integer)
    payment_type_id = Column(Integer, ForeignKey("paymenttypes.id"))
    salary_location_id = Column(Integer, ForeignKey("teachersalary.id"))
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))


class AssistentSalary(GennisBase):
    __tablename__ = "asistent_salary"
    id = Column(Integer, primary_key=True)
    assisten_id = Column(Integer, ForeignKey("assistent.id"))
    total_salary = Column(Integer)
    taken_money = Column(Integer)
    remaining_salary = Column(Integer)
    debt = Column(Integer)
    total_fine = Column(Integer, default=0)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


class AssistentBlackSalary(GennisBase):
    __tablename__ = "asistent_black_salary"
    id = Column(Integer, primary_key=True)
    assistent_id = Column(Integer, ForeignKey("assistent.id"))
    total_salary = Column(Integer)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


class StaffSalary(GennisBase):
    __tablename__ = "staffsalary"
    id = Column(Integer, primary_key=True)
    staff_id = Column(Integer, ForeignKey("staff.id"))
    total_salary = Column(Integer)
    taken_money = Column(Integer)
    remaining_salary = Column(Integer)
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
    status = Column(Boolean, default=False)


class StaffSalaries(GennisBase):
    """Individual staff salary payment transactions."""
    __tablename__ = "staffsalaries"
    id = Column(Integer, primary_key=True)
    payment_sum = Column(Integer)
    payment_type_id = Column(Integer, ForeignKey("paymenttypes.id"))
    salary_location_id = Column(Integer, ForeignKey("staffsalary.id"))
    staff_id = Column(Integer, ForeignKey("staff.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))


# ── Dividends ─────────────────────────────────────────────────────────────────

class GennisDividend(GennisBase):
    __tablename__ = "management_dividend"
    id = Column(Integer, primary_key=True, autoincrement=True)
    management_id = Column(Integer, nullable=False, unique=True)
    amount = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    deleted = Column(Boolean, default=False)


# ── Investments ───────────────────────────────────────────────────────────────

class GennisInvestment(GennisBase):
    __tablename__ = "management_investment"
    id = Column(Integer, primary_key=True, autoincrement=True)
    management_id = Column(Integer, nullable=False, unique=True)
    amount = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    deleted = Column(Boolean, default=False)


# ── Missions ──────────────────────────────────────────────────────────────────

class GennisMission(GennisBase):
    __tablename__ = "missions"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    title = Column(String(255))
    description = Column(Text, nullable=True)
    category = Column(String(50))
    creator_id = Column(Integer, ForeignKey("users.id"))
    creator_name = Column(String(255), nullable=True)
    executor_id = Column(Integer, ForeignKey("users.id"))
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_name = Column(String(255), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    start_datetime = Column(DateTime)
    deadline_datetime = Column(DateTime)
    finish_datetime = Column(DateTime, nullable=True)
    status = Column(String(30))
    kpi_weight = Column(Integer, default=10)
    penalty_per_day = Column(Integer, default=2)
    early_bonus_per_day = Column(Integer, default=1)
    max_bonus = Column(Integer, default=3)
    max_penalty = Column(Integer, default=10)
    delay_days = Column(Integer, default=0)
    final_sc = Column(Integer, default=0)
    is_recurring = Column(Boolean, default=False)
    created_at = Column(DateTime)


# ── Mission sub-records ───────────────────────────────────────────────────────

class GennisMissionSubtask(GennisBase):
    __tablename__ = "mission_subtasks"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(Integer, ForeignKey("missions.id"))
    title = Column(String(255))
    is_done = Column(Boolean, default=False)
    order = Column(Integer, default=0)
    creator_name = Column(String(255), nullable=True)


class GennisMissionAttachment(GennisBase):
    __tablename__ = "mission_attachments"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(Integer, ForeignKey("missions.id"))
    file_path = Column(String(500))
    note = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    creator_name = Column(String(255), nullable=True)


class GennisMissionComment(GennisBase):
    __tablename__ = "mission_comments"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(Integer, ForeignKey("missions.id"))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    text = Column(Text)
    attachment_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=True)
    creator_name = Column(String(255), nullable=True)


class GennisMissionProof(GennisBase):
    __tablename__ = "mission_proofs"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(Integer, ForeignKey("missions.id"))
    file_path = Column(String(500))
    comment = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)
    creator_name = Column(String(255), nullable=True)


class GennisMissionHistory(GennisBase):
    __tablename__ = "mission_history"
    id = Column(Integer, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(Integer, ForeignKey("missions.id"))
    executor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    management_executor_id = Column(BigInteger, nullable=True)
    management_executor_name = Column(String(255), nullable=True)
    management_reviewer_id = Column(BigInteger, nullable=True)
    management_reviewer_name = Column(String(255), nullable=True)
    turon_executor_id = Column(BigInteger, nullable=True)
    turon_executor_name = Column(String(255), nullable=True)
    turon_reviewer_id = Column(BigInteger, nullable=True)
    turon_reviewer_name = Column(String(255), nullable=True)
    changed_by_name = Column(String(255), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=True)


# ── Overheads ─────────────────────────────────────────────────────────────────

class OverheadType(GennisBase):
    __tablename__ = "overheadtype"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    cost = Column(Integer, nullable=True)
    changeable = Column(Boolean, default=True, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    deleted = Column(Boolean, default=False)
    management_id = Column(Integer, nullable=True)


class Overhead(GennisBase):
    __tablename__ = "overhead"
    id = Column(Integer, primary_key=True)
    item_sum = Column(Integer)
    item_name = Column(String)
    overhead_type_id = Column(Integer, ForeignKey("overheadtype.id"), nullable=True)
    payment_type_id = Column(Integer, ForeignKey("paymenttypes.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))


class GennisApiLog(GennisBase):
    __tablename__ = "api_log"
    id = Column(Integer, primary_key=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=True)
