from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from .database import engine, gennis_write_engine, turon_write_engine
from .external_models.gennis import GennisDividend, GennisInvestment
from .external_models.turon import TuronDividend, TuronInvestment
from .routers.v1 import (
    auth,
    jobs, users, salary_months, salary_days,
    system_models, branches, tags, missions,
    mission_subtasks, mission_attachments, mission_comments, mission_proofs,
    notifications,
    statistics,
    gennis_detail,
    turon_detail,
    dividends,
    investments,
    projects,
    sections,
    combined,
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
        conn.commit()
    with turon_write_engine.connect() as conn:
        conn.execute(text("ALTER TABLE tasks_mission ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionsubtask ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionattachment ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missioncomment ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.execute(text("ALTER TABLE tasks_missionproof ADD COLUMN IF NOT EXISTS management_id BIGINT UNIQUE"))
        conn.commit()

    yield


app = FastAPI(
    title="Gennis Management API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "100.81.196.80:3000"],
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
app.include_router(dividends.router, prefix=V1)
app.include_router(investments.router, prefix=V1)
app.include_router(projects.router, prefix=V1)
app.include_router(sections.router, prefix=V1)
app.include_router(combined.router, prefix=V1)


@app.get("/docs", include_in_schema=False)
def custom_swagger():
    with open("static/swagger-custom.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/")
def root():
    return {"status": "ok", "message": "Gennis Management API"}
