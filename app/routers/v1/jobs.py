from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ...database import get_db
from ...models import Job
from ...schemas import JobCreate, JobUpdate, JobOut

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/", response_model=JobOut, status_code=201)
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    job = Job(**data.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/", response_model=List[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(Job).filter(Job.deleted == False).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.deleted == False).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: int, data: JobUpdate, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.deleted == False).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.deleted == False).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.deleted = True
    db.commit()
