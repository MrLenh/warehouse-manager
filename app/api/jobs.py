"""Admin API for background job management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.scheduler_service import get_jobs_status, pause_job, revert_last_job, run_job_now, start_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


# --- Existing job endpoints ---

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


@router.post("/{job_id}/revert")
def revert_job_endpoint(job_id: str):
    """Revert the last run of a job, restoring orders to previous states."""
    try:
        return revert_last_job(job_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/tracking/check")
def manual_tracking_check(db: Session = Depends(get_db)):
    """Manually trigger tracking check (without scheduler)."""
    from app.services.tracking_service import check_tracking_updates
    return check_tracking_updates(db)


# --- Custom job CRUD ---

class CustomJobCreate(BaseModel):
    name: str
    description: str = ""
    source_statuses: list[str] = []
    tracking_conditions: list[str] = []
    target_status: str = "shipped"
    require_tracking_number: bool = True
    interval_minutes: int = 30
    enabled: bool = True


class CustomJobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_statuses: list[str] | None = None
    tracking_conditions: list[str] | None = None
    target_status: str | None = None
    require_tracking_number: bool | None = None
    interval_minutes: int | None = None
    enabled: bool | None = None


@router.get("/custom")
def list_custom_jobs_endpoint(db: Session = Depends(get_db)):
    """List all custom job definitions."""
    from app.services.custom_job_service import job_to_dict, list_custom_jobs
    jobs = list_custom_jobs(db)
    return [job_to_dict(j) for j in jobs]


@router.post("/custom")
def create_custom_job_endpoint(data: CustomJobCreate, db: Session = Depends(get_db)):
    """Create a new custom job and register it in the scheduler."""
    from app.services.custom_job_service import create_custom_job, job_to_dict
    from app.services.scheduler_service import register_custom_job

    job = create_custom_job(db, data.model_dump())

    # Register in scheduler
    if job.enabled:
        register_custom_job(job.id, job.name, job.interval_minutes, start_paused=True)

    return job_to_dict(job)


@router.get("/custom/{job_id}")
def get_custom_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    """Get a custom job definition."""
    from app.services.custom_job_service import get_custom_job, job_to_dict
    job = get_custom_job(db, job_id)
    if not job:
        raise HTTPException(404, "Custom job not found")
    return job_to_dict(job)


@router.patch("/custom/{job_id}")
def update_custom_job_endpoint(job_id: str, data: CustomJobUpdate, db: Session = Depends(get_db)):
    """Update a custom job definition and re-register in scheduler."""
    from app.services.custom_job_service import get_custom_job, job_to_dict, update_custom_job
    from app.services.scheduler_service import register_custom_job, unregister_custom_job

    update_data = data.model_dump(exclude_none=True)
    try:
        job = update_custom_job(db, job_id, update_data)
    except ValueError as e:
        raise HTTPException(404, str(e))

    # Re-register in scheduler with updated config
    unregister_custom_job(job_id)
    if job.enabled:
        register_custom_job(job.id, job.name, job.interval_minutes, start_paused=True)

    return job_to_dict(job)


@router.delete("/custom/{job_id}")
def delete_custom_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    """Delete a custom job and remove from scheduler."""
    from app.services.custom_job_service import delete_custom_job
    from app.services.scheduler_service import unregister_custom_job

    unregister_custom_job(job_id)
    if not delete_custom_job(db, job_id):
        raise HTTPException(404, "Custom job not found")

    return {"status": "deleted", "id": job_id}


@router.post("/custom/{job_id}/run")
def run_custom_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    """Run a custom job immediately (one-off, without scheduler)."""
    from app.services.custom_job_service import execute_custom_job, get_custom_job
    from app.services.scheduler_service import _last_results

    job = get_custom_job(db, job_id)
    if not job:
        raise HTTPException(404, "Custom job not found")

    result = execute_custom_job(db, job)
    _last_results[f"custom_{job_id}"] = result
    return {"id": job_id, "status": "completed", "result": result}
