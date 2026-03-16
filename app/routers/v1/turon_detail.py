"""
Detailed per-record views for the Turon school.
Mirrors encashment/views/encashment.py from the Turon project.
No black-salary or assistent-salary — Turon does not have those.
"""
from collections import defaultdict
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, exists, and_, or_, case, select

from ...database import get_turon_db
from ...external_models import turon as T
from typing import List
from ...schemas_stats import (
    BranchItem,
    TuronSchoolStudentsOut, TuronTeacherSalariesOut,
    TuronEmployerSalariesOut, TuronEncashmentOut,
)

router = APIRouter(prefix="/turon", tags=["Turon Detail"])


# ── Branches ──────────────────────────────────────────────────────────────────

@router.get("/branches", response_model=List[BranchItem])
def turon_branches(db: Session = Depends(get_turon_db)):
    """List Turon school branches, excluding Gazalkent and Test."""
    rows = (
        db.query(T.Branch)
        .join(T.Location, T.Location.id == T.Branch.location_id)
        .join(T.System, T.System.id == T.Location.system_id)
        .filter(T.System.name == "school")
        .filter(~T.Branch.name.in_(["Gazalkent"]))
        .order_by(T.Branch.id)
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


# ── helpers ───────────────────────────────────────────────────────────────────

def _dates_for_system(db: Session, system_name: str, date_col) -> list:
    rows = (
        db.query(
            extract("year",  date_col).label("year"),
            extract("month", date_col).label("month"),
        )
        .join(T.System, T.System.id == T.AttendancePerMonth.system_id)
        .filter(T.System.name == system_name)
        .distinct()
        .order_by("year", "month")
        .all()
    )
    ym: dict = defaultdict(list)
    for r in rows:
        ym[int(r.year)].append(int(r.month))
    return [{"year": y, "months": m} for y, m in ym.items()]


def _salary_dates(db: Session, date_col, filter_clause) -> list:
    rows = (
        db.query(
            extract("year",  date_col).label("year"),
            extract("month", date_col).label("month"),
        )
        .filter(filter_clause)
        .distinct()
        .order_by("year", "month")
        .all()
    )
    ym: dict = defaultdict(list)
    for r in rows:
        ym[int(r.year)].append(int(r.month))
    return [{"year": y, "months": m} for y, m in ym.items()]


# ── School students ───────────────────────────────────────────────────────────

@router.get("/school-students", response_model=TuronSchoolStudentsOut)
def turon_school_students(
    branch: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_turon_db),
):
    """
    Per-class student payment breakdown for the school system.
    Mirrors GetSchoolStudents from turon/encashment/views/encashment.py.
    """
    first_day = date(year, month, 1)

    # ── Subquery: student is still active in this group (M2M exists) ──────────
    is_active_sub = (
        select(T.group_students.c.student_id)
        .where(
            and_(
                T.group_students.c.group_id == T.AttendancePerMonth.group_id,
                T.group_students.c.student_id == T.AttendancePerMonth.student_id,
            )
        )
        .correlate(T.AttendancePerMonth)
        .exists()
    )

    # ── Subquery: most recent deleted group for this student this month ────────
    last_deleted_group_sub = (
        select(T.DeletedStudent.group_id)
        .where(
            and_(
                T.DeletedStudent.student_id == T.AttendancePerMonth.student_id,
                T.DeletedStudent.deleted_date >= first_day,
            )
        )
        .correlate(T.AttendancePerMonth)
        .order_by(T.DeletedStudent.id.desc())
        .limit(1)
        .scalar_subquery()
    )

    # ── Main attendance query ─────────────────────────────────────────────────
    rows = (
        db.query(
            T.AttendancePerMonth,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
            T.CustomUser.phone.label("user_phone"),
            T.ClassNumber.number.label("class_number"),
            T.ClassColors.name.label("color_name"),
            T.Group.id.label("group_id"),
        )
        .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .join(T.Group, T.Group.id == T.AttendancePerMonth.group_id)
        .join(T.ClassNumber, T.ClassNumber.id == T.Group.class_number_id)
        .join(T.ClassColors, T.ClassColors.id == T.Group.color_id)
        .filter(
            T.CustomUser.branch_id == branch,
            extract("year",  T.AttendancePerMonth.month_date) == year,
            extract("month", T.AttendancePerMonth.month_date) == month,
        )
        .filter(or_(is_active_sub, T.AttendancePerMonth.group_id == last_deleted_group_sub))
        .order_by(T.ClassNumber.number, T.Group.id, T.CustomUser.surname)
        .all()
    )

    attendance_ids = [r.AttendancePerMonth.id for r in rows]

    # ── Payment aggregates per attendance_id ──────────────────────────────────
    payment_rows = (
        db.query(
            T.StudentPayment.attendance_id,
            func.sum(case((and_(T.PaymentTypes.name == "cash",  T.StudentPayment.status == False), T.StudentPayment.payment_sum), else_=0)).label("cash"),
            func.sum(case((and_(T.PaymentTypes.name == "bank",  T.StudentPayment.status == False), T.StudentPayment.payment_sum), else_=0)).label("bank"),
            func.sum(case((and_(T.PaymentTypes.name == "click", T.StudentPayment.status == False), T.StudentPayment.payment_sum), else_=0)).label("click"),
            func.sum(case((T.StudentPayment.status == True, T.StudentPayment.payment_sum), else_=0)).label("paid"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.StudentPayment.payment_type_id)
        .filter(T.StudentPayment.attendance_id.in_(attendance_ids), T.StudentPayment.deleted == False)
        .group_by(T.StudentPayment.attendance_id)
        .all()
    )

    payments_dict: dict = defaultdict(lambda: {"cash": 0, "bank": 0, "click": 0, "paid": 0})
    for p in payment_rows:
        payments_dict[p.attendance_id] = {
            "cash": p.cash or 0, "bank": p.bank or 0,
            "click": p.click or 0, "paid": p.paid or 0,
        }

    # ── Build per-class structure ─────────────────────────────────────────────
    classes = {}
    total_sum = total_debt = total_remaining = total_donation = total_discount = 0

    for row in rows:
        apm = row.AttendancePerMonth
        class_key = f"{row.class_number}-{row.color_name}"

        if class_key not in classes:
            classes[class_key] = {
                "class_number": class_key,
                "students": [],
                "_order": (row.class_number or 999, row.group_id),
            }

        p = payments_dict[apm.id]
        cash, bank, click, paid = p["cash"], p["bank"], p["click"], p["paid"]
        donation = apm.discount or 0
        debt     = apm.total_debt or 0

        covered   = cash + bank + click + paid + donation
        remaining = max(0, debt - covered)
        payment   = max(0, debt - remaining - donation - paid)

        total_debt      += debt
        total_remaining += remaining
        total_donation  += donation
        total_discount  += paid
        total_sum       += payment

        classes[class_key]["students"].append({
            "id":             apm.student_id,
            "name":           row.user_name,
            "surname":        row.user_surname,
            "phone":          row.user_phone,
            "total_debt":     debt,
            "remaining_debt": remaining,
            "cash":           cash,
            "bank":           bank,
            "click":          click,
            "total_dis":      donation,
            "total_discount": paid,
            "month_id":       apm.id,
        })

    sorted_classes = sorted(
        classes.values(),
        key=lambda x: (
            0 if x["_order"][0] == 0 else (2 if x["_order"][0] == 999 else 1),
            x["_order"][0] if x["_order"][0] != 999 else float("inf"),
            x["_order"][1],
        ),
    )
    for c in sorted_classes:
        del c["_order"]

    dates = _dates_for_system(db, "school", T.AttendancePerMonth.month_date)

    return {
        "class":                sorted_classes,
        "dates":                dates,
        "total_sum":            total_sum,
        "total_debt":           total_debt,
        "reaming_debt":         total_remaining,
        "total_dis":            total_donation,
        "total_discount":       total_discount,
        "total_with_discount":  total_debt - (total_discount + total_donation),
    }


# ── Teacher salaries ──────────────────────────────────────────────────────────

@router.get("/teacher-salaries", response_model=TuronTeacherSalariesOut)
def turon_teacher_salaries(
    branch: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_turon_db),
):
    """
    Per-teacher salary breakdown with cash/bank/click split.
    Mirrors GetTeacherSalary from turon/encashment/views/encashment.py.
    """
    salary_rows = (
        db.query(
            T.TeacherSalary,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
            T.CustomUser.phone.label("user_phone"),
        )
        .join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id)
        .join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id)
        .filter(
            T.CustomUser.branch_id == branch,
            extract("month", T.TeacherSalary.month_date) == month,
            extract("year",  T.TeacherSalary.month_date) == year,
        )
        .all()
    )

    salary_ids = [r.TeacherSalary.id for r in salary_rows]

    # Batch payment breakdown for all salaries at once
    pay_rows = (
        db.query(
            T.TeacherSalaryList.salary_id_id,
            func.sum(case((T.PaymentTypes.name == "cash",  T.TeacherSalaryList.salary), else_=0)).label("cash"),
            func.sum(case((T.PaymentTypes.name == "bank",  T.TeacherSalaryList.salary), else_=0)).label("bank"),
            func.sum(case((T.PaymentTypes.name == "click", T.TeacherSalaryList.salary), else_=0)).label("click"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.TeacherSalaryList.payment_id)
        .filter(
            T.TeacherSalaryList.salary_id_id.in_(salary_ids),
            T.TeacherSalaryList.deleted == False,
        )
        .group_by(T.TeacherSalaryList.salary_id_id)
        .all()
    )
    pay_dict = {r.salary_id_id: {"cash": r.cash or 0, "bank": r.bank or 0, "click": r.click or 0} for r in pay_rows}

    # Batch first subject per teacher
    subj_rows = (
        db.query(
            T.teacher_subjects.c.teacher_id,
            func.min(T.Subject.name).label("subject_name"),
        )
        .join(T.Subject, T.Subject.id == T.teacher_subjects.c.subject_id)
        .filter(T.teacher_subjects.c.teacher_id.in_([r.TeacherSalary.teacher_id for r in salary_rows]))
        .group_by(T.teacher_subjects.c.teacher_id)
        .all()
    )
    subj_dict = {r.teacher_id: r.subject_name for r in subj_rows}

    salary_list = []
    for row in salary_rows:
        s = row.TeacherSalary
        p = pay_dict.get(s.id, {"cash": 0, "bank": 0, "click": 0})
        salary_list.append({
            "id":               s.id,
            "name":             row.user_name,
            "surname":          row.user_surname,
            "phone":            row.user_phone,
            "total_salary":     s.total_salary,
            "taken_salary":     s.taken_salary,
            "remaining_salary": s.remaining_salary,
            "subject":          subj_dict.get(s.teacher_id),
            "cash":             p["cash"],
            "bank":             p["bank"],
            "click":            p["click"],
        })

    date_rows = (
        db.query(
            extract("year",  T.TeacherSalary.month_date).label("year"),
            extract("month", T.TeacherSalary.month_date).label("month"),
        )
        .join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id)
        .join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id)
        .filter(T.CustomUser.branch_id == branch)
        .distinct()
        .order_by("year", "month")
        .all()
    )
    from collections import defaultdict as _dd
    _ym: dict = _dd(list)
    for r in date_rows:
        _ym[int(r.year)].append(int(r.month))
    dates = [{"year": y, "months": m} for y, m in _ym.items()]

    return {"salary": salary_list, "dates": dates, "branch": branch}


# ── Employer (staff) salaries ─────────────────────────────────────────────────

@router.get("/employer-salaries", response_model=TuronEmployerSalariesOut)
def turon_employer_salaries(
    branch: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_turon_db),
):
    """
    Per-staff salary breakdown with cash/bank/click split.
    Mirrors GetEMployerSalary from turon/encashment/views/encashment.py.
    """
    salary_rows = (
        db.query(
            T.UserSalary,
            T.CustomUser.name.label("user_name"),
            T.CustomUser.surname.label("user_surname"),
            T.CustomUser.phone.label("user_phone"),
        )
        .join(T.CustomUser, T.CustomUser.id == T.UserSalary.user_id)
        .filter(
            T.CustomUser.branch_id == branch,
            extract("month", T.UserSalary.date) == month,
            extract("year",  T.UserSalary.date) == year,
        )
        .all()
    )

    salary_ids = [r.UserSalary.id for r in salary_rows]

    # Batch payment breakdown
    pay_rows = (
        db.query(
            T.UserSalaryList.user_salary_id,
            func.sum(case((T.PaymentTypes.name == "cash",  T.UserSalaryList.salary), else_=0)).label("cash"),
            func.sum(case((T.PaymentTypes.name == "bank",  T.UserSalaryList.salary), else_=0)).label("bank"),
            func.sum(case((T.PaymentTypes.name == "click", T.UserSalaryList.salary), else_=0)).label("click"),
        )
        .join(T.PaymentTypes, T.PaymentTypes.id == T.UserSalaryList.payment_types_id)
        .filter(
            T.UserSalaryList.user_salary_id.in_(salary_ids),
            T.UserSalaryList.deleted == False,
        )
        .group_by(T.UserSalaryList.user_salary_id)
        .all()
    )
    pay_dict = {r.user_salary_id: {"cash": r.cash or 0, "bank": r.bank or 0, "click": r.click or 0} for r in pay_rows}

    salary_list = []
    for row in salary_rows:
        s = row.UserSalary
        p = pay_dict.get(s.id, {"cash": 0, "bank": 0, "click": 0})
        salary_list.append({
            "id":               s.id,
            "name":             row.user_name,
            "surname":          row.user_surname,
            "phone":            row.user_phone,
            "total_salary":     s.total_salary,
            "taken_salary":     s.taken_salary,
            "remaining_salary": s.remaining_salary,
            "cash":             p["cash"],
            "bank":             p["bank"],
            "click":            p["click"],
        })

    dates = _salary_dates(
        db, T.UserSalary.date,
        T.CustomUser.branch_id == branch,
    )

    return {"salary": salary_list, "dates": dates, "branch": branch}


# ── Encashment school (full report by payment type) ────────────────────────────

@router.get("/encashment", response_model=TuronEncashmentOut)
def turon_encashment(
    branch: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    db: Session = Depends(get_turon_db),
):
    """
    Full encashment report broken down by payment type.
    Mirrors EncashmentsSchool from turon/encashment/views/encashment.py.
    """
    # ── Totals (payment-type independent) ─────────────────────────────────────
    apm_filter = and_(
        T.AttendancePerMonth.student_id == T.Student.id,
        extract("year",  T.AttendancePerMonth.month_date) == year,
        extract("month", T.AttendancePerMonth.month_date) == month,
    )

    student_totals = (
        db.query(
            func.coalesce(func.sum(T.AttendancePerMonth.remaining_debt), 0).label("remaining_debt"),
            func.coalesce(func.sum(T.AttendancePerMonth.total_debt),     0).label("total_debt"),
        )
        .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
        .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
        .filter(T.CustomUser.branch_id == branch, apm_filter)
        .one()
    )

    teacher_totals = (
        db.query(
            func.coalesce(func.sum(T.TeacherSalary.remaining_salary), 0).label("remaining"),
            func.coalesce(func.sum(T.TeacherSalary.total_salary),     0).label("total"),
        )
        .join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id)
        .join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id)
        .filter(
            T.CustomUser.branch_id == branch,
            extract("month", T.TeacherSalary.month_date) == month,
            extract("year",  T.TeacherSalary.month_date) == year,
        )
        .one()
    )

    user_totals = (
        db.query(
            func.coalesce(func.sum(T.UserSalary.remaining_salary), 0).label("remaining"),
            func.coalesce(func.sum(T.UserSalary.total_salary),     0).label("total"),
        )
        .join(T.CustomUser, T.CustomUser.id == T.UserSalary.user_id)
        .filter(
            T.CustomUser.branch_id == branch,
            extract("month", T.UserSalary.date) == month,
            extract("year",  T.UserSalary.date) == year,
        )
        .one()
    )

    # ── Per payment-type breakdown ─────────────────────────────────────────────
    payment_types = db.query(T.PaymentTypes).all()

    overhead_type_names = ["Gaz", "Svet", "Suv", "Arenda", "Oshxona uchun", "Reklama uchun", "Boshqa"]

    info = {
        "student":  {"remaining_debt": student_totals.remaining_debt, "total_debt": student_totals.total_debt, "payments": []},
        "teacher":  {"remaining_salary": teacher_totals.remaining,    "total_salary": teacher_totals.total,    "salaries": []},
        "user":     {"remaining_salary": user_totals.remaining,        "total_salary": user_totals.total,       "salaries": []},
        "overhead": [],
        "capital":  [],
        "total":    [],
    }
    payment_results = []
    overall_total = 0

    for pt in payment_types:
        # students
        s_pay = (
            db.query(func.coalesce(func.sum(T.StudentPayment.payment_sum), 0))
            .join(T.Student, T.Student.id == T.StudentPayment.student_id)
            .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
            .filter(
                T.CustomUser.branch_id == branch,
                T.StudentPayment.payment_type_id == pt.id,
                T.StudentPayment.deleted == False,
                T.StudentPayment.status == True,
                extract("month", T.StudentPayment.date) == month,
                extract("year",  T.StudentPayment.date) == year,
            )
            .scalar() or 0
        )
        s_debt = (
            db.query(func.coalesce(func.sum(T.AttendancePerMonth.total_debt), 0))
            .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
            .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
            .filter(
                T.CustomUser.branch_id == branch,
                extract("month", T.AttendancePerMonth.month_date) == month,
                extract("year",  T.AttendancePerMonth.month_date) == year,
            )
            .scalar() or 0
        )
        s_remaining = (
            db.query(func.coalesce(func.sum(T.AttendancePerMonth.remaining_debt), 0))
            .join(T.Student, T.Student.id == T.AttendancePerMonth.student_id)
            .join(T.CustomUser, T.CustomUser.id == T.Student.user_id)
            .filter(
                T.CustomUser.branch_id == branch,
                extract("month", T.AttendancePerMonth.month_date) == month,
                extract("year",  T.AttendancePerMonth.month_date) == year,
            )
            .scalar() or 0
        )

        # teachers
        t_total     = db.query(func.coalesce(func.sum(T.TeacherSalary.total_salary),     0)).join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id).join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id).filter(T.CustomUser.branch_id == branch, extract("month", T.TeacherSalary.month_date) == month, extract("year", T.TeacherSalary.month_date) == year).scalar() or 0
        t_remaining = db.query(func.coalesce(func.sum(T.TeacherSalary.remaining_salary), 0)).join(T.Teacher, T.Teacher.id == T.TeacherSalary.teacher_id).join(T.CustomUser, T.CustomUser.id == T.Teacher.user_id).filter(T.CustomUser.branch_id == branch, extract("month", T.TeacherSalary.month_date) == month, extract("year", T.TeacherSalary.month_date) == year).scalar() or 0
        t_taken    = (
            db.query(func.coalesce(func.sum(T.TeacherSalaryList.salary), 0))
            .join(T.PaymentTypes, T.PaymentTypes.id == T.TeacherSalaryList.payment_id)
            .filter(
                T.TeacherSalaryList.branch_id == branch,
                T.TeacherSalaryList.payment_id == pt.id,
                T.TeacherSalaryList.deleted == False,
                extract("month", T.TeacherSalaryList.date) == month,
                extract("year",  T.TeacherSalaryList.date) == year,
            )
            .scalar() or 0
        )

        # workers
        u_total    = db.query(func.coalesce(func.sum(T.UserSalary.total_salary),     0)).join(T.CustomUser, T.CustomUser.id == T.UserSalary.user_id).filter(T.CustomUser.branch_id == branch, extract("month", T.UserSalary.date) == month, extract("year", T.UserSalary.date) == year).scalar() or 0
        u_remaining = db.query(func.coalesce(func.sum(T.UserSalary.remaining_salary), 0)).join(T.CustomUser, T.CustomUser.id == T.UserSalary.user_id).filter(T.CustomUser.branch_id == branch, extract("month", T.UserSalary.date) == month, extract("year", T.UserSalary.date) == year).scalar() or 0
        u_taken    = (
            db.query(func.coalesce(func.sum(T.UserSalaryList.salary), 0))
            .filter(
                T.UserSalaryList.branch_id == branch,
                T.UserSalaryList.payment_types_id == pt.id,
                T.UserSalaryList.deleted == False,
                extract("month", T.UserSalaryList.date) == month,
                extract("year",  T.UserSalaryList.date) == year,
            )
            .scalar() or 0
        )

        # branch payments (books)
        branch_pay = (
            db.query(func.coalesce(func.sum(T.BranchPayment.payment_sum), 0))
            .join(T.BookOrder, T.BookOrder.id == T.BranchPayment.book_order_id)
            .filter(
                T.BranchPayment.branch_id == branch,
                T.BranchPayment.payment_type_id == pt.id,
                extract("month", T.BookOrder.day) == month,
                extract("year",  T.BookOrder.day) == year,
            )
            .scalar() or 0
        )

        # overheads by type
        overhead_totals = {}
        for oh_name in overhead_type_names:
            key = oh_name.lower().replace(" ", "_")
            val = (
                db.query(func.coalesce(func.sum(T.Overhead.price), 0))
                .join(T.OverheadType, T.OverheadType.id == T.Overhead.type_id)
                .filter(
                    T.Overhead.branch_id == branch,
                    T.Overhead.payment_id == pt.id,
                    T.Overhead.deleted == False,
                    T.OverheadType.name == oh_name,
                    extract("month", T.Overhead.created) == month,
                    extract("year",  T.Overhead.created) == year,
                )
                .scalar() or 0
            )
            overhead_totals[key] = val
        total_overhead = sum(overhead_totals.values())

        # capital
        capital_total = (
            db.query(func.coalesce(func.sum(T.OldCapital.price), 0))
            .filter(
                T.OldCapital.branch_id == branch,
                T.OldCapital.payment_type_id == pt.id,
                T.OldCapital.deleted == False,
                extract("month", T.OldCapital.added_date) == month,
                extract("year",  T.OldCapital.added_date) == year,
            )
            .scalar() or 0
        )

        payment_total = s_pay - (t_taken + u_taken + capital_total + total_overhead)
        overall_total += payment_total

        payment_results.append({
            "payment_type": pt.name,
            "students": {"student_total_payment": s_pay, "total_debt": s_debt, "remaining_debt": s_remaining},
            "teachers": {"taken": t_taken, "remaining_salary": t_remaining, "total_salary": t_total},
            "workers":  {"taken": u_taken, "remaining_salary": u_remaining, "total_salary": u_total},
            "branch":   {"branch_total_payment": branch_pay},
            "overheads": {"total_overhead_payment": total_overhead, **overhead_totals},
            "capitals":  {"total_capital": capital_total},
            "payment_total": payment_total,
        })

        info["student"]["payments"].append({"payment_type": pt.name, "student_total_payment": s_pay})
        info["teacher"]["salaries"].append({"payment_type": pt.name, "teacher_total_salary": t_total})
        info["user"]["salaries"].append({"payment_type": pt.name, "worker_total_salary": u_total})
        info["overhead"].append({"payment_type": pt.name, "total_overhead_payment": total_overhead})
        info["capital"].append({"payment_type": pt.name, "total_capital": capital_total})
        info["total"].append({"payment_type": pt.name, "payment_total": payment_total})

    dates = _salary_dates(
        db, T.UserSalary.date,
        T.CustomUser.branch_id == branch,
    )

    return {
        "payment_results": payment_results,
        "summary":         info,
        "overall_total":   overall_total,
        "dates":           dates,
    }
