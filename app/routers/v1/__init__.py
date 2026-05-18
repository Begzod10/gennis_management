from . import auth
from .accountant import (
    overhead_types,
    dashboard as accountant_dashboard,
    students as accountant_students,
    payments as accountant_payments,
    overheads as accountant_overheads,
    salaries as accountant_salaries,
    debts as accountant_debts,
)

from .management import (
    admin_requests,
    branch_loans,
    branch_transactions,
    overhead_type_logs,
    branches, combined, dividends, investments, jobs,
    missions, mission_attachments, mission_comments,
    mission_proofs, mission_subtasks,
    notifications, projects,
    salary_days, salary_months, sections,
    statistics, system_models, tags, users,
    telegram_bot,
)

from .gennis import detail as gennis_detail

from .turon import (
    calendar, classes as turon_classes, detail as turon_detail,
    students as turon_students, teachers as turon_teachers,
    terms as turon_terms, timetable as turon_timetable,
)
