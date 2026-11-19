import json
from datetime import datetime
from sqlalchemy import select
from backend.models import (Project, SourceConnection, Contributor, Discussion, Message, MessageVersion,
    Decision, DecisionVersion, Alternative, EvidenceReference, CodeEntity, CodeLink, PullRequest, GraphEdge, now)
from backend.connectors import digest
from backend.inference import verify_quotes, verify_semantics, PROMPT_VERSION


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else now()


def get_or_create(db, model, where, **values):
    result = db.scalar(select(model).filter_by(**where))
    if not result:
        result = model(**where, **values)
        db.add(result)
        db.flush()
    return result


def source_connection(db, project, provider="github", origin="https://github.com"):
    return get_or_create(db, SourceConnection,
        {"project_id": project.id, "provider": provider, "origin": origin}, external_id=project.repository)


def save_message(db, discussion, raw, kind, provider="github", body=None, external_id=None, url=None,
                 author=None, created=None, updated=None, parent_id=None):
    author = author or raw.get("user") or raw.get("actor") or {}
    contributor = None
    if author.get("id") is not None:
        contributor = get_or_create(db, Contributor,
            {"provider": provider, "external_id": str(author["id"])},
            handle=author.get("login", "unknown"), profile_url=author.get("html_url", ""))
    msg = get_or_create(db, Message,
        {"discussion_id": discussion.id, "external_id": external_id or f"{kind}:{raw['id']}"},
        project_id=discussion.project_id, contributor_id=contributor.id if contributor else None,
        url=url or raw.get("html_url") or discussion.url, kind=kind,
        source_created_at=stamp(created or raw.get("created_at") or raw.get("submitted_at")), parent_id=parent_id)
    body = (raw.get("body") or "") if body is None else body
    # Revision identity includes source metadata (edits, author association, review state), not only prose.
    content_hash = digest(json.dumps({"body": body, "raw": raw}, sort_keys=True))
    return get_or_create(db, MessageVersion, {"message_id": msg.id, "content_hash": content_hash},
                         body=body, raw=raw,
                         source_updated_at=stamp(updated or raw.get("updated_at") or raw.get("submitted_at")
                                                 or raw.get("created_at")))


def persist_github(db, project: Project, bundle: dict):
    issue = bundle["issue"]
    connection = source_connection(db, project)
    discussion = get_or_create(db, Discussion,
        {"connection_id": connection.id, "external_id": str(issue["number"])},
        project_id=project.id, kind="pull_request" if "pr" in bundle else "issue",
        title=issue["title"], url=issue["html_url"], source_created_at=stamp(issue["created_at"]),
        source_updated_at=stamp(issue["updated_at"]), raw=bundle)
    discussion.title, discussion.raw = issue["title"], bundle
    discussion.source_updated_at = stamp(issue["updated_at"])
    root = save_message(db, discussion, issue, "body")
    id_map = {}
    for key, kind in (("comments", "comment"), ("reviews", "review"),
                      ("review_comments", "inline_review"), ("timeline", "timeline"),
                      ("commits", "commit")):
        for raw in bundle.get(key, []):
            # Some GitHub timeline entries have neither numeric nor node IDs.
            external = f"{kind}:{raw.get('id') or raw.get('node_id') or digest(json.dumps(raw, sort_keys=True))}"
            if kind == "commit":
                raw = {**raw, "html_url": raw.get("html_url") or raw.get("url"),
                       "body": raw.get("commit", {}).get("message", "")}
            version = save_message(db, discussion, raw, kind, external_id=external,
                                   parent_id=id_map.get(raw.get("in_reply_to_id"), root.message_id))
            id_map[raw.get("id")] = version.message_id
    if "pr" in bundle:
        pr = bundle["pr"]
        row = get_or_create(db, PullRequest, {"project_id": project.id, "number": issue["number"]},
            discussion_id=discussion.id, title=pr["title"], url=pr["html_url"], head_sha=pr["head"]["sha"],
            state="merged" if pr.get("merged") else pr["state"], details=bundle)
        row.head_sha, row.details = pr["head"]["sha"], bundle
        row.state = "merged" if pr.get("merged") else pr["state"]
        for file in bundle.get("files", []):
            get_or_create(db, CodeEntity,
                {"project_id": project.id, "path": file["filename"], "symbol": "", "commit_sha": pr["head"]["sha"]},
                kind="file", details={"pr_number": issue["number"], "status": file["status"],
                    "previous_filename": file.get("previous_filename"), "url": file.get("blob_url")})
    return discussion


def persist_github_discussion(db, project: Project, source: dict):
    """Map GraphQL Discussions and nested replies into the same immutable evidence store."""
    issue = {"number": source["number"], "title": source["title"], "body": source.get("body", ""),
        "html_url": source["url"], "created_at": source["createdAt"], "updated_at": source["updatedAt"],
        "user": {"login": (source.get("author") or {}).get("login"),
                 "html_url": (source.get("author") or {}).get("url")}}
    connection = source_connection(db, project, provider="github_discussions")
    discussion = get_or_create(db, Discussion,
        {"connection_id": connection.id, "external_id": str(issue["number"])},
        project_id=project.id, kind="github_discussion", title=issue["title"], url=issue["html_url"],
        source_created_at=stamp(issue["created_at"]), source_updated_at=stamp(issue["updated_at"]), raw=source)
    discussion.title, discussion.url, discussion.raw = issue["title"], issue["html_url"], source
    discussion.source_updated_at = stamp(issue["updated_at"])
    root = save_message(db, discussion, issue, "body", external_id=f"discussion:{source['id']}")
    for comment in source.get("comments", []):
        author = comment.get("author") or {}
        raw = {**comment, "user": {"login": author.get("login"), "html_url": author.get("url")},
               "html_url": comment.get("url"), "created_at": comment.get("createdAt"),
               "updated_at": comment.get("updatedAt")}
        version = save_message(db, discussion, raw, "discussion_comment", external_id=comment["id"],
                               parent_id=root.message_id)
        for reply in comment.get("replies", []):
            reply_author = reply.get("author") or {}
            reply_raw = {**reply, "user": {"login": reply_author.get("login"), "html_url": reply_author.get("url")},
                         "html_url": reply.get("url"), "created_at": reply.get("createdAt"),
                         "updated_at": reply.get("updatedAt")}
            save_message(db, discussion, reply_raw, "discussion_reply", external_id=reply["id"],
                         parent_id=version.message_id)
    return discussion


def persist_symbols(db, project, pr_number: int, head_sha: str, file_path: str, source: bytes):
    from backend.code_awareness import symbols
    language = {".py": "python", ".ts": "typescript", ".tsx": "tsx"}.get(
        __import__("pathlib").Path(file_path).suffix.lower())
    if not language:
        return []
    output = []
    for symbol in symbols(source, language):
        row = get_or_create(db, CodeEntity,
            {"project_id": project.id, "path": file_path, "symbol": symbol["name"], "commit_sha": head_sha},
            kind=symbol["kind"], details={**symbol, "pr_number": pr_number, "source": "treesitter"})
        output.append(row)
    return output


def evidence_records(db, discussion_id):
    rows = db.execute(select(MessageVersion, Message, Contributor).join(Message,
        Message.id == MessageVersion.message_id).outerjoin(Contributor, Contributor.id == Message.contributor_id)
        .where(Message.discussion_id == discussion_id).order_by(Message.source_created_at,
                                                                MessageVersion.source_updated_at,
                                                                MessageVersion.created_at)).all()
    seen, records = set(), []
    for version, message, contributor in rows:
        if message.id in seen:
            continue
        seen.add(message.id)
        if not version.body.strip():
            continue
        records.append({"message_version_id": str(version.id), "body": version.body, "url": message.url,
            "author": contributor.handle if contributor else "unknown",
            "author_association": version.raw.get("author_association", "unknown"),
            "timestamp": message.source_created_at.isoformat(), "kind": message.kind})
    return records


def persist_extraction(db, discussion, extraction, model, semantic=True):
    records = evidence_records(db, discussion.id)
    by_id = {r["message_version_id"]: r for r in records}
    input_hash = digest(json.dumps(records, sort_keys=True))
    # Validate the entire extraction before writing any interpretation.
    for candidate in extraction.decisions:
        verify_quotes(candidate.citations, by_id)
        for alternative in candidate.alternatives:
            verify_quotes(alternative.citations, by_id)
    saved = []
    for candidate in extraction.decisions:
        citations = verify_quotes(candidate.citations, by_id)
        verification = verify_semantics(candidate.claim, [c["quote"] for c in citations]) if semantic else None
        requires_disposition = candidate.status in {"accepted", "rejected", "deferred", "superseded", "reverted"}
        supported = bool(verification and verification.supported and
                         (not requires_disposition or verification.explicit_disposition))
        # Abstain on unsupported records; do not materialize a speculative decision row.
        if not supported:
            continue
        # A stable extraction key deduplicates the same decision across discussions in one project.
        decision = db.scalar(select(Decision).where(Decision.project_id == discussion.project_id,
            Decision.stable_key == candidate.key).with_for_update())
        if decision is None:
            decision = get_or_create(db, Decision,
                {"discussion_id": discussion.id, "stable_key": candidate.key}, project_id=discussion.project_id)
        db.refresh(decision, with_for_update=True)
        previous = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == decision.id)
                             .order_by(DecisionVersion.revision.desc()).limit(1))
        output_hash = digest(candidate.model_dump_json())
        if previous and previous.input_hash == input_hash and previous.details.get("output_hash") == output_hash:
            saved.append(previous)
            continue
        revision = (previous.revision + 1) if previous else 1
        decision.current_revision = revision
        version = DecisionVersion(decision_id=decision.id, revision=revision, title=candidate.title,
            claim=candidate.claim, scope=candidate.scope, status=candidate.status,
            verification="model_supported" if supported else "needs_review", model=model,
            prompt_version=PROMPT_VERSION, input_hash=input_hash,
            details={"open_questions": candidate.open_questions, "possible_supersession": candidate.possible_supersession,
                     "output_hash": output_hash, "verification": verification.model_dump() if verification else
                     {"rationale": "Agent-assisted reconstruction; exact quotes checked, maintainer review pending"}})
        db.add(version)
        db.flush()
        for citation in candidate.citations:
            db.add(EvidenceReference(version_id=version.id, message_version_id=citation.message_version_id,
                claim=candidate.claim, quote=citation.quote, verification=version.verification))
        for alternative in candidate.alternatives:
            verified = verify_semantics(alternative.approach + ": " + alternative.rationale,
                                       [c.quote for c in verify_quotes(alternative.citations, by_id)]) if semantic else None
            if not verified or not verified.supported or (alternative.status in {"rejected", "deferred", "accepted"}
                                                            and not verified.explicit_disposition):
                continue
            alt = Alternative(version_id=version.id, approach=alternative.approach,
                              status=alternative.status, rationale=alternative.rationale)
            db.add(alt)
            db.flush()
            get_or_create(db, GraphEdge,
                {"project_id": discussion.project_id, "source_id": alt.id, "target_id": decision.id,
                 "relation": "alternative_to"}, source_kind="alternative", target_kind="decision", provenance="verified")
            for citation in alternative.citations:
                db.add(EvidenceReference(version_id=version.id, alternative_id=alt.id,
                    message_version_id=citation.message_version_id, claim=alternative.rationale,
                    quote=citation.quote, verification="model_supported"))
        get_or_create(db, GraphEdge,
            {"project_id": discussion.project_id, "source_id": decision.id, "target_id": discussion.id,
             "relation": "reconstructed_from"}, source_kind="decision", target_kind="discussion", provenance="verified")
        for prior_key in candidate.possible_supersession:
            prior = db.scalar(select(Decision).where(Decision.project_id == discussion.project_id,
                Decision.stable_key == prior_key, Decision.id != decision.id).with_for_update())
            if not prior:
                continue
            prior_version = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == prior.id,
                DecisionVersion.revision == prior.current_revision))
            if not prior_version or prior_version.status == "superseded":
                continue
            successor = DecisionVersion(decision_id=prior.id, revision=prior.current_revision + 1,
                title=prior_version.title, claim=prior_version.claim, scope=prior_version.scope,
                status="superseded", verification="model_supported", model=model,
                prompt_version=PROMPT_VERSION, input_hash=input_hash,
                details={**prior_version.details, "superseded_by": candidate.key,
                         "superseded_evidence_version": str(version.id)})
            prior.current_revision += 1
            db.add(successor)
            db.flush()
            get_or_create(db, GraphEdge,
                {"project_id": discussion.project_id, "source_id": decision.id, "target_id": prior.id,
                 "relation": "supersedes"}, source_kind="decision", target_kind="decision", provenance="verified")
        pr = db.scalar(select(PullRequest).where(PullRequest.discussion_id == discussion.id))
        if pr:
            entities = db.scalars(select(CodeEntity).where(CodeEntity.project_id == discussion.project_id,
                                                          CodeEntity.commit_sha == pr.head_sha)).all()
            for entity in entities:
                # File membership is verified; relevance of every file to a particular claim is inferred.
                db.add(CodeLink(version_id=version.id, entity_id=entity.id, status="inferred",
                                provenance="File changed in source PR; claim-level relevance unreviewed", proof_url=pr.url))
        saved.append(version)
    return saved
