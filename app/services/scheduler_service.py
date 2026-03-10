"""Scheduler service: manages background jobs via APScheduler."""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Store last run results for each job
_last_results: dict[str, dict] = {}


def _run_tracking_job():
    """Execute tracking check inside a fresh DB session."""
    from app.database import SessionLocal
    from app.services.tracking_service import check_tracking_updates

    db = SessionLocal()
    try:
        result = check_tracking_updates(db)
        _last_results["tracking_check"] = result
    except Exception as e:
        logger.error("Tracking job error: %s", e)
        _last_results["tracking_check"] = {
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()


def init_scheduler():
    """Initialize scheduler with default jobs (paused). Call during app startup."""
    if scheduler.running:
        return

    scheduler.add_job(
        _run_tracking_job,
        "interval",
        minutes=30,
        id="tracking_check",
        name="Tracking Status Check",
        replace_existing=True,
        next_run_time=None,  # Start paused
    )
    scheduler.start()
    logger.info("Scheduler started with jobs paused")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def get_jobs_status() -> list[dict]:
    """Return status of all scheduled jobs."""
    jobs = []
    for job in scheduler.get_jobs():
        last = _last_results.get(job.id)
        # Build a lighter last_result for the list view (exclude full snapshot data)
        last_light = None
        if last:
            last_light = {k: v for k, v in last.items() if k != "revert_snapshots"}
            snapshots = last.get("revert_snapshots", [])
            last_light["revert_snapshots"] = [{"order_number": s["order_number"]} for s in snapshots]
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "running": job.next_run_time is not None,
            "trigger": str(job.trigger),
            "last_result": last_light,
        })
    return jobs


def start_job(job_id: str, interval_minutes: int | None = None) -> dict:
    """Resume/start a job. Optionally update interval."""
    job = scheduler.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")

    if interval_minutes and interval_minutes > 0:
        scheduler.reschedule_job(job_id, trigger="interval", minutes=interval_minutes)

    # Resume by scheduling next run now
    job = scheduler.get_job(job_id)
    if not job.next_run_time:
        job.resume()

    return {"id": job_id, "status": "started", "next_run": job.next_run_time.isoformat() if job.next_run_time else None}


def pause_job(job_id: str) -> dict:
    """Pause a job."""
    job = scheduler.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")
    job.pause()
    return {"id": job_id, "status": "paused"}


def run_job_now(job_id: str) -> dict:
    """Trigger a job to run immediately (one-off)."""
    job = scheduler.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found")

    # Run synchronously so we can return result
    job.func()
    return {"id": job_id, "status": "completed", "result": _last_results.get(job_id)}


def revert_last_job(job_id: str) -> dict:
    """Revert the last run of a job, restoring orders to previous states."""
    last = _last_results.get(job_id)
    if not last:
        raise ValueError(f"No previous run found for job '{job_id}'")

    snapshots = last.get("revert_snapshots")
    if not snapshots:
        raise ValueError("No changes to revert from the last run")

    from app.database import SessionLocal
    from app.services.tracking_service import revert_tracking_updates

    db = SessionLocal()
    try:
        result = revert_tracking_updates(db, snapshots)
        # Clear revert snapshots after successful revert
        last["revert_snapshots"] = []
        last["reverted"] = True
        return {"id": job_id, "status": "reverted", "result": result}
    finally:
        db.close()
