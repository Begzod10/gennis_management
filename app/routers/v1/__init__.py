from . import auth
from .accountant import overhead_types

from .management import (
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
