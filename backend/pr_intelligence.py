"""Conservative PR analysis. Publication is a separate, disabled-by-default operator action."""
import time
import jwt
from sqlalchemy import select
from backend.config import settings
from backend.connectors import GitHub, UpstreamError
from backend.models import Decision, DecisionVersion, CodeEntity, CodeLink, PRFinding, Alternative
from backend.memory import get_or_create
from backend.inference import SYSTEM, structured, InferenceUnavailable
from backend.schemas import StrictModel, Citation
from backend.repositories.evidence import citations_for_version
from pydantic import Field


class Conflict(StrictModel):
    conflict: bool
    explanation: str
    citations: list[Citation]


class Suggestion(StrictModel):
    approach: str = Field(min_length=8, max_length=1200)
    complexity: str = Field(min_length=3, max_length=500)
    maintainability: str = Field(min_length=3, max_length=500)
    compatibility: str = Field(min_length=3, max_length=500)
    risk: str = Field(min_length=3, max_length=500)
    historical_statement: str = Field(max_length=1000)
    repeats_rejected_alternative: bool
    citations: list[Citation] = Field(max_length=5)


class HistoricalConstraint(StrictModel):
    statement: str = Field(min_length=5, max_length=1000)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class Suggestions(StrictModel):
    objective: str = Field(min_length=3, max_length=1000)
    historical_constraints: list[HistoricalConstraint] = Field(max_length=8)
    suggestions: list[Suggestion] = Field(min_length=2, max_length=3)


def installation_client(repository: str):
    config = settings()
    if not all([config.github_app_id, config.github_app_private_key, config.github_installation_id]):
        raise UpstreamError("GitHub App is not configured")
    now = int(time.time())
    token = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": config.github_app_id},
                       config.github_app_private_key.replace("\\n", "\n"), algorithm="RS256")
    client = GitHub(token=token)
    try:
        data = client.request(f"/app/installations/{int(config.github_installation_id)}/access_tokens", method="POST",
            json={"repositories": [repository.split("/")[1]]}).json()
    finally:
        client.close()
    return GitHub(token=data["token"])


def related_versions(db, project_id, paths):
    if not paths:
        return []
    return db.scalars(select(DecisionVersion).join(Decision).join(CodeLink, CodeLink.version_id == DecisionVersion.id)
        .join(CodeEntity, CodeEntity.id == CodeLink.entity_id).where(Decision.project_id == project_id,
            Decision.current_revision == DecisionVersion.revision, DecisionVersion.verification == "model_supported",
            DecisionVersion.status.notin_(["superseded", "reverted"]),
            CodeLink.status.in_(["verified", "inferred"]), CodeEntity.path.in_(paths)).distinct().limit(10)).all()


def analyze_pr(db, project, pr):
    from backend.inference import verify_quotes, verify_semantics
    files = pr.details.get("files", [])
    versions = related_versions(db, project.id, [f["filename"] for f in files])
    from backend.retrieval import search
    context_query = " ".join([pr.title, pr.details.get("body", ""),
        " ".join(f.get("filename", "") for f in files)])[:2000]
    try:
        hits, _ = search(db, project.id, context_query, limit=10)
        known = {v.id for v in versions}
        versions.extend(hit["version"] for hit in hits if hit["version"].id not in known
                        and hit["version"].status not in {"superseded", "reverted"}
                        and hit["version"].verification == "model_supported")
    except Exception:
        pass  # Exact file-path candidates remain available when embeddings or search are down.
    saved = []
    for version in versions:
        evidence = citations_for_version(db, version.id)
        records = {str(e["message_version_id"]): e for e in evidence}
        symbols = db.scalars(select(CodeEntity).where(CodeEntity.project_id == project.id,
            CodeEntity.commit_sha == pr.head_sha, CodeEntity.path.in_([f["filename"] for f in files]),
            CodeEntity.symbol != "").limit(100)).all()
        result = structured(Conflict, SYSTEM + "\nAssess a concrete conflict between the PR patch and the cited historical constraint. "
            "File overlap alone is insufficient. Remain silent when the decision is not established as currently applicable.",
            {"decision": version.claim, "historical_status": version.status, "sources": list(records.values()),
             "pull_request": {"title": pr.title, "body": pr.details.get("body", "")},
             "symbols": [{"path": symbol.path, "name": symbol.symbol, "kind": symbol.kind,
                         "line_start": symbol.details.get("line_start"),
                         "line_end": symbol.details.get("line_end")} for symbol in symbols],
             "patches": [{"path": f["filename"], "patch": f.get("patch", ""),
                          "previous_filename": f.get("previous_filename")} for f in files]},)
        if not result.conflict or not result.citations:
            continue
        checked = verify_quotes(result.citations, records)
        support = verify_semantics(result.explanation, [c["quote"] for c in checked])
        if not support.supported:
            continue
        finding = get_or_create(db, PRFinding, {"pr_id": pr.id, "head_sha": pr.head_sha, "version_id": version.id},
            relevance=1.0, explanation=result.explanation, publication="verified")
        saved.append(finding)
    return saved


def explore_alternatives(db, project, pr, objective: str):
    """Generate ephemeral options grounded in the shared, verified project memory."""
    from backend.inference import verify_quotes, verify_semantics
    from backend.repositories.evidence import citations_for_version
    from backend.retrieval import search

    files = pr.details.get("files", [])
    versions = related_versions(db, project.id, [f.get("filename", "") for f in files])
    query = " ".join([objective, pr.title, pr.details.get("body", ""),
                       " ".join(f.get("filename", "") for f in files)])[:2000]
    hits, _ = search(db, project.id, query, limit=10)
    ids = {v.id for v in versions}
    versions.extend(hit["version"] for hit in hits if hit["version"].id not in ids
                    and hit["version"].status not in {"superseded", "reverted"}
                    and hit["version"].verification == "model_supported")
    source_records, rejected_ids, constraints = {}, set(), []
    for version in versions[:10]:
        citations = citations_for_version(db, version.id)
        for record in citations:
            source_records.setdefault(str(record["message_version_id"]), {
                "message_version_id": str(record["message_version_id"]), "body": record["body"],
                "url": record["url"], "author": record["author"], "quote": record["quote"],
                "decision_status": version.status})
        for alternative in db.scalars(select(Alternative).where(Alternative.version_id == version.id)):
            if alternative.status != "rejected":
                continue
            alt_records = [r for r in citations if r.get("alternative_id") == alternative.id]
            for record in alt_records:
                rejected_ids.add(str(record["message_version_id"]))
                source_records[str(record["message_version_id"])]["rejected_alternative"] = alternative.approach
                source_records[str(record["message_version_id"])]["rejection_rationale"] = alternative.rationale
        records = {str(r["message_version_id"]): r for r in citations}
        cited = [r for r in records.values() if r.get("alternative_id") is None]
        if cited:
            # Only include a verified current interpretation; citations are resolved below.
            constraints.append({"statement": version.claim, "citations": cited[:3]})
    source_records = dict(list(source_records.items())[:24])
    output = structured(Suggestions, SYSTEM + "\nPropose two or three substantially different, untested approaches for this PR. Separate engineering tradeoffs from historical facts. Cite only exact supplied message IDs/quotes. Rejected alternatives are source evidence; mark a repeat only when the proposed approach actually repeats one. Do not call suggestions tested or approved.",
        {"objective": objective, "pull_request": {"title": pr.title, "body": pr.details.get("body", ""),
            "head_sha": pr.head_sha, "files": [{"path": f.get("filename"), "patch": f.get("patch", "")}
                                             for f in files[:30]],
         "symbols": [{"path": e.path, "name": e.symbol, "kind": e.kind,
                      "line_start": e.details.get("line_start"), "line_end": e.details.get("line_end")}
                     for e in db.scalars(select(CodeEntity).where(CodeEntity.project_id == project.id,
                         CodeEntity.commit_sha == pr.head_sha, CodeEntity.symbol != "").limit(100))]},
         "verified_history": [{"statement": c["statement"], "citations": c["citations"]} for c in constraints],
         "rejected_alternative_message_ids": sorted(rejected_ids),
         "source_records": list(source_records.values())})
    verified_constraints = []
    for item in output.historical_constraints:
        checked = verify_quotes(item.citations, source_records)
        if verify_semantics(item.statement, [c["quote"] for c in checked]).supported:
            verified_constraints.append({"statement": item.statement,
                "citations": [{k: v for k, v in c.items() if k != "body"} for c in checked]})
    options = []
    for item in output.suggestions:
        checked = verify_quotes(item.citations, source_records) if item.citations else []
        supports = bool(checked and verify_semantics(item.historical_statement,
                      [c["quote"] for c in checked]).supported)
        repeats = bool(supports and item.repeats_rejected_alternative and
                       any(str(c["message_version_id"]) in rejected_ids for c in checked))
        options.append({"approach": item.approach, "complexity": item.complexity,
            "maintainability": item.maintainability, "compatibility": item.compatibility, "risk": item.risk,
            "historical_statement": item.historical_statement if supports else "No verified historical support asserted.",
            "historical_status": "repeats_rejected_alternative" if repeats else
                "historically_supported" if supports else "novel_unvalidated",
            "validation_status": "unvalidated", "citations": [
                {k: v for k, v in c.items() if k != "body"} for c in checked] if supports else []})
    return {"objective": output.objective, "head_sha": pr.head_sha,
        "historical_constraints": verified_constraints, "suggestions": options,
        "notice": "Suggestions are untested. Historical support is limited to the cited source records."}


def publish_findings(db, project, pr, findings):
    """Operator opt-in only; this function is not called by ingestion or webhooks."""
    config = settings()
    if not config.github_publish_enabled:
        raise UpstreamError("PR publishing is disabled")
    if not findings:
        return "silent"
    # Require explicit review of drafts before publication. Never post only inferred associations.
    if any(f.publication not in ("verified", "approved", "published") or f.head_sha != pr.head_sha or f.pr_id != pr.id for f in findings):
        raise UpstreamError("Only evidence-verified findings for the current head may be published")
    client = installation_client(project.repository)
    try:
        client.public_repository(project.repository)
        live = client.get(f"/repos/{project.repository}/pulls/{pr.number}")
        if live["head"]["sha"] != pr.head_sha or live["state"] != "open":
            return "stale_head"
        marker = "<!-- watermelon:historical-context -->"
        parts = [marker, "### WATERMELON · historical context", f"Reviewed head: `{pr.head_sha}`"]
        for finding in findings[:3]:
            refs = citations_for_version(db, finding.version_id)
            if not refs:
                continue
            parts.append(f"\n{finding.explanation}\n" + " ".join(
                f"[Source {i + 1}]({ref['url']})" for i, ref in enumerate(refs[:4])))
        if len(parts) == 3:
            return "silent"
        body = "\n\n".join(parts)
        comments = client.pages(f"/repos/{project.repository}/issues/{pr.number}/comments")
        previous = next((c for c in comments if marker in (c.get("body") or "") and
                         c.get("performed_via_github_app", {}).get("id") == int(config.github_app_id)), None)
        if previous and previous.get("body") == body:
            return "unchanged"
        # Recheck after fetching comments to reduce stale-head publication window.
        if client.get(f"/repos/{project.repository}/pulls/{pr.number}")["head"]["sha"] != pr.head_sha:
            return "stale_head"
        path = f"/repos/{project.repository}/issues/comments/{previous['id']}" if previous else f"/repos/{project.repository}/issues/{pr.number}/comments"
        result = client.request(path, method="PATCH" if previous else "POST", json={"body": body}).json()
        for finding in findings:
            finding.publication, finding.external_comment_id = "published", str(result["id"])
        return "published"
    finally:
        client.close()
