"""Admin API for background job management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.scheduler_service import get_jobs_status, pause_job, run_job_now, start_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("")
def list_jobs():
    """Get status of all background jobs."""
    return get_jobs_status()


@router.post("/{job_id}/start")
def start_job_endpoint(job_id: str, interval_minutes: int | None = None):
    """Start/resume a job. Optionally set interval in minutes."""
    try:
        return start_job(job_id, interval_minutes)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{job_id}/pause")
def pause_job_endpoint(job_id: str):
    """Pause a job."""
    try:
        return pause_job(job_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{job_id}/run")
def run_job_now_endpoint(job_id: str):
    """Run a job immediately (one-off)."""
    try:
        return run_job_now(job_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/tracking/check")
def manual_tracking_check(db: Session = Depends(get_db)):
    """Manually trigger tracking check (without scheduler)."""
    from app.services.tracking_service import check_tracking_updates
    return check_tracking_updates(db)
