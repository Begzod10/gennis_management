"""
Pydantic response schemas for statistics, gennis_detail, and turon_detail routes.
"""
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


# ── Common ────────────────────────────────────────────────────────────────────

class BranchItem(BaseModel):
    id: int
    name: Optional[str]


class PaymentTypeAmount(BaseModel):
    payment_type: str
    total: int


class ByPaymentType(BaseModel):
    total: int
    by_payment_type: List[PaymentTypeAmount]


class YearMonths(BaseModel):
    year: int
    months: List[int]


# ── Statistics: overheads ─────────────────────────────────────────────────────

class OverheadByItem(BaseModel):
    item: Optional[str]
    total: int


class OverheadByType(BaseModel):
    type: Optional[str]
    total: int


class GennisOverheadSummary(BaseModel):
    total: int
    by_item: List[OverheadByItem]
    by_payment_type: List[PaymentTypeAmount]


class TuronOverheadSummary(BaseModel):
    total: int
    by_overhead_type: List[OverheadByType]
    by_payment_type: List[PaymentTypeAmount]


# ── Statistics: system summaries ──────────────────────────────────────────────

class GennisSummary(BaseModel):
    payments: ByPaymentType
    teacher_salaries: ByPaymentType
    staff_salaries: ByPaymentType
    overheads: GennisOverheadSummary
    dividends: int
    investments: int
    total_expenses: int
    remaining: int


class TuronSummary(BaseModel):
    payments: ByPaymentType
    teacher_salaries: ByPaymentType
    staff_salaries: ByPaymentType
    overheads: TuronOverheadSummary
    dividends: int
    investments: int
    total_expenses: int
    remaining: int


class CombinedStats(BaseModel):
    total_payments: int
    total_teacher_salaries: int
    total_staff_salaries: int
    total_overheads: int
    total_dividends: int
    total_investments: int
    total_expenses: int
    remaining: int


class Period(BaseModel):
    month: Optional[int]
    year: Optional[int]


class OverviewOut(BaseModel):
    period: Period
    gennis: GennisSummary
    turon: TuronSummary
    combined: CombinedStats


# ── Gennis detail: debtors ────────────────────────────────────────────────────

class GennisGroupItem(BaseModel):
    group_name: str
    subject_name: str
    remaining_debt: int
    total_debt: int
    payment: int
    total_discount: int
    for_student_total_discount: int


class GennisStudentDebtor(BaseModel):
    id: int
    student_name: str
    month: str
    is_deleted: bool
    deleted_date: Optional[str]
    groups: List[GennisGroupItem]


class GennisDebtorsOut(BaseModel):
    student_list: List[GennisStudentDebtor]
    total_debt: int
    remaining_debt: int
    payment: int
    total_discount: int
    total_first_discount: int


# ── Gennis detail: salaries ───────────────────────────────────────────────────

class GennisTeacherSalaryItem(BaseModel):
    id: int
    teacher_name: str
    month: str
    is_deleted: bool
    deleted_date: Optional[str]
    teacher_salary: int
    taken_money: int
    remaining_salary: int
    black_salary: int
    debt: int
    fine: int


class GennisTeacherSalariesOut(BaseModel):
    salary_list: List[GennisTeacherSalaryItem]
    total_salary: int
    taken_money: int
    remaining_salary: int
    black_salary: int
    debt: int
    fine: int


class GennisAssistentSalaryItem(BaseModel):
    id: int
    assistent_name: str
    month: str
    is_deleted: bool
    assistent_salary: int
    taken_money: int
    remaining_salary: int
    black_salary: int
    debt: int
    fine: int


class GennisAssistentSalariesOut(BaseModel):
    salary_list: List[GennisAssistentSalaryItem]
    total_salary: int
    taken_money: int
    remaining_salary: int
    black_salary: int
    debt: int
    fine: int


class GennisStaffSalaryItem(BaseModel):
    id: int
    staff_name: str
    month: str
    is_deleted: Optional[bool]
    deleted_date: Optional[str]
    deleted_comment: Optional[str]
    staff_salary: int
    taken_money: int
    remaining_salary: int


class GennisStaffSalariesOut(BaseModel):
    salary_list: List[GennisStaffSalaryItem]
    total_salary: int
    taken_money: int
    remaining_salary: int


# ── Gennis detail: overhead ───────────────────────────────────────────────────

class GennisOverheadItem(BaseModel):
    id: int
    item_name: Optional[str]
    item_sum: int
    month: str
    payment_type: str


class GennisOverheadDetailOut(BaseModel):
    overhead_list: List[GennisOverheadItem]
    total_gaz: int
    total_svet: int
    total_suv: int
    total_arenda: int
    total_other: int


# ── Turon detail: school students ─────────────────────────────────────────────

class TuronClassStudent(BaseModel):
    id: int
    name: Optional[str]
    surname: Optional[str]
    phone: Optional[str]
    total_debt: int
    remaining_debt: int
    cash: int
    bank: int
    click: int
    total_dis: int
    total_discount: int
    month_id: int


class TuronClassGroup(BaseModel):
    class_number: str
    students: List[TuronClassStudent]


class TuronSchoolStudentsOut(BaseModel):
    model_config = {"populate_by_name": True}

    class_: List[TuronClassGroup] = Field(default=[], alias="class")
    dates: List[YearMonths]
    total_sum: int
    total_debt: int
    reaming_debt: int
    total_dis: int
    total_discount: int
    total_with_discount: int


# ── Turon detail: teacher salaries ────────────────────────────────────────────

class TuronTeacherSalaryItem(BaseModel):
    id: int
    name: Optional[str]
    surname: Optional[str]
    phone: Optional[str]
    total_salary: int
    taken_salary: int
    remaining_salary: int
    subject: Optional[str]
    cash: int
    bank: int
    click: int


class TuronTeacherSalariesOut(BaseModel):
    salary: List[TuronTeacherSalaryItem]
    dates: List[YearMonths]
    branch: int


# ── Turon detail: employer salaries ──────────────────────────────────────────

class TuronEmployerSalaryItem(BaseModel):
    id: int
    name: Optional[str]
    surname: Optional[str]
    phone: Optional[str]
    total_salary: Optional[int]
    taken_salary: Optional[int]
    remaining_salary: Optional[int]
    cash: int
    bank: int
    click: int


class TuronEmployerSalariesOut(BaseModel):
    salary: List[TuronEmployerSalaryItem]
    dates: List[YearMonths]
    branch: int


# ── Turon detail: encashment ──────────────────────────────────────────────────

class TuronStudentEncashment(BaseModel):
    student_total_payment: int
    total_debt: int
    remaining_debt: int


class TuronTeacherEncashment(BaseModel):
    taken: int
    remaining_salary: int
    total_salary: int


class TuronWorkerEncashment(BaseModel):
    taken: int
    remaining_salary: int
    total_salary: int


class TuronOverheadEncashment(BaseModel):
    total_overhead_payment: int


class TuronCapitalEncashment(BaseModel):
    total_capital: int


class TuronPaymentResult(BaseModel):
    payment_type: str
    students: TuronStudentEncashment
    teachers: TuronTeacherEncashment
    workers: TuronWorkerEncashment
    branch: Dict[str, int]
    overheads: Dict[str, Any]
    capitals: TuronCapitalEncashment
    payment_total: int


class TuronStudentSummary(BaseModel):
    remaining_debt: int
    total_debt: int
    payments: List[Dict[str, Any]]


class TuronTeacherSummary(BaseModel):
    remaining_salary: int
    total_salary: int
    salaries: List[Dict[str, Any]]


class TuronEncashmentSummary(BaseModel):
    student: TuronStudentSummary
    teacher: TuronTeacherSummary
    user: TuronTeacherSummary
    overhead: List[Dict[str, Any]]
    capital: List[Dict[str, Any]]
    total: List[Dict[str, Any]]


class TuronEncashmentOut(BaseModel):
    payment_results: List[TuronPaymentResult]
    summary: TuronEncashmentSummary
    overall_total: int
    dates: List[YearMonths]
