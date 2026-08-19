import logging
import os
import socket
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from .config import get_settings
from .database import SessionLocal
from .document_text import DocumentExtractionError, extract_text
from .main import initialize_database
from .models import JobStatus, ReviewJob, utcnow
from .reviewer import MockReviewProvider, TransientReviewProviderError
from .services import new_review_job


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()
worker_id = f"{socket.gethostname()}:{os.getpid()}"
provider = MockReviewProvider()


def recover_stale_jobs() -> int:
    cutoff = utcnow() - timedelta(seconds=settings.job_lease_seconds)
    with SessionLocal.begin() as db:
        result = db.execute(
            update(ReviewJob)
            .where(ReviewJob.status == JobStatus.processing, ReviewJob.locked_at < cutoff)
            .values(status=JobStatus.pending, worker_id=None, locked_at=None)
        )
        return result.rowcount


def claim_job() -> str | None:
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ReviewJob)
            .where(ReviewJob.status == JobStatus.pending, ReviewJob.available_at <= utcnow())
            .order_by(ReviewJob.available_at, ReviewJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status = JobStatus.processing
        job.attempts += 1
        job.worker_id = worker_id
        job.locked_at = utcnow()
        job.started_at = utcnow()
        return job.id


def process_job(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.scalar(
            select(ReviewJob)
            .options(joinedload(ReviewJob.document))
            .where(ReviewJob.id == job_id, ReviewJob.worker_id == worker_id)
        )
        if not job:
            logger.warning("Job %s is no longer owned by this worker", job_id)
            return
        try:
            try:
                data = Path(job.document.storage_path).read_bytes()
            except OSError as exc:
                raise DocumentExtractionError("Stored document file is missing or unreadable") from exc
            text = extract_text(job.document.filename, data)
            job.document.content_text = text
            result = provider.review(text)
            job.result = result
            job.risk_level = result["overall_risk_level"]
            job.status = JobStatus.completed
            job.completed_at = utcnow()
            job.error_message = None
            logger.info("Completed job %s with risk=%s", job.id, job.risk_level)
        except TransientReviewProviderError as exc:
            job.status = JobStatus.failed
            job.error_message = str(exc)[:2000]
            job.completed_at = utcnow()
            if job.attempts < job.max_attempts:
                delay = settings.job_retry_base_seconds * (2 ** (job.attempts - 1))
                retry = new_review_job(
                    job.tenant_id,
                    job.document_id,
                    retry_of=job,
                    available_at=utcnow() + timedelta(seconds=delay),
                )
                retry.document = job.document
                db.add(retry)
                logger.warning("Review job %s failed transiently; queued retry %s", job.id, retry.id)
            else:
                logger.warning("Review job %s exhausted automatic retries", job.id)
        except Exception as exc:
            job.status = JobStatus.failed
            job.error_message = str(exc)[:2000]
            job.completed_at = utcnow()
            logger.exception("Review job %s failed permanently", job.id)
        finally:
            job.locked_at = None
            db.commit()


def run_once() -> bool:
    job_id = claim_job()
    if not job_id:
        return False
    process_job(job_id)
    return True


def main() -> None:
    initialize_database()
    logger.info("Worker %s started", worker_id)
    while True:
        recovered = recover_stale_jobs()
        if recovered:
            logger.warning("Recovered %d stale job(s)", recovered)
        if not run_once():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
