"""
Read-only SQLAlchemy models mapped to the Gennis education center database.
Only columns needed for statistics are declared.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Text
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

class Users(GennisBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    surname = Column(String)
    location_id = Column(Integer, ForeignKey("locations.id"))


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


class Staff(GennisBase):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
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


# ── Overheads ─────────────────────────────────────────────────────────────────

class Overhead(GennisBase):
    __tablename__ = "overhead"
    id = Column(Integer, primary_key=True)
    item_sum = Column(Integer)
    item_name = Column(String)
    payment_type_id = Column(Integer, ForeignKey("paymenttypes.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    calendar_month = Column(Integer, ForeignKey("calendarmonth.id"))
    calendar_year = Column(Integer, ForeignKey("calendaryear.id"))
