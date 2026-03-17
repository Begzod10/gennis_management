"""
Detailed per-record views for the Gennis education center.
Mirrors account/overal_datas/home_screen.py from the Gennis project.
"""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ...database import get_gennis_db
from ...external_models import gennis as G
from typing import List, Optional, Union
from ...schemas_stats import (
    BranchItem,
    GennisDebtorsOut,
    GennisTeacherSalariesOut, GennisAssistentSalariesOut, GennisStaffSalariesOut,
    GennisOverheadDetailOut,
)

router = APIRouter(prefix="/gennis", tags=["Gennis Detail"])


# ── Branches ──────────────────────────────────────────────────────────────────

@router.get("/branches", response_model=List[BranchItem])
def gennis_branches(db: Session = Depends(get_gennis_db)):
    """List all Gennis locations (branches)."""
    rows = db.query(G.Locations).order_by(G.Locations.id).all()
    return [{"id": r.id, "name": r.name} for r in rows]


# ── People lists ─────────────────────────────────────────────────────────────

@router.get("/directors")
def gennis_directors(
    location_id: Optional[int] = Query(None),
    db: Session = Depends(get_gennis_db),
):
    """List active Gennis managers (Staff with profession 'manager'),
    optionally filtered by location."""
    q = (
        db.query(G.Staff, G.Users, G.GennisProfessions, G.GennisRoles, G.EducationLanguage, G.Locations)
        .join(G.Users, G.Staff.user_id == G.Users.id)
        .join(G.GennisProfessions, G.Staff.profession_id == G.GennisProfessions.id)
        .join(G.Locations, G.Users.location_id == G.Locations.id)
        .outerjoin(G.GennisRoles, G.Users.role_id == G.GennisRoles.id)
        .outerjoin(G.EducationLanguage, G.Users.education_language == G.EducationLanguage.id)
        .filter(
            G.GennisProfessions.name.ilike("manager"),
            or_(G.Staff.deleted == False, G.Staff.deleted == None),
            or_(G.Users.deleted == False, G.Users.deleted == None),
        )
    )
    if location_id:
        q = q.filter(G.Users.location_id == location_id)
    rows = q.order_by(G.Users.name).all()
    return [
        {
            "id": user.id,
            "name": user.name.title() if user.name else None,
            "surname": user.surname.title() if user.surname else None,
            "username": user.username,
            "age": user.age,
            "job": profession.name,
            "language": lang.name if lang else None,
            "role": role.role if role else None,
            "type_role": role.type_role if role else None,
            "location_id": user.location_id,
            "location_name": location.name,
        }
        for staff, user, profession, role, lang, location in rows
    ]

@router.get("/teachers")
def gennis_teachers(
    location_id: Optional[int] = Query(None),
    db: Session = Depends(get_gennis_db),
):
    """List all active teachers in Gennis, optionally filtered by location."""
    q = (
        db.query(G.Teachers, G.Users)
        .join(G.Users, G.Teachers.user_id == G.Users.id)
        .outerjoin(G.DeletedTeachers, G.Teachers.id == G.DeletedTeachers.teacher_id)
        .filter(G.DeletedTeachers.id == None)
    )
    if location_id:
        q = q.filter(G.Users.location_id == location_id)
    rows = q.order_by(G.Users.name).all()
    return [
        {
            "id": teacher.id,
            "user_id": user.id,
            "name": user.name,
            "surname": user.surname,
            "location_id": user.location_id,
        }
        for teacher, user in rows
    ]


@router.get("/staff")
def gennis_staff(
    location_id: Optional[int] = Query(None),
    db: Session = Depends(get_gennis_db),
):
    """List all active staff/workers in Gennis, optionally filtered by location."""
    q = (
        db.query(G.Staff, G.Users, G.GennisProfessions, G.GennisRoles, G.EducationLanguage)
        .join(G.Users, G.Staff.user_id == G.Users.id)
        .join(G.GennisProfessions, G.Staff.profession_id == G.GennisProfessions.id)
        .outerjoin(G.GennisRoles, G.Users.role_id == G.GennisRoles.id)
        .outerjoin(G.EducationLanguage, G.Users.education_language == G.EducationLanguage.id)
        .filter(or_(G.Staff.deleted == False, G.Staff.deleted == None))
    )
    if location_id:
        q = q.filter(G.Users.location_id == location_id)
    rows = q.order_by(G.Users.name).all()
    return [
        {
            "id": user.id,
            "name": user.name.title() if user.name else None,
            "surname": user.surname.title() if user.surname else None,
            "username": user.username,
            "age": user.age,
            "job": profession.name,
            "language": lang.name if lang else None,
            "role": role.role if role else None,
            "type_role": role.type_role if role else None,
            "location_id": user.location_id,
        }
        for staff, user, profession, role, lang in rows
    ]


# ── Employees ─────────────────────────────────────────────────────────────────

@router.get("/employees/{location_id}")
def gennis_employees(
    location_id: int,
    status: Optional[str] = Query(None, description="Pass 'deleted' to list deleted staff"),
    search: Optional[str] = Query(None),
    job: Optional[str] = Query(None, description="Filter by profession name"),
    language: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(50, ge=1),
    db: Session = Depends(get_gennis_db),
):
    """List staff/employees for a Gennis location. Mirrors /api/account/employees/<location_id>."""
    deleted_filter = G.Staff.deleted == True if status == "deleted" else or_(G.Staff.deleted == False, G.Staff.deleted == None)

    q = (
        db.query(G.Staff, G.Users, G.GennisProfessions, G.GennisRoles, G.EducationLanguage)
        .join(G.Users, G.Staff.user_id == G.Users.id)
        .join(G.GennisProfessions, G.Staff.profession_id == G.GennisProfessions.id)
        .outerjoin(G.GennisRoles, G.Users.role_id == G.GennisRoles.id)
        .outerjoin(G.EducationLanguage, G.Users.education_language == G.EducationLanguage.id)
        .filter(
            G.Users.location_id == location_id,
            deleted_filter,
        )
        .order_by(G.Users.id)
    )

    if job:
        q = q.filter(G.GennisProfessions.name == job)
    if language:
        q = q.filter(G.EducationLanguage.name.ilike(language))
    if search:
        pattern = f"%{search}%"
        q = q.filter(or_(
            G.Users.name.ilike(pattern),
            G.Users.surname.ilike(pattern),
            G.Users.username.ilike(pattern),
        ))

    total = q.count()
    rows = q.offset(offset).limit(limit).all()

    data = [
        {
            "id": user.id,
            "name": user.name.title() if user.name else None,
            "surname": user.surname.title() if user.surname else None,
            "username": user.username,
            "age": user.age,
            "job": profession.name,
            "language": lang.name if lang else None,
            "role": role.role if role else None,
            "type_role": role.type_role if role else None,
        }
        for staff, user, profession, role, lang in rows
    ]

    return {
        "data": data,
        "pagination": {
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total,
        },
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_month_year(db: Session, month: int, year: int):
    """Return (month_id, year_id) from the Gennis calendar tables."""
    year_obj = datetime.strptime(str(year), "%Y")
    month_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")

    year_row = db.query(G.CalendarYear).filter(G.CalendarYear.date == year_obj).first()
    if not year_row:
        raise HTTPException(status_code=404, detail=f"Calendar year {year} not found")

    month_row = (
        db.query(G.CalendarMonth)
        .filter(
            G.CalendarMonth.date == month_obj,
            G.CalendarMonth.year_id == year_row.id,
        )
        .first()
    )
    if not month_row:
        raise HTTPException(status_code=404, detail=f"Calendar month {year}-{month} not found")

    return month_row.id, year_row.id


# ── Debtors ───────────────────────────────────────────────────────────────────

@router.get("/debtors", response_model=GennisDebtorsOut)
def gennis_debtors(
    location_id: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_gennis_db),
):
    month_id, year_id = _resolve_month_year(db, month, year)
    month_date_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")

    # ── Attendance records ────────────────────────────────────────────────────
    attendance_records = (
        db.query(
            G.AttendanceHistoryStudent,
            G.Students,
            G.Users,
            G.Groups,
            G.Subjects,
        )
        .join(G.Students, G.AttendanceHistoryStudent.student_id == G.Students.id)
        .join(G.Users, G.Students.user_id == G.Users.id)
        .join(G.Groups, G.AttendanceHistoryStudent.group_id == G.Groups.id)
        .join(G.Subjects, G.Groups.subject_id == G.Subjects.id)
        .filter(
            G.AttendanceHistoryStudent.calendar_month == month_id,
            G.AttendanceHistoryStudent.calendar_year == year_id,
            G.Users.location_id == location_id,
        )
        .order_by(G.Students.id)
        .all()
    )

    student_ids = [r[1].id for r in attendance_records]

    # ── Deleted students info (batch) ─────────────────────────────────────────
    deleted_rows = (
        db.query(G.DeletedStudents.student_id, G.CalendarDay.date)
        .join(G.CalendarDay, G.DeletedStudents.calendar_day == G.CalendarDay.id)
        .filter(G.DeletedStudents.student_id.in_(student_ids))
        .all()
    )
    deleted_students_info = {row.student_id: row.date for row in deleted_rows}

    # ── Discounts per student (batch) ─────────────────────────────────────────
    discount_rows = (
        db.query(G.StudentPayments.student_id, G.StudentPayments.payment_sum)
        .filter(
            G.StudentPayments.student_id.in_(student_ids),
            G.StudentPayments.calendar_month == month_id,
            G.StudentPayments.calendar_year == year_id,
            G.StudentPayments.location_id == location_id,
            G.StudentPayments.payment == False,
        )
        .all()
    )
    discounts_by_student: dict = defaultdict(int)
    for row in discount_rows:
        discounts_by_student[row.student_id] += row.payment_sum or 0

    # ── Build response ────────────────────────────────────────────────────────
    students_dict = {}
    total_debt = payment = total_discount = total_first_discount = 0

    for attendance, student, user, group, subject in attendance_records:
        for_student_total_discount = discounts_by_student[student.id]
        total_first_discount += for_student_total_discount

        if student.id not in students_dict:
            deletion_date = deleted_students_info.get(student.id)
            students_dict[student.id] = {
                "id": student.id,
                "student_name": f"{user.name} {user.surname}",
                "month": month_date_obj.strftime("%Y-%m"),
                "is_deleted": student.id in deleted_students_info,
                "deleted_date": deletion_date.strftime("%Y-%m-%d") if deletion_date else None,
                "groups": [],
            }

        total_debt    += attendance.total_debt     or 0
        payment       += attendance.payment        or 0
        total_discount += attendance.total_discount or 0

        students_dict[student.id]["groups"].append({
            "group_name":               group.name,
            "subject_name":             subject.name,
            "remaining_debt":           attendance.remaining_debt   or 0,
            "total_debt":               attendance.total_debt       or 0,
            "payment":                  attendance.payment          or 0,
            "total_discount":           attendance.total_discount   or 0,
            "for_student_total_discount": for_student_total_discount,
        })

    return {
        "student_list":        list(students_dict.values()),
        "total_debt":          total_debt,
        "remaining_debt":      total_debt - payment,
        "payment":             payment,
        "total_discount":      total_discount,
        "total_first_discount": total_first_discount,
    }


# ── Salaries ──────────────────────────────────────────────────────────────────

@router.get("/salaries", response_model=Union[GennisTeacherSalariesOut, GennisAssistentSalariesOut, GennisStaffSalariesOut])
def gennis_salaries(
    location_id: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    type_salary: str = Query(..., pattern="^(teacher|assistent|staff)$"),
    db: Session = Depends(get_gennis_db),
):
    month_id, year_id = _resolve_month_year(db, month, year)
    month_date_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")

    # ── Teacher ───────────────────────────────────────────────────────────────
    if type_salary == "teacher":
        salary_records = (
            db.query(
                G.TeacherSalary,
                G.Teachers,
                G.Users,
                G.CalendarMonth,
                G.CalendarYear,
                G.DeletedTeachers,
            )
            .join(G.Teachers, G.TeacherSalary.teacher_id == G.Teachers.id)
            .join(G.Users, G.Teachers.user_id == G.Users.id)
            .join(G.CalendarMonth, G.TeacherSalary.calendar_month == G.CalendarMonth.id)
            .join(G.CalendarYear, G.CalendarMonth.year_id == G.CalendarYear.id)
            .outerjoin(G.DeletedTeachers, G.Teachers.id == G.DeletedTeachers.teacher_id)
            .filter(
                G.TeacherSalary.calendar_month == month_id,
                G.TeacherSalary.calendar_year == year_id,
                G.Users.location_id == location_id,
                G.TeacherSalary.location_id == location_id,
                or_(
                    G.DeletedTeachers.id == None,
                    G.CalendarMonth.date > month_date_obj,
                ),
            )
            .all()
        )

        teacher_ids = [r[1].id for r in salary_records]

        # batch-fetch black salaries for this month
        black_rows = (
            db.query(G.TeacherBlackSalary.teacher_id, G.TeacherBlackSalary.total_salary)
            .filter(
                G.TeacherBlackSalary.teacher_id.in_(teacher_ids),
                G.TeacherBlackSalary.calendar_month == month_id,
                G.TeacherBlackSalary.location_id == location_id,
                G.TeacherBlackSalary.status == False,
            )
            .all()
        )
        black_by_teacher: dict = defaultdict(int)
        for row in black_rows:
            black_by_teacher[row.teacher_id] += row.total_salary or 0

        salary_dict = {}
        total_salary = total_taken = total_black = total_debt = total_fine = total_remaining = 0

        for salary, teacher, user, cal_month, cal_year, deleted_teacher in salary_records:
            black_salary = black_by_teacher[teacher.id]
            debt        = salary.debt       or 0
            taken_money = salary.taken_money or 0
            fine        = salary.total_fine  or 0
            remaining   = salary.total_salary - (taken_money + black_salary + fine - debt)

            salary_dict[teacher.id] = {
                "id":               teacher.id,
                "teacher_name":     f"{user.name} {user.surname}",
                "month":            month_date_obj.strftime("%Y-%m"),
                "is_deleted":       deleted_teacher is not None,
                "deleted_date":     cal_year.date.strftime("%Y-%m") if deleted_teacher else None,
                "teacher_salary":   salary.total_salary,
                "taken_money":      taken_money,
                "remaining_salary": remaining,
                "black_salary":     black_salary,
                "debt":             debt,
                "fine":             fine,
            }
            total_remaining += remaining
            total_fine      += fine
            total_debt      += debt
            total_black     += black_salary
            total_salary    += salary.total_salary
            total_taken     += taken_money

        return {
            "salary_list":        list(salary_dict.values()),
            "total_salary":       total_salary,
            "taken_money":        total_taken,
            "remaining_salary":   total_remaining,
            "black_salary":       total_black,
            "debt":               total_debt,
            "fine":               total_fine,
        }

    # ── Assistent ─────────────────────────────────────────────────────────────
    elif type_salary == "assistent":
        salary_records = (
            db.query(
                G.AssistentSalary,
                G.Assistent,
                G.Users,
                G.CalendarMonth,
                G.CalendarYear,
            )
            .join(G.Assistent, G.AssistentSalary.assisten_id == G.Assistent.id)
            .join(G.Users, G.Assistent.user_id == G.Users.id)
            .join(G.CalendarMonth, G.AssistentSalary.calendar_month == G.CalendarMonth.id)
            .join(G.CalendarYear, G.CalendarMonth.year_id == G.CalendarYear.id)
            .filter(
                G.AssistentSalary.calendar_month == month_id,
                G.AssistentSalary.calendar_year == year_id,
                G.Users.location_id == location_id,
                G.AssistentSalary.location_id == location_id,
                or_(
                    G.Assistent.deleted == False,
                    G.Assistent.deleted == None,
                    and_(
                        G.Assistent.deleted == True,
                        G.CalendarMonth.date > month_date_obj,
                    ),
                ),
            )
            .all()
        )

        assistent_ids = [r[1].id for r in salary_records]

        black_rows = (
            db.query(G.AssistentBlackSalary.assistent_id, G.AssistentBlackSalary.total_salary)
            .filter(
                G.AssistentBlackSalary.assistent_id.in_(assistent_ids),
                G.AssistentBlackSalary.calendar_month == month_id,
                G.AssistentBlackSalary.location_id == location_id,
                G.AssistentBlackSalary.status == False,
            )
            .all()
        )
        black_by_assistent: dict = defaultdict(int)
        for row in black_rows:
            black_by_assistent[row.assistent_id] += row.total_salary or 0

        salary_dict = {}
        total_salary = total_taken = total_black = total_debt = total_fine = total_remaining = 0

        for salary, assistent, user, cal_month, cal_year in salary_records:
            black_salary = black_by_assistent[assistent.id]
            debt        = salary.debt       or 0
            taken_money = salary.taken_money or 0
            fine        = salary.total_fine  or 0
            remaining   = salary.total_salary - (taken_money + black_salary + fine - debt)

            salary_dict[assistent.id] = {
                "id":               assistent.id,
                "assistent_name":   f"{user.name} {user.surname}",
                "month":            month_date_obj.strftime("%Y-%m"),
                "is_deleted":       assistent.deleted or False,
                "assistent_salary": salary.total_salary,
                "taken_money":      taken_money,
                "remaining_salary": remaining,
                "black_salary":     black_salary,
                "debt":             debt,
                "fine":             fine,
            }
            total_remaining += remaining
            total_fine      += fine
            total_debt      += debt
            total_black     += black_salary
            total_salary    += salary.total_salary
            total_taken     += taken_money

        return {
            "salary_list":      list(salary_dict.values()),
            "total_salary":     total_salary,
            "taken_money":      total_taken,
            "remaining_salary": total_remaining,
            "black_salary":     total_black,
            "debt":             total_debt,
            "fine":             total_fine,
        }

    # ── Staff ─────────────────────────────────────────────────────────────────
    else:
        salary_records = (
            db.query(
                G.StaffSalary,
                G.Staff,
                G.Users,
                G.CalendarMonth,
                G.CalendarYear,
            )
            .join(G.Staff, G.StaffSalary.staff_id == G.Staff.id)
            .join(G.Users, G.Staff.user_id == G.Users.id)
            .join(G.CalendarMonth, G.StaffSalary.calendar_month == G.CalendarMonth.id)
            .join(G.CalendarYear, G.CalendarMonth.year_id == G.CalendarYear.id)
            .filter(
                G.StaffSalary.calendar_month == month_id,
                G.StaffSalary.calendar_year == year_id,
                G.Users.location_id == location_id,
                or_(
                    G.Staff.deleted == False,
                    G.Staff.deleted == None,
                    and_(
                        G.Staff.deleted == True,
                        G.CalendarMonth.date > month_date_obj,
                    ),
                ),
            )
            .all()
        )

        salary_dict = {}
        total_salary = total_taken = 0

        for salary, staff, user, cal_month, cal_year in salary_records:
            taken_money = salary.taken_money or 0
            if staff.id not in salary_dict:
                salary_dict[staff.id] = {
                    "id":               staff.id,
                    "staff_name":       f"{user.name} {user.surname}",
                    "month":            month_date_obj.strftime("%Y-%m"),
                    "is_deleted":       staff.deleted,
                    "deleted_date":     staff.deleted_date.strftime("%Y-%m") if staff.deleted_date else None,
                    "deleted_comment":  staff.deleted_comment,
                    "staff_salary":     salary.total_salary,
                    "taken_money":      taken_money,
                    "remaining_salary": salary.total_salary - taken_money,
                }
            total_salary += salary.total_salary
            total_taken  += taken_money

        return {
            "salary_list":      list(salary_dict.values()),
            "total_salary":     total_salary,
            "taken_money":      total_taken,
            "remaining_salary": total_salary - total_taken,
        }


# ── Overhead ──────────────────────────────────────────────────────────────────

@router.get("/overhead", response_model=GennisOverheadDetailOut)
def gennis_overhead(
    location_id: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_gennis_db),
):
    month_id, year_id = _resolve_month_year(db, month, year)
    month_date_obj = datetime.strptime(f"{year}-{month:02d}", "%Y-%m")

    all_overheads = (
        db.query(G.Overhead, G.PaymentTypes)
        .join(G.PaymentTypes, G.PaymentTypes.id == G.Overhead.payment_type_id)
        .filter(
            G.Overhead.calendar_month == month_id,
            G.Overhead.calendar_year == year_id,
            G.Overhead.location_id == location_id,
        )
        .all()
    )

    total_gaz = total_svet = total_suv = total_arenda = total_other = 0
    overhead_list = []

    for overhead, payment_type in all_overheads:
        item_sum = overhead.item_sum or 0
        name = (overhead.item_name or "").lower()

        if name == "gaz":       total_gaz    += item_sum
        elif name == "svet":    total_svet   += item_sum
        elif name == "suv":     total_suv    += item_sum
        elif name == "arenda":  total_arenda += item_sum
        else:                   total_other  += item_sum

        overhead_list.append({
            "id":           overhead.id,
            "item_name":    overhead.item_name,
            "item_sum":     item_sum,
            "month":        month_date_obj.strftime("%Y-%m"),
            "payment_type": payment_type.name,
        })

    return {
        "overhead_list": overhead_list,
        "total_gaz":     total_gaz,
        "total_svet":    total_svet,
        "total_suv":     total_suv,
        "total_arenda":  total_arenda,
        "total_other":   total_other,
    }
