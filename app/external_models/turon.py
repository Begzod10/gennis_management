"""
Read-only SQLAlchemy models mapped to the Turon school (Django) database.
Django auto-generates table names as {app_label}_{model_name_lowercase}.
Only columns needed for statistics are declared.
"""
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Date, DateTime, ForeignKey, Table, Text, JSON, Float
from sqlalchemy.orm import DeclarativeBase


class TuronBase(DeclarativeBase):
    pass


# ── Django auth tables ────────────────────────────────────────────────────────

class AuthGroup(TuronBase):
    __tablename__ = "auth_group"
    id = Column(Integer, primary_key=True)
    name = Column(String(150))


# M2M: CustomUser.groups -> user_customuser_groups
customuser_groups = Table(
    "user_customuser_groups",
    TuronBase.metadata,
    Column("customuser_id", BigInteger, ForeignKey("user_customuser.id")),
    Column("group_id", Integer, ForeignKey("auth_group.id")),
)


class CustomAutoGroup(TuronBase):
    __tablename__ = "user_customautogroup"
    id = Column(BigInteger, primary_key=True)
    group_id = Column(Integer, ForeignKey("auth_group.id"))
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"), nullable=True)
    deleted = Column(Boolean, default=False, nullable=True)


class ManyBranch(TuronBase):
    """permissions app → permissions_manybranch: user ↔ branch access mapping."""
    __tablename__ = "permissions_manybranch"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"))
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))


# ── Lookup / reference tables ─────────────────────────────────────────────────

class Location(TuronBase):
    __tablename__ = "location_location"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))
    system_id = Column(BigInteger, ForeignKey("system_system.id"))


class Branch(TuronBase):
    __tablename__ = "branch_branch"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))
    location_id = Column(BigInteger, ForeignKey("location_location.id"))


class PaymentTypes(TuronBase):
    __tablename__ = "payments_paymenttypes"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(250))


class Subject(TuronBase):
    # subjects app -> subjects_subject
    __tablename__ = "subjects_subject"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(250))


class OverheadType(TuronBase):
    __tablename__ = "overhead_overheadtype"
    id = Column(BigInteger, primary_key=True)
    name = Column(String)
    order = Column(Integer)


class System(TuronBase):
    __tablename__ = "system_system"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))


class ClassColors(TuronBase):
    __tablename__ = "classes_classcolors"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100), nullable=True)
    value = Column(String(100), nullable=True)


class ClassTypes(TuronBase):
    __tablename__ = "classes_classtypes"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(100))


class ClassNumber(TuronBase):
    __tablename__ = "classes_classnumber"
    id = Column(BigInteger, primary_key=True)
    number = Column(Integer)
    price = Column(Integer, nullable=True)
    curriculum_hours = Column(Integer, nullable=True)
    class_types_id = Column(BigInteger, ForeignKey("classes_classtypes.id"), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)


# ── Users / students ──────────────────────────────────────────────────────────

class Language(TuronBase):
    __tablename__ = "language_language"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(250))


class CustomUser(TuronBase):
    __tablename__ = "user_customuser"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(200))
    surname = Column(String(200))
    father_name = Column(String(200), nullable=True)
    phone = Column(String(200))
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    language_id = Column(BigInteger, ForeignKey("language_language.id"), nullable=True)
    birth_date = Column(Date, nullable=True)
    registered_date = Column(Date, nullable=True)
    balance = Column(String, nullable=True)
    face_id = Column(String(200), nullable=True)
    comment = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)


# M2M: Student.subject
student_subjects = Table(
    "students_student_subject",
    TuronBase.metadata,
    Column("student_id", BigInteger, ForeignKey("students_student.id")),
    Column("subject_id", BigInteger, ForeignKey("subjects_subject.id")),
)


class Student(TuronBase):
    __tablename__ = "students_student"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"))
    debt_status = Column(BigInteger, nullable=True)
    class_number_id = Column(BigInteger, ForeignKey("classes_classnumber.id"), nullable=True)
    parents_number = Column(String(250), nullable=True)
    shift = Column(String(50), nullable=True)


class StudentCharity(TuronBase):
    __tablename__ = "students_studentcharity"
    id = Column(BigInteger, primary_key=True)
    charity_sum = Column(Integer, nullable=True)
    name = Column(String(200), nullable=True)
    group_id = Column(BigInteger, ForeignKey("group_group.id"), nullable=True)
    added_data = Column(Date, nullable=True)
    student_id = Column(BigInteger, ForeignKey("students_student.id"), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)


class GroupReason(TuronBase):
    __tablename__ = "group_groupreason"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))


class DeletedStudent(TuronBase):
    __tablename__ = "students_deletedstudent"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger, ForeignKey("students_student.id"))
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    group_reason_id = Column(BigInteger, ForeignKey("group_groupreason.id"), nullable=True)
    deleted_date = Column(Date)
    comment = Column(String(255), nullable=True)
    deleted = Column(Boolean, default=False)


class DeletedNewStudent(TuronBase):
    __tablename__ = "students_deletednewstudent"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger, ForeignKey("students_student.id"))


class StudentExamResult(TuronBase):
    __tablename__ = "students_studentexamresult"
    id = Column(BigInteger, primary_key=True)
    title = Column(String(255))
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    teacher_id = Column(BigInteger, ForeignKey("teachers_teacher.id"))
    student_id = Column(BigInteger, ForeignKey("students_student.id"))
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"))
    score = Column(Integer, nullable=True)
    datetime = Column(DateTime, nullable=True)
    created = Column(DateTime, nullable=True)


# ── Teachers ─────────────────────────────────────────────────────────────────

# M2M: Teacher.subject  -> teachers_teacher_subject
teacher_subjects = Table(
    "teachers_teacher_subject",
    TuronBase.metadata,
    Column("teacher_id", BigInteger, ForeignKey("teachers_teacher.id")),
    Column("subject_id", BigInteger, ForeignKey("subjects_subject.id")),
)

# M2M: Teacher.branches -> teachers_teacher_branches
teacher_branches = Table(
    "teachers_teacher_branches",
    TuronBase.metadata,
    Column("teacher_id", BigInteger, ForeignKey("teachers_teacher.id")),
    Column("branch_id", BigInteger, ForeignKey("branch_branch.id")),
)


# M2M: Group.teacher -> group_group_teacher
group_teachers = Table(
    "group_group_teacher",
    TuronBase.metadata,
    Column("group_id", BigInteger, ForeignKey("group_group.id")),
    Column("teacher_id", BigInteger, ForeignKey("teachers_teacher.id")),
)


class Teacher(TuronBase):
    # teachers app -> teachers_teacher
    __tablename__ = "teachers_teacher"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"))
    color = Column(String(50), nullable=True)
    class_type_id = Column(BigInteger, ForeignKey("classes_classtypes.id"), nullable=True)
    deleted = Column(Boolean, default=False)


class TeacherSalaryType(TuronBase):
    __tablename__ = "teachers_teachersalarytype"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))
    salary = Column(Integer, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    turon_old_id = Column(BigInteger, nullable=True)


class TeacherSalary(TuronBase):
    # teachers app -> teachers_teachersalary
    __tablename__ = "teachers_teachersalary"
    id = Column(BigInteger, primary_key=True)
    month_date = Column(Date)
    total_salary = Column(BigInteger, default=0)
    taken_salary = Column(BigInteger, default=0)
    remaining_salary = Column(BigInteger, default=0)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    teacher_id = Column(BigInteger, ForeignKey("teachers_teacher.id"))


# ── Groups ────────────────────────────────────────────────────────────────────

# M2M association table: Group.students
group_students = Table(
    "group_group_students",
    TuronBase.metadata,
    Column("group_id", BigInteger, ForeignKey("group_group.id")),
    Column("student_id", BigInteger, ForeignKey("students_student.id")),
)


class SubjectLevel(TuronBase):
    __tablename__ = "subjects_subjectlevel"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(250), nullable=False)
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"), nullable=True)
    disabled = Column(Boolean, default=False)
    desc = Column(String, nullable=True)


class Group(TuronBase):
    __tablename__ = "group_group"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=True)
    price = Column(Integer, nullable=True)
    status = Column(Boolean, nullable=True, default=False)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    language_id = Column(BigInteger, ForeignKey("language_language.id"), nullable=True)
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"), nullable=True)
    class_number_id = Column(BigInteger, ForeignKey("classes_classnumber.id"), nullable=True)
    color_id = Column(BigInteger, ForeignKey("classes_classcolors.id"), nullable=True)
    class_type_id = Column(BigInteger, ForeignKey("classes_classtypes.id"), nullable=True)
    deleted = Column(Boolean, default=False)


class GroupSubjects(TuronBase):
    __tablename__ = "group_groupsubjects"
    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"))
    hours = Column(Integer, nullable=True)
    count = Column(Integer, nullable=True)


# ── Flows ─────────────────────────────────────────────────────────────────────

flow_students = Table(
    "flows_flow_students",
    TuronBase.metadata,
    Column("flow_id", BigInteger, ForeignKey("flows_flow.id")),
    Column("student_id", BigInteger, ForeignKey("students_student.id")),
)


class Flow(TuronBase):
    __tablename__ = "flows_flow"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"), nullable=True)
    teacher_id = Column(BigInteger, ForeignKey("teachers_teacher.id"), nullable=True)
    desc = Column(String, nullable=True)
    activity = Column(Boolean, default=False)
    level_id = Column(BigInteger, ForeignKey("subjects_subjectlevel.id"), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    classes = Column(JSON, nullable=True)
    order = Column(Integer, nullable=True)


# ── Terms / Tests ─────────────────────────────────────────────────────────────

class Term(TuronBase):
    __tablename__ = "terms_term"
    id = Column(BigInteger, primary_key=True)
    quarter = Column(Integer)
    start_date = Column(Date)
    end_date = Column(Date)
    academic_year = Column(String(9))


class TermTest(TuronBase):
    __tablename__ = "terms_test"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255))
    weight = Column(Integer)
    term_id = Column(BigInteger, ForeignKey("terms_term.id"))
    date = Column(Date)
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"))
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    class_number_id = Column(BigInteger, ForeignKey("classes_classnumber.id"), nullable=True)
    deleted = Column(Boolean, default=False)


# ── Attendance ────────────────────────────────────────────────────────────────

class StudentMonthlySummary(TuronBase):
    __tablename__ = "attendances_studentmonthlysummary"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger, ForeignKey("students_student.id"))
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    year = Column(Integer)
    month = Column(Integer)
    stats = Column(JSON, default=dict)


class GroupMonthlySummary(TuronBase):
    __tablename__ = "attendances_groupmonthlysummary"
    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    year = Column(Integer)
    month = Column(Integer)
    stats = Column(JSON, default=dict)


class StudentDailyAttendance(TuronBase):
    __tablename__ = "attendances_studentdailyattendance"
    id = Column(BigInteger, primary_key=True)
    monthly_summary_id = Column(BigInteger, ForeignKey("attendances_studentmonthlysummary.id"))
    day = Column(Date)
    status = Column(Boolean, default=False)
    reason = Column(String(255), nullable=True)
    entry_time = Column(DateTime, nullable=True)
    leave_time = Column(DateTime, nullable=True)


class AttendancePerMonth(TuronBase):
    __tablename__ = "attendances_attendancepermonth"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger, ForeignKey("students_student.id"))
    group_id = Column(BigInteger, ForeignKey("group_group.id"))
    month_date = Column(Date)
    total_debt = Column(Integer, default=0)
    remaining_debt = Column(Integer, default=0)
    discount = Column(Integer, default=0)
    status = Column(Boolean, default=False)
    payment = Column(Integer, default=0)
    system_id = Column(BigInteger, ForeignKey("system_system.id"))


# ── Payments ──────────────────────────────────────────────────────────────────

class StudentPayment(TuronBase):
    __tablename__ = "students_studentpayment"
    id = Column(BigInteger, primary_key=True)
    payment_sum = Column(Integer, default=0)
    date = Column(Date)
    status = Column(Boolean)
    deleted = Column(Boolean, default=False)
    payment_type_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    student_id = Column(BigInteger, ForeignKey("students_student.id"))
    attendance_id = Column(BigInteger, ForeignKey("attendances_attendancepermonth.id"))


# ── Salaries ──────────────────────────────────────────────────────────────────

class UserSalary(TuronBase):
    # user app -> user_usersalary (staff monthly salary record)
    __tablename__ = "user_usersalary"
    id = Column(BigInteger, primary_key=True)
    date = Column(Date)
    total_salary = Column(Integer)
    taken_salary = Column(Integer)
    remaining_salary = Column(Integer)
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"))


class TeacherSalaryList(TuronBase):
    __tablename__ = "teachers_teachersalarylist"
    id = Column(BigInteger, primary_key=True)
    salary = Column(Integer, default=0)
    date = Column(Date)
    deleted = Column(Boolean, default=False)
    payment_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))
    salary_id_id = Column(BigInteger, ForeignKey("teachers_teachersalary.id"))
    teacher_id = Column(BigInteger, ForeignKey("teachers_teacher.id"))
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))


class UserSalaryList(TuronBase):
    __tablename__ = "user_usersalarylist"
    id = Column(BigInteger, primary_key=True)
    salary = Column(Integer)
    date = Column(Date)
    deleted = Column(Boolean, default=False)
    payment_types_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))
    user_salary_id = Column(BigInteger, ForeignKey("user_usersalary.id"))
    user_id = Column(BigInteger)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))


# ── Capital ───────────────────────────────────────────────────────────────────

class OldCapital(TuronBase):
    # capital app -> capital_oldcapital
    __tablename__ = "capital_oldcapital"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(500))
    price = Column(Integer)
    added_date = Column(Date)
    deleted = Column(Boolean, default=False)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    payment_type_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))


# ── Books / branch payments ───────────────────────────────────────────────────

class BookOrder(TuronBase):
    # books app -> books_bookorder
    __tablename__ = "books_bookorder"
    id = Column(BigInteger, primary_key=True)
    day = Column(Date)


class BranchPayment(TuronBase):
    # books app -> books_branchpayment
    __tablename__ = "books_branchpayment"
    id = Column(BigInteger, primary_key=True)
    payment_sum = Column(Integer)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    book_order_id = Column(BigInteger, ForeignKey("books_bookorder.id"))
    payment_type_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))


# ── Dividends ─────────────────────────────────────────────────────────────────

class TuronDividend(TuronBase):
    __tablename__ = "dividend"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    management_id = Column(BigInteger, nullable=False, unique=True)
    amount = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    deleted = Column(Boolean, default=False)


# ── Investments ───────────────────────────────────────────────────────────────

class TuronInvestment(TuronBase):
    __tablename__ = "management_investment"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    management_id = Column(BigInteger, nullable=False, unique=True)
    amount = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    payment_type = Column(String(255), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    deleted = Column(Boolean, default=False)


# ── Missions ──────────────────────────────────────────────────────────────────

class TuronMission(TuronBase):
    __tablename__ = "tasks_mission"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    title = Column(String(255))
    description = Column(Text, nullable=True)
    category = Column(String(50))
    creator_id = Column(BigInteger, ForeignKey("user_customuser.id"))
    creator_name = Column(String(255), nullable=True)
    executor_id = Column(BigInteger, ForeignKey("user_customuser.id"))
    reviewer_id = Column(BigInteger, ForeignKey("user_customuser.id"), nullable=True)
    reviewer_name = Column(String(255), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    start_date = Column(Date)
    deadline = Column(Date)
    finish_date = Column(Date, nullable=True)
    status = Column(String(30))
    kpi_weight = Column(Integer, default=10)
    penalty_per_day = Column(Integer, default=2)
    early_bonus_per_day = Column(Integer, default=1)
    max_bonus = Column(Integer, default=3)
    max_penalty = Column(Integer, default=10)
    delay_days = Column(Integer, default=0)
    final_sc = Column(Integer, default=0)
    is_redirected = Column(Boolean, default=False)
    is_recurring = Column(Boolean, default=False)
    repeat_every = Column(Integer, default=1)
    created_at = Column(Date)
    updated_at = Column(Date)


# ── Mission sub-records ───────────────────────────────────────────────────────

class TuronMissionSubtask(TuronBase):
    __tablename__ = "tasks_missionsubtask"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(BigInteger, ForeignKey("tasks_mission.id"))
    title = Column(String(255))
    is_done = Column(Boolean, default=False)
    order = Column(Integer, default=0)
    creator_name = Column(String(255), nullable=True)


class TuronMissionAttachment(TuronBase):
    __tablename__ = "tasks_missionattachment"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(BigInteger, ForeignKey("tasks_mission.id"))
    file = Column(String(500))
    note = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime)
    creator_name = Column(String(255), nullable=True)


class TuronMissionComment(TuronBase):
    __tablename__ = "tasks_missioncomment"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(BigInteger, ForeignKey("tasks_mission.id"))
    user_id = Column(BigInteger, ForeignKey("user_customuser.id"), nullable=True)
    text = Column(Text)
    attachment = Column(String(500), nullable=True)
    created_at = Column(DateTime)
    creator_name = Column(String(255), nullable=True)


class TuronMissionProof(TuronBase):
    __tablename__ = "tasks_missionproof"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(BigInteger, ForeignKey("tasks_mission.id"))
    file = Column(String(500))
    comment = Column(String(255), nullable=True)
    created_at = Column(DateTime)
    creator_name = Column(String(255), nullable=True)


class TuronMissionHistory(TuronBase):
    __tablename__ = "tasks_missionhistory"
    id = Column(BigInteger, primary_key=True)
    management_id = Column(BigInteger, nullable=True, unique=True)
    mission_id = Column(BigInteger, ForeignKey("tasks_mission.id"))
    executor_id = Column(BigInteger, ForeignKey("user_customuser.id"), nullable=True)
    reviewer_id = Column(BigInteger, ForeignKey("user_customuser.id"), nullable=True)
    management_executor_id = Column(BigInteger, nullable=True)
    management_executor_name = Column(String(255), nullable=True)
    management_reviewer_id = Column(BigInteger, nullable=True)
    management_reviewer_name = Column(String(255), nullable=True)
    gennis_executor_id = Column(Integer, nullable=True)
    gennis_executor_name = Column(String(255), nullable=True)
    gennis_reviewer_id = Column(Integer, nullable=True)
    gennis_reviewer_name = Column(String(255), nullable=True)
    changed_by_name = Column(String(255), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=True)


# ── Calendar ──────────────────────────────────────────────────────────────────

class TuronTypeDay(TuronBase):
    __tablename__ = "Calendar_typeday"
    id = Column(BigInteger, primary_key=True)
    type = Column(String(255), nullable=False)
    color = Column(String(255), nullable=False)


class TuronCalendarYear(TuronBase):
    __tablename__ = "Calendar_years"
    id = Column(BigInteger, primary_key=True)
    year = Column(Integer, nullable=False)


class TuronCalendarMonth(TuronBase):
    __tablename__ = "Calendar_month"
    id = Column(BigInteger, primary_key=True)
    month_number = Column(Integer, nullable=False)
    month_name = Column(String(50), nullable=False)
    years_id = Column(BigInteger, ForeignKey("Calendar_years.id"), nullable=False)


class TuronCalendarDay(TuronBase):
    __tablename__ = "Calendar_day"
    id = Column(BigInteger, primary_key=True)
    day_number = Column(Integer, nullable=False)
    day_name = Column(String(50), nullable=False)
    month_id = Column(BigInteger, ForeignKey("Calendar_month.id"), nullable=False)
    year_id = Column(BigInteger, ForeignKey("Calendar_years.id"), nullable=False)
    type_id_id = Column(BigInteger, ForeignKey("Calendar_typeday.id"), nullable=False)


# ── Overheads ─────────────────────────────────────────────────────────────────

class Overhead(TuronBase):
    __tablename__ = "overhead_overhead"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(300))
    price = Column(Integer)
    created = Column(Date)
    deleted = Column(Boolean, default=False)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"))
    type_id = Column(BigInteger, ForeignKey("overhead_overheadtype.id"))
    payment_id = Column(BigInteger, ForeignKey("payments_paymenttypes.id"))


# ── Timetable ─────────────────────────────────────────────────────────────────

class WeekDays(TuronBase):
    __tablename__ = "time_table_weekdays"
    id = Column(BigInteger, primary_key=True)
    name_en = Column(String, nullable=True)
    name_uz = Column(String, nullable=True)
    order = Column(Integer, nullable=True)


class Room(TuronBase):
    __tablename__ = "rooms_room"
    id = Column(BigInteger, primary_key=True)
    name = Column(String(255), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    deleted = Column(Boolean, default=False)
    order = Column(Integer, nullable=True)


class Hours(TuronBase):
    __tablename__ = "school_time_table_hours"
    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=True)
    start_time = Column(String(10), nullable=True)
    end_time = Column(String(10), nullable=True)
    order = Column(Integer, nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)


# M2M: ClassTimeTable.students
classtimetable_students = Table(
    "school_time_table_classtimetable_students",
    TuronBase.metadata,
    Column("classtimetable_id", BigInteger, ForeignKey("school_time_table_classtimetable.id")),
    Column("student_id", BigInteger, ForeignKey("students_student.id")),
)


class ClassTimeTable(TuronBase):
    __tablename__ = "school_time_table_classtimetable"
    id = Column(BigInteger, primary_key=True)
    group_id = Column(BigInteger, ForeignKey("group_group.id"), nullable=True)
    flow_id = Column(BigInteger, ForeignKey("flows_flow.id"), nullable=True)
    week_id = Column(BigInteger, ForeignKey("time_table_weekdays.id"), nullable=True)
    room_id = Column(BigInteger, ForeignKey("rooms_room.id"), nullable=True)
    hours_id = Column(BigInteger, ForeignKey("school_time_table_hours.id"), nullable=True)
    branch_id = Column(BigInteger, ForeignKey("branch_branch.id"), nullable=True)
    teacher_id = Column(BigInteger, ForeignKey("teachers_teacher.id"), nullable=True)
    subject_id = Column(BigInteger, ForeignKey("subjects_subject.id"), nullable=True)
    date = Column(Date, nullable=True)
    name = Column(String, nullable=True)


class TuronCustomUser(TuronBase):
    __tablename__ = "user_customuser"
    __table_args__ = {"extend_existing": True}
    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=True)
    surname = Column(String, nullable=True)


class TuronApiLog(TuronBase):
    __tablename__ = "api_log"
    id = Column(BigInteger, primary_key=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=True)
    user_id = Column(BigInteger, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=True)
