import argparse
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.db import engine
from backend.models import Project, IngestionJob
from backend.memory import get_or_create
from backend.config import settings
from backend.jobs import ingest_job
from backend.connectors import digest

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
manifest_text = Path("data/httpx-manifest.json").read_text()
manifest = json.loads(manifest_text)
with Session(engine()) as db:
    project = get_or_create(db, Project, {"owner_id": settings().owner_id, "repository": manifest["repository"]}, name="HTTPX")
    job = IngestionJob(project_id=project.id, cursor={"numbers": [x["number"] for x in manifest["items"]],
        "extract": not args.source_only, "manifest_hash": digest(manifest_text)})
    db.add(job)
    db.commit()
    job_id = str(job.id)
    print("Project:", project.id, "Job:", job_id, flush=True)
ingest_job(job_id)
with Session(engine()) as db:
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
    print(json.dumps({"status": job.status, "progress": job.progress, "coverage": job.cursor}, indent=2))
