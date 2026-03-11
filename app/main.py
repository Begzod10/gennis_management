from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from .database import engine
from .routers.v1 import (
    auth,
    jobs, users, salary_months, salary_days,
    system_models, branches, tags, missions,
    mission_subtasks, mission_attachments, mission_comments, mission_proofs,
    notifications,
    statistics,
    gennis_detail,
    turon_detail,
)

app = FastAPI(
    title="Gennis Management API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "100.81.196.80:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

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


@app.get("/docs", include_in_schema=False)
def custom_swagger():
    with open("static/swagger-custom.html", "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/")
def root():
    return {"status": "ok", "message": "Gennis Management API"}
