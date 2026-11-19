"""Resume the original bounded sample; committed discussion snapshots are not fetched again."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.db import engine
from backend.models import IngestionJob, Discussion
from backend.jobs import ingest_job

with Session(engine()) as db:
    job = db.scalar(select(IngestionJob).where(IngestionJob.kind == "github").order_by(IngestionJob.created_at.desc()).limit(1))
    completed = [int(d.external_id) for d in db.scalars(select(Discussion).where(Discussion.project_id == job.project_id))]
    job.cursor = {**job.cursor, "completed": completed}
    job.status = "queued"
    db.commit()
    job_id = str(job.id)
    print("Resuming only missing IDs:", [n for n in job.cursor["numbers"] if n not in completed], flush=True)
ingest_job(job_id)
