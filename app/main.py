import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from jose import jwt, JWTError
from sqlalchemy import text
from .config import settings
from .database import engine, gennis_write_engine, turon_write_engine, SessionLocal
from .models import ApiLog

_log = logging.getLogger(__name__)
from .external_models.gennis import GennisDividend, GennisInvestment
from .external_models.turon import TuronDividend, TuronInvestment
from .routers.v1 import auth
from .routers.v1.accountant import overhead_types
from .routers.v1.management import (
    jobs, users, salary_months, salary_days,
    system_models, branches, tags, missions,
    mission_subtasks, mission_attachments, mission_comments, mission_proofs,
    notifications, statistics, dividends, investments,
    projects, sections, combined, telegram_bot,
)
from .routers.v1.gennis import detail as gennis_detail
from .routers.v1.turon import (
    calendar, classes as turon_classes, detail as turon_detail,
    students as turon_students, teachers as turon_teachers,
    terms as turon_terms, timetable as turon_timetable,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create management_dividend/investment tables in external DBs if not exist
    GennisDividend.__table__.create(bind=gennis_write_engine, checkfirst=True)
    TuronDividend.__table__.create(bind=turon_write_engine, checkfirst=True)
    GennisInvestment.__table__.create(bind=gennis_write_engine, checkfirst=True)
    TuronInvestment.__table__.create(bind=turon_write_engine, checkfirst=True)

    # Add management_id to Gennis missions table and Turon tasks_mission table
    with gennis_write_engine.connect() as conn:
        conn.execute(text("ALTER TABLE missions ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE missions ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE missions ADD COLUMN IF NOT EXISTS reviewer_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE mission_subtasks ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE mission_subtasks ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE mission_attachments ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE mission_attachments ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE mission_comments ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE mission_comments ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE mission_proofs ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE mission_proofs ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        conn.execute(text("ALTER TABLE overheadtype ADD COLUMN IF NOT EXISTS management_id BIGINT"))
        conn.commit()
    with turon_write_engine.connect() as conn:
        conn.execute(text("ALTER TABLE tasks_mission ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionsubtask ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionattachment ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missioncomment ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionproof ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE overhead_overheadtype ADD COLUMN IF NOT EXISTS management_id BIGINT"))
        conn.execute(text("ALTER TABLE overhead_overheadtype ADD COLUMN IF NOT EXISTS deleted BOOLEAN DEFAULT FALSE"))
        conn.commit()

    yield


app = FastAPI(
    title="Gennis Management API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

_SKIP_LOG_PREFIXES = ("/static", "/uploads", "/docs", "/openapi.json", "/")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if any(path == p or path.startswith(p + "/") for p in ("/static", "/uploads")):
        return await call_next(request)

    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - start) * 1000

    user_id = None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("user_id")
        except JWTError:
            pass

    db = None
    try:
        db = SessionLocal()
        db.add(ApiLog(
            method=request.method,
            path=path,
            status_code=response.status_code,
            user_id=user_id,
            response_time_ms=round(elapsed_ms, 2),
        ))
        db.commit()
    except Exception as e:
        _log.error(f"ApiLog write failed: {e}")
        if db:
            db.rollback()
    finally:
        if db:
            db.close()

    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "100.81.196.80:3000",
                    "https://office.gennis.uz", "https://school.gennis.uz",
                    "https://admin.gennis.uz"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

V1 = "/api/v1"

app.include_router(auth.router, prefix=V1)
app.include_router(jobs.router, prefix=V1)
app.include_router(users.router, prefix=V1)
app.include_router(salary_months.router, prefix=V1)
app.include_router(salary_days.router, prefix=V1)
app.include_router(system_models.router, prefix=V1)
app.include_router(branches.router, prefix=V1)
app.include_router(tags.router, prefix=V1)
app.include_router(missions.router, prefix=V1)
app.include_router(mission_subtasks.router, prefix=V1)
app.include_router(mission_attachments.router, prefix=V1)
app.include_router(mission_comments.router, prefix=V1)
app.include_router(mission_proofs.router, prefix=V1)
app.include_router(notifications.router, prefix=V1)
app.include_router(statistics.router, prefix=V1)
app.include_router(gennis_detail.router, prefix=V1)
app.include_router(turon_detail.router, prefix=V1)
app.include_router(overhead_types.router, prefix=V1)
app.include_router(dividends.router, prefix=V1)
app.include_router(investments.router, prefix=V1)
app.include_router(projects.router, prefix=V1)
app.include_router(sections.router, prefix=V1)
app.include_router(combined.router, prefix=V1)
app.include_router(calendar.router, prefix=V1)
app.include_router(turon_students.router, prefix=V1)
app.include_router(turon_classes.router, prefix=V1)
app.include_router(turon_timetable.router, prefix=V1)
app.include_router(turon_teachers.router, prefix=V1)
app.include_router(turon_terms.router, prefix=V1)
app.include_router(telegram_bot.router, prefix=V1)


@app.get("/docs", include_in_schema=False)
def custom_swagger():
    with open("static/swagger-custom.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/usage", include_in_schema=False)
def usage_dashboard():
    with open("static/usage-dashboard.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/")
def root():
    return {"status": "ok", "message": "Gennis Management API"}
