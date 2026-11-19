"""RQ entry points; durable job records survive Redis enqueue failures."""
import uuid
import time
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from rq import Queue, Retry
from rq.serializers import JSONSerializer
from backend.db import engine
from backend.config import settings
from backend.connectors import GitHub, RateLimited
from backend.models import Project, IngestionJob, SourceConnection, now
from backend.memory import persist_github, persist_github_discussion, evidence_records, persist_extraction
from backend.inference import extract, InferenceUnavailable, redis_connection


def enqueue(job_id):
    return Queue("watermelon", connection=redis_connection(), serializer=JSONSerializer).enqueue(
        "backend.jobs.ingest_job", str(job_id), job_id=str(job_id), job_timeout=1800,
        retry=Retry(max=3, interval=[60, 300, 900]), result_ttl=86400)


def ingest_job(job_id: str):
    job_uuid = uuid.UUID(job_id)
    with Session(engine()) as db:
        job = db.get(IngestionJob, job_uuid, with_for_update=True)
        if not job or job.status == "complete":
            return
        project = db.get(Project, job.project_id)
        project_id, repository, cursor, job_kind = project.id, project.repository, dict(job.cursor), job.kind
        job.status, job.attempts = "running", job.attempts + 1
        db.commit()
    client = GitHub()
    if job_kind == "github_pr_event":
        try:
            from backend.pr_intelligence import installation_client, analyze_pr, publish_findings
            from backend.models import PullRequest
            client.close()
            client = installation_client(repository)
            client.public_repository(repository)
            bundle = client.discussion(repository, int(cursor["number"]))
            if "pr" not in bundle:
                raise ValueError("GitHub PR event no longer resolves to a pull request")
            from pathlib import Path
            symbol_sources = {}
            for changed_file in bundle.get("files", []):
                if Path(changed_file["filename"]).suffix.lower() not in {".py", ".ts", ".tsx"}:
                    continue
                try:
                    symbol_sources[changed_file["filename"]] = client.file_content(
                        repository, changed_file["filename"], bundle["pr"]["head"]["sha"])
                except RateLimited:
                    raise
                except Exception:
                    continue
            with Session(engine()) as db:
                project = db.get(Project, project_id)
                discussion = persist_github(db, project, bundle)
                from backend.memory import persist_symbols
                for path, source in symbol_sources.items():
                    persist_symbols(db, project, int(cursor["number"]), bundle["pr"]["head"]["sha"], path, source)
                db.flush()
                pr = db.scalar(select(PullRequest).where(PullRequest.project_id == project_id,
                    PullRequest.number == int(cursor["number"])).with_for_update())
                if not pr or pr.head_sha != bundle["pr"]["head"]["sha"]:
                    raise ValueError("Pull request head changed while saving its source snapshot")
                findings = analyze_pr(db, project, pr)
                publication = "disabled" if not settings().github_publish_enabled else "silent"
                if settings().github_publish_enabled and findings:
                    publication = publish_findings(db, project, pr, findings)
                job = db.get(IngestionJob, job_uuid)
                job.progress, job.status, job.finished_at = 100, "complete", now()
                job.cursor = {**cursor, "discussion_id": str(discussion.id), "pr_id": str(pr.id),
                    "analyzed_head_sha": pr.head_sha, "finding_ids": [str(f.id) for f in findings],
                    "publication": publication}
                db.commit()
            return
        except Exception as exc:
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                if job:
                    job.status = "failed"
                    job.error = f"GitHub App PR analysis failed: {type(exc).__name__}; delivery can be retried."
                    db.commit()
            raise
        finally:
            client.close()
    if job_kind == "discourse":
        try:
            from backend.discourse import ingest_topic
            with Session(engine()) as db:
                project = db.get(Project, project_id)
                discussion = ingest_topic(db, project, cursor["origin"], int(cursor["topic_id"]))
                discussion_id = discussion.id
                db.commit()
                records = evidence_records(db, discussion_id)
            blocked = False
            if cursor.get("extract", True):
                try:
                    result = extract(records)
                    with Session(engine()) as db:
                        from backend.models import Discussion
                        discussion = db.get(Discussion, discussion_id)
                        versions = persist_extraction(db, discussion, result, settings().openrouter_model)
                        db.commit()
                    if settings().openrouter_embedding_model:
                        from backend.retrieval import index_version
                        for version in versions:
                            try:
                                with Session(engine()) as db:
                                    from backend.models import DecisionVersion
                                    row = db.get(DecisionVersion, version.id)
                                    index_version(db, project_id, row)
                                    db.commit()
                            except Exception:
                                cursor.setdefault("embedding_failures", []).append({"error_type": "EmbeddingUnavailable"})
                except InferenceUnavailable as exc:
                    blocked = True
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                job.progress, job.status, job.finished_at = 100, "awaiting_model" if blocked else "complete", now()
                if blocked:
                    job.error = "Source ingestion finished. Extraction awaits model configuration or budget."
                job.cursor = {**cursor, "discussion_id": str(discussion_id)}
                db.commit()
            return
        except Exception as exc:
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                if job:
                    job.status = "failed"
                    job.error = f"Discourse ingestion interrupted: {type(exc).__name__}; retry is safe."
                    db.commit()
            raise
        finally:
            client.close()
    if job_kind == "pr_analysis":
        try:
            from backend.models import PullRequest
            from backend.pr_intelligence import analyze_pr
            with Session(engine()) as db:
                project = db.get(Project, project_id)
                pr = db.scalar(select(PullRequest).where(PullRequest.id == cursor["pr_id"],
                                                        PullRequest.project_id == project_id))
                if not pr or pr.head_sha != cursor["head_sha"]:
                    raise ValueError("Pull request head changed before analysis")
                findings = analyze_pr(db, project, pr)
                job = db.get(IngestionJob, job_uuid)
                job.progress, job.status, job.finished_at = 100, "complete", now()
                job.cursor = {**cursor, "finding_ids": [str(f.id) for f in findings]}
                db.commit()
            return
        except Exception as exc:
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                if job:
                    job.status = "failed"
                    job.error = f"PR analysis interrupted: {type(exc).__name__}; retry is safe."
                    db.commit()
            raise
        finally:
            client.close()
    if job_kind == "github_discussion":
        cursor["numbers"] = [int(cursor["number"])]
        cursor["graphql_discussion"] = True
        cursor["extract"] = True
    if job_kind == "github_reconcile":
        try:
            since = cursor.get("updated_since")
            changed = client.pages(f"/repos/{repository}/issues", max_pages=10, state="all", since=since)
            numbers = sorted({int(item["number"]) for item in changed})
            cursor["numbers"] = numbers[:1000]
            cursor["extract"] = True
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                job.cursor = cursor
                db.commit()
        except Exception as exc:
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                if job:
                    job.status, job.error = "failed", f"Reconciliation failed: {type(exc).__name__}; watermark was not advanced."
                    db.commit()
            raise
    blocked = list(cursor.get("extraction_blocked", []))
    completed = set(cursor.get("completed", []))
    abstentions = list(cursor.get("extraction_abstentions", []))
    failures = []
    embedding_failures = list(cursor.get("embedding_failures", []))
    try:
        client.public_repository(repository)
        for index, number in enumerate(cursor["numbers"]):
            if number in completed:
                continue
            try:
                # No SQL transaction stays open while waiting for upstream network requests.
                if cursor.get("graphql_discussion"):
                    bundle = client.graphql_discussion(repository, number)
                else:
                    bundle = client.discussion(repository, number)
                    failures.extend({"number": number, **failure} for failure in bundle.get("partial_failures", []))
                symbol_sources = {}
                if bundle.get("pr"):
                    from pathlib import Path
                    for changed_file in bundle.get("files", []):
                        language = {".py", ".ts", ".tsx"}
                        if Path(changed_file["filename"]).suffix.lower() not in language:
                            continue
                        try:
                            symbol_sources[changed_file["filename"]] = client.file_content(
                                repository, changed_file["filename"], bundle["pr"]["head"]["sha"])
                        except RateLimited:
                            raise
                        except Exception as exc:
                            failures.append({"number": number, "component": "symbols",
                                             "error_type": type(exc).__name__})
                with Session(engine()) as db:
                    project = db.get(Project, project_id, with_for_update=True)
                    discussion = (persist_github_discussion(db, project, bundle) if cursor.get("graphql_discussion")
                                  else persist_github(db, project, bundle))
                    if bundle.get("pr"):
                        from backend.memory import persist_symbols
                        for path, source in symbol_sources.items():
                            persist_symbols(db, project, number, bundle["pr"]["head"]["sha"], path, source)
                    discussion_id = discussion.id
                    db.commit()
                    records = evidence_records(db, discussion_id)
                if cursor.get("extract", True):
                    try:
                        result = extract(records)
                        if not result.decisions:
                            abstentions.append({"number": number, "reason": result.abstention_reason})
                        with Session(engine()) as db:
                            from backend.models import Discussion
                            discussion = db.get(Discussion, discussion_id)
                            versions = persist_extraction(db, discussion, result, settings().openrouter_model)
                            db.commit()
                        if settings().openrouter_embedding_model:
                            from backend.retrieval import index_version
                            for version in versions:
                                try:
                                    with Session(engine()) as db:
                                        from backend.models import DecisionVersion
                                        row = db.get(DecisionVersion, version.id)
                                        index_version(db, project_id, row)
                                        db.commit()
                                except Exception:
                                    # Lexical retrieval remains available; record status below for operators.
                                    embedding_failures.append({"number": number, "error_type": "EmbeddingUnavailable"})
                    except InferenceUnavailable as exc:
                        blocked.append({"number": number, "reason": str(exc)})
                completed.add(number)
            except Exception as exc:
                if isinstance(exc, RateLimited):
                    raise
                failures.append({"number": number, "error_type": type(exc).__name__})
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                job.progress = round((index + 1) / len(cursor["numbers"]) * 100)
                job.cursor = {**cursor, "completed": sorted(completed), "failures": failures,
                              "extraction_blocked": blocked, "extraction_abstentions": abstentions,
                              "embedding_failures": embedding_failures}
                db.commit()
        with Session(engine()) as db:
            job = db.get(IngestionJob, job_uuid)
            project = db.get(Project, project_id)
            job.status = "partial" if failures else "awaiting_model" if blocked else "complete"
            job.error = "Some source records failed; inspect job coverage." if failures else (
                "Source ingestion finished. Extraction awaits model configuration or budget." if blocked else None)
            job.finished_at = now()
            project.status = "partial" if failures else "indexed"
            connection = db.scalar(select(SourceConnection).where(SourceConnection.project_id == project_id,
                                                                 SourceConnection.provider == "github"))
            if connection:
                connection.status = job.status
                if not failures:
                    connection.last_sync = now()
                connection.cursor = {"numbers": cursor["numbers"], "failures": failures,
                                     "updated_since": cursor.get("updated_since")}
            db.commit()
    except Exception as exc:
        # A fresh connection is essential after a broken transaction/connection.
        try:
            with Session(engine()) as db:
                job = db.get(IngestionJob, job_uuid)
                job.status, job.error = "failed", f"Ingestion interrupted: {type(exc).__name__}; retry preserves completed records."
                db.commit()
        except Exception:
            pass  # A stale running job is recoverable; never fabricate successful completion.
        raise
    finally:
        client.close()


def recover_jobs():
    """Operator/cron reconciliation of durable work not successfully queued."""
    recovered = 0
    with Session(engine()) as db:
        for job in db.scalars(select(IngestionJob).where(IngestionJob.status.in_(["queued", "enqueue_failed"]))
                              .with_for_update(skip_locked=True)):
            try:
                enqueue(job.id)
            except Exception:
                job.status = "enqueue_failed"
                job.error = "Redis unavailable during reconciliation; retry will be attempted later."
            else:
                job.status, job.error = "queued", None
                recovered += 1
        db.commit()
    return recovered
