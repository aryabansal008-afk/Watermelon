"""Real PostgreSQL contract tests. Set TEST_DATABASE_URL to a disposable *_test database.

Schema creation/migrations are intentionally not performed inside pytest. Run
`uv run alembic upgrade head` against the test URL first; test rows are rolled back.
"""
import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import sqlalchemy_url
from backend.memory import persist_github
from backend import memory
from backend.schemas import Extraction, DecisionClaim, Citation, Verification
from backend.retrieval import search
from backend import api
from backend.models import (Alternative, Decision, DecisionVersion, Discussion, Embedding,
                            GraphEdge, IngestionJob, Message, MessageVersion, Project, SourceConnection,
                            CodeEntity, CodeLink, EvidenceReference, PullRequest, PRFinding)
from backend.schemas import Answer, AnswerClaim, Citation

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pg_engine():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    database = urlparse(url).path.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.fail("Integration tests only run against a dedicated database whose name ends in _test")
    engine = create_engine(sqlalchemy_url(url), pool_pre_ping=True, hide_parameters=True,
                           connect_args={"connect_timeout": 10})
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database() = :db"), {"db": database}).scalar()
        assert connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")).scalar()
    yield engine
    engine.dispose()


@pytest.fixture
def db(pg_engine):
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def base_records(db, suffix=None):
    suffix = suffix or uuid.uuid4().hex
    project = Project(owner_id=f"integration-{suffix}", repository=f"test-owner/repo-{suffix}", name="Test", status="new")
    db.add(project)
    db.flush()
    connection = SourceConnection(project_id=project.id, provider="github", origin="https://github.com",
                                  external_id=project.repository, cursor={"fixture": suffix})
    db.add(connection)
    db.flush()
    discussion = Discussion(project_id=project.id, connection_id=connection.id, external_id="1", kind="issue",
        title="Test discussion", url="https://github.com/test/repo/issues/1", source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc), raw={"fixture": True})
    db.add(discussion)
    db.flush()
    message = Message(project_id=project.id, discussion_id=discussion.id, external_id="issue:1", url=discussion.url,
        kind="body", source_created_at=datetime.now(timezone.utc))
    db.add(message)
    db.flush()
    version = MessageVersion(message_id=message.id, content_hash=hashlib.sha256((suffix + "source").encode()).hexdigest(),
        body="The team retained the synchronous API because callers depend on direct results.", raw={"body": "source"},
        source_updated_at=datetime.now(timezone.utc))
    db.add(version)
    db.flush()
    decision = Decision(project_id=project.id, discussion_id=discussion.id, stable_key="sync-api", current_revision=1)
    db.add(decision)
    db.flush()
    decision_version = DecisionVersion(decision_id=decision.id, revision=1, title="Keep synchronous API",
        claim="The team retained the synchronous API because callers depend on direct results.", scope="Client API",
        status="accepted", verification="model_supported", model="fixture", prompt_version="test-v1",
        input_hash=hashlib.sha256((suffix + "decision").encode()).hexdigest(), details={"audit": {"source": "integration"}})
    db.add(decision_version)
    db.flush()
    return project, connection, discussion, message, version, decision, decision_version


def test_jsonb_crud_vector_similarity_and_full_text(db):
    project, _, _, _, _, _, dv = base_records(db)
    assert db.scalar(select(Project).where(Project.id == project.id)).repository == project.repository
    assert db.execute(select(DecisionVersion.details["audit"]["source"].astext)
                      .where(DecisionVersion.id == dv.id)).scalar_one() == "integration"
    v1 = [0.0] * 1536
    v1[0], v1[1] = 1.0, 0.0
    v2 = [0.0] * 1536
    v2[0], v2[1] = 0.0, 1.0
    db.add_all([Embedding(project_id=project.id, version_id=dv.id, model="integration", content_hash="a" * 64, vector=v1)])
    db.flush()
    nearest = db.scalar(select(Embedding).where(Embedding.project_id == project.id)
                        .order_by(Embedding.vector.cosine_distance(v1)).limit(1))
    assert nearest.version_id == dv.id
    fts = db.execute(select(func.to_tsvector("english", DecisionVersion.title + " " + DecisionVersion.claim)
        .op("@@")(func.websearch_to_tsquery("english", "synchronous direct results"))).where(DecisionVersion.id == dv.id)).scalar_one()
    assert fts is True


def test_project_create_read_update_delete(db):
    project = Project(owner_id=f"crud-{uuid.uuid4().hex}", repository="test-owner/crud", name="Before", status="new")
    db.add(project)
    db.flush()
    project_id = project.id
    assert db.get(Project, project_id).name == "Before"
    project.name = "After"
    db.flush()
    assert db.get(Project, project_id).name == "After"
    db.delete(project)
    db.flush()
    assert db.get(Project, project_id) is None


def test_graph_traversal_decision_versions_and_fk_constraints(db):
    project, _, discussion, _, _, decision, current = base_records(db)
    alt = Alternative(version_id=current.id, approach="Make requests asynchronous", status="deferred",
                      rationale="Would require a breaking client change")
    db.add(alt)
    db.flush()
    edge = GraphEdge(project_id=project.id, source_id=decision.id, target_id=discussion.id,
        source_kind="decision", target_kind="discussion", relation="reconstructed_from", provenance="verified")
    db.add(edge)
    current2 = DecisionVersion(decision_id=decision.id, revision=2, title="Keep synchronous API",
        claim=current.claim, scope=current.scope, status="accepted", verification="needs_review", model="fixture",
        prompt_version="test-v1", input_hash="b" * 64, details={"revision": 2})
    decision.current_revision = 2
    db.add(current2)
    db.flush()
    assert db.scalar(select(GraphEdge).where(GraphEdge.project_id == project.id,
        (GraphEdge.source_id == decision.id) | (GraphEdge.target_id == discussion.id))).id == edge.id
    assert db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == decision.id,
        DecisionVersion.revision == decision.current_revision)).id == current2.id
    nested = db.begin_nested()
    db.add(Discussion(project_id=uuid.uuid4(), connection_id=uuid.uuid4(), external_id="invalid", kind="issue",
        title="orphan", url="https://example.test", source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc), raw={}))
    with pytest.raises(IntegrityError):
        db.flush()
    nested.rollback()


def test_duplicate_source_processing_deduplicates_message_revisions(db):
    suffix = uuid.uuid4().hex
    project = Project(owner_id=f"integration-{suffix}", repository=f"test-owner/repo-{suffix}", name="Test", status="new")
    db.add(project)
    db.flush()
    bundle = {"issue": {"id": 1, "number": 1, "title": "Idempotent ingestion", "html_url": "https://github.com/test/repo/issues/1",
        "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T00:00:00Z",
        "user": {"id": 7, "login": "test-user", "html_url": "https://github.com/test-user"}, "body": "Keep source content stable."},
        "comments": [], "reviews": [], "review_comments": [], "timeline": []}
    first = persist_github(db, project, bundle)
    second = persist_github(db, project, bundle)
    assert first.id == second.id
    assert db.scalar(select(func.count()).select_from(Message).where(Message.discussion_id == first.id)) == 1
    assert db.scalar(select(func.count()).select_from(MessageVersion).join(Message)
                     .where(Message.discussion_id == first.id)) == 1


def test_retrieval_is_relevant_and_project_scoped(db):
    project, *_rest, version = base_records(db)
    rows, _ = search(db, project.id, "synchronous API direct results")
    assert any(row["version"].id == version.id for row in rows)
    irrelevant, _ = search(db, project.id, "quantum banana telescope")
    assert irrelevant == []
    other = Project(owner_id=f"other-{uuid.uuid4().hex}", repository="other-owner/repo", name="Other")
    db.add(other)
    db.flush()
    assert search(db, other.id, "synchronous API direct results")[0] == []


def test_unsupported_extraction_abstains_without_creating_decision(db, monkeypatch):
    project, _, discussion, _, source, *_ = base_records(db)
    monkeypatch.setattr(memory, "verify_semantics", lambda *args: Verification(
        supported=False, explicit_disposition=False, rationale="Opinion without support"))
    claim = DecisionClaim(key="speculative-change", title="Speculative change",
        claim="The project adopted a new transport behavior.", scope="API", status="accepted",
        citations=[Citation(message_version_id=source.id, quote="The team retained the synchronous API because callers depend on direct results.")],
        alternatives=[], open_questions=[], possible_supersession=[])
    assert memory.persist_extraction(db, discussion, Extraction(decisions=[claim], abstention_reason=""), "fixture") == []
    assert db.scalar(select(func.count()).select_from(Decision).where(Decision.stable_key == claim.key)) == 0


def test_supported_new_evidence_versions_superseded_decision(db, monkeypatch):
    project, _, discussion, _, source, old_decision, old_version = base_records(db)
    monkeypatch.setattr(memory, "verify_semantics", lambda *args: Verification(
        supported=True, explicit_disposition=True, rationale="Later maintainer statement is explicit"))
    claim = DecisionClaim(key="new-sync-policy", title="Later sync policy",
        claim="The project kept synchronous calls after considering caller dependence.", scope="API", status="accepted",
        citations=[Citation(message_version_id=source.id, quote="The team retained the synchronous API because callers depend on direct results.")],
        alternatives=[], open_questions=[], possible_supersession=["sync-api"])
    saved = memory.persist_extraction(db, discussion, Extraction(decisions=[claim], abstention_reason=""), "fixture")
    db.flush()
    db.refresh(old_decision)
    old_current = db.scalar(select(DecisionVersion).where(DecisionVersion.decision_id == old_decision.id,
                                      DecisionVersion.revision == old_decision.current_revision))
    assert len(saved) == 1
    assert old_current.status == "superseded"
    assert old_current.revision == old_version.revision + 1
    assert db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.relation == "supersedes")) == 1


def test_same_stable_decision_is_deduplicated_across_discussions(db, monkeypatch):
    project, connection, _, _, _, original, _ = base_records(db)
    later = Discussion(project_id=project.id, connection_id=connection.id, external_id="2", kind="issue",
        title="Follow-up", url="https://github.com/test/repo/issues/2", source_created_at=datetime.now(timezone.utc),
        source_updated_at=datetime.now(timezone.utc), raw={})
    db.add(later)
    db.flush()
    message = Message(project_id=project.id, discussion_id=later.id, external_id="comment:2",
        url=later.url, kind="comment", source_created_at=datetime.now(timezone.utc))
    db.add(message)
    db.flush()
    version = MessageVersion(message_id=message.id, content_hash="c" * 64,
        body="We will keep the synchronous API for existing callers.", raw={}, source_updated_at=datetime.now(timezone.utc))
    db.add(version)
    db.flush()
    monkeypatch.setattr(memory, "verify_semantics", lambda *args: Verification(
        supported=True, explicit_disposition=True, rationale="Explicit maintainer statement"))
    claim = DecisionClaim(key="sync-api", title="Keep synchronous API",
        claim="The project retained synchronous calls for existing callers.", scope="API", status="accepted",
        citations=[Citation(message_version_id=version.id, quote=version.body)], alternatives=[],
        open_questions=[], possible_supersession=[])
    result = memory.persist_extraction(db, later, Extraction(decisions=[claim], abstention_reason=""), "fixture")
    db.flush()
    assert len(result) == 1
    assert result[0].decision_id == original.id
    assert db.scalar(select(func.count()).select_from(Decision).where(Decision.project_id == project.id,
        Decision.stable_key == "sync-api")) == 1
    assert db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.source_id == original.id,
        GraphEdge.target_id == later.id, GraphEdge.relation == "reconstructed_from")) == 1


def add_pr_and_code(db, project, discussion, decision_version, path="src/client.py", sha="a" * 40, link=True):
    pr = PullRequest(project_id=project.id, discussion_id=discussion.id, number=17,
        title="Preserve retry behavior", url="https://github.com/test/repo/pull/17", head_sha=sha,
        state="open", details={"body": "Keep client retries compatible.", "files": [
            {"filename": path, "patch": "+ # keep retry compatibility"}]})
    db.add(pr)
    entity = CodeEntity(project_id=project.id, path=path, symbol="request", kind="function",
        commit_sha=sha, details={"source": "treesitter"})
    db.add(entity)
    db.flush()
    if link:
        db.add(CodeLink(version_id=decision_version.id, entity_id=entity.id, provenance="PR source path",
            status="inferred", proof_url=pr.url))
    db.flush()
    return pr, entity


def test_relevant_pr_creates_cited_historical_finding(db, monkeypatch):
    from backend import pr_intelligence
    from backend.pr_intelligence import Conflict
    from backend.schemas import Verification
    project, _, discussion, _, source, decision, version = base_records(db)
    db.add(EvidenceReference(version_id=version.id, message_version_id=source.id, claim=version.claim,
        quote="The team retained the synchronous API because callers depend on direct results.",
        verification="model_supported"))
    pr, _ = add_pr_and_code(db, project, discussion, version)
    monkeypatch.setattr(pr_intelligence, "structured", lambda *args, **kwargs: Conflict(conflict=True,
        explanation="The change removes direct synchronous results relied on by callers.",
        citations=[Citation(message_version_id=source.id,
            quote="The team retained the synchronous API because callers depend on direct results.")]))
    from backend import inference
    monkeypatch.setattr(inference, "verify_semantics", lambda *args: Verification(
        supported=True, explicit_disposition=True, rationale="The quote establishes the constraint."))
    findings = pr_intelligence.analyze_pr(db, project, pr)
    assert len(findings) == 1
    assert findings[0].version_id == version.id
    assert findings[0].head_sha == pr.head_sha
    assert findings[0].publication == "verified"


def test_unrelated_pr_has_no_historical_finding(db, monkeypatch):
    from backend import pr_intelligence
    project, _, discussion, _, _, _, version = base_records(db)
    pr, _ = add_pr_and_code(db, project, discussion, version, path="unrelated/charting.py", sha="b" * 40, link=False)
    called = []
    monkeypatch.setattr(pr_intelligence, "structured", lambda *args, **kwargs: called.append(True))
    assert pr_intelligence.analyze_pr(db, project, pr) == []
    assert called == []


def test_superseded_decision_is_not_pr_authority(db, monkeypatch):
    from backend import pr_intelligence
    project, _, discussion, _, _, decision, old = base_records(db)
    newer = DecisionVersion(decision_id=decision.id, revision=2, title=old.title, claim=old.claim,
        scope=old.scope, status="superseded", verification="model_supported", model="fixture",
        prompt_version="test-v1", input_hash="d" * 64, details={})
    db.add(newer)
    decision.current_revision = 2
    db.flush()
    pr, _ = add_pr_and_code(db, project, discussion, old)
    called = []
    monkeypatch.setattr(pr_intelligence, "structured", lambda *args, **kwargs: called.append(True))
    assert pr_intelligence.analyze_pr(db, project, pr) == []
    assert called == []


def test_chat_answers_with_resolved_source_and_logs_usage(db, monkeypatch):
    from backend import api
    project, _, _, _, source, _, version = base_records(db)
    db.add(EvidenceReference(version_id=version.id, message_version_id=source.id, claim=version.claim,
        quote="The team retained the synchronous API because callers depend on direct results.",
        verification="model_supported"))
    monkeypatch.setattr(api, "budget", lambda *args: 1)
    monkeypatch.setattr(api, "search", lambda *args, **kwargs: ([{"version": version, "score": 1}], "full_text"))
    monkeypatch.setattr(api, "structured", lambda *args, **kwargs: (Answer(claims=[AnswerClaim(
        text="The team kept the synchronous API because callers depended on direct results.",
        citations=[Citation(message_version_id=source.id,
            quote="The team retained the synchronous API because callers depend on direct results.")])],
        abstention_reason=""), {"prompt_tokens": 42, "completion_tokens": 18, "cost": 0.00002}))
    from backend.schemas import Verification
    monkeypatch.setattr(api, "verify_semantics", lambda *args: Verification(supported=True,
        explicit_disposition=True, rationale="The citation supports the claim."))
    result = api.answer_question(project.id, api.AskRequest(question="Why was the synchronous API retained?"),
        db, project.owner_id)
    assert "synchronous API" in result["answer"]
    assert result["citations"][0]["url"] == "https://github.com/test/repo/issues/1"
    assistant = db.scalar(select(api.m.ChatMessage).where(api.m.ChatMessage.role == "assistant"))
    assert assistant.prompt_tokens == 42 and assistant.completion_tokens == 18
    assert assistant.cost_usd == pytest.approx(0.00002)


def test_chat_abstains_when_retrieval_has_no_evidence(db, monkeypatch):
    from backend import api
    project, *_ = base_records(db)
    monkeypatch.setattr(api, "search", lambda *args, **kwargs: ([], "full_text"))
    monkeypatch.setattr(api, "structured", lambda *args, **kwargs: pytest.fail("no model call without evidence"))
    result = api.answer_question(project.id, api.AskRequest(question="What is the unrelated quantum rocket?"),
        db, project.owner_id)
    assert "couldn’t find sufficient historical evidence" in result["answer"]
    assert result["citations"] == []


def test_alternative_explorer_keeps_all_suggestions_unvalidated(db, monkeypatch):
    from backend import pr_intelligence
    from backend.pr_intelligence import HistoricalConstraint, Suggestion, Suggestions
    from backend.schemas import Verification
    project, _, discussion, _, source, _, version = base_records(db)
    db.add(EvidenceReference(version_id=version.id, message_version_id=source.id, claim=version.claim,
        quote="The team retained the synchronous API because callers depend on direct results.",
        verification="model_supported"))
    db.add(Alternative(version_id=version.id, approach="Make calls asynchronous", status="rejected",
        rationale="Callers depend on direct results."))
    db.flush()
    # The cited original statement is sufficient to test evidence resolution; the output stays unvalidated.
    pr, _ = add_pr_and_code(db, project, discussion, version)
    citation = Citation(message_version_id=source.id,
        quote="The team retained the synchronous API because callers depend on direct results.")
    generated = Suggestions(objective="Keep retry behavior compatible", historical_constraints=[
        HistoricalConstraint(statement="Existing callers depend on direct synchronous results.", citations=[citation])],
        suggestions=[
            Suggestion(approach="Keep the synchronous interface and add bounded retries.", complexity="Low", maintainability="High", compatibility="Preserves callers", risk="Retry storms", historical_statement="Callers depend on direct results.", repeats_rejected_alternative=False, citations=[citation]),
            Suggestion(approach="Move transport work behind a callback adapter.", complexity="Medium", maintainability="Medium", compatibility="Needs an adapter", risk="Lifecycle changes", historical_statement="Novel approach without a verified precedent.", repeats_rejected_alternative=False, citations=[]),
        ])
    from backend import retrieval, inference
    monkeypatch.setattr(retrieval, "search", lambda *args, **kwargs: ([], "full_text"))
    monkeypatch.setattr(pr_intelligence, "structured", lambda *args, **kwargs: generated)
    monkeypatch.setattr(inference, "verify_semantics", lambda *args: Verification(supported=True,
        explicit_disposition=False, rationale="Supported by the excerpt."))
    result = pr_intelligence.explore_alternatives(db, project, pr, "Keep retry behavior compatible")
    assert len(result["suggestions"]) == 2
    assert all(s["validation_status"] == "unvalidated" for s in result["suggestions"])
    assert result["suggestions"][1]["historical_status"] == "novel_unvalidated"


def test_repeated_pr_publication_updates_same_comment(db, monkeypatch):
    from backend import pr_intelligence
    from backend import config
    project, _, discussion, _, source, _, version = base_records(db)
    db.add(EvidenceReference(version_id=version.id, message_version_id=source.id, claim=version.claim,
        quote="The team retained the synchronous API because callers depend on direct results.",
        verification="model_supported"))
    pr, _ = add_pr_and_code(db, project, discussion, version)
    finding = PRFinding(pr_id=pr.id, version_id=version.id, head_sha=pr.head_sha, relevance=1.0,
        explanation="Synchronous results are a historical constraint.", publication="verified")
    db.add(finding)
    db.flush()
    monkeypatch.setattr(config.settings(), "github_publish_enabled", True)
    monkeypatch.setattr(config.settings(), "github_app_id", "123")
    class FakeGitHub:
        def __init__(self): self.comments=[]; self.posts=0
        def public_repository(self, repo): return {"full_name": repo}
        def get(self, path): return {"head":{"sha":pr.head_sha},"state":"open"}
        def pages(self, path): return list(self.comments)
        def request(self, path, method="GET", json=None):
            if method == "POST":
                self.posts+=1
                row={"id":99,"body":json["body"],"performed_via_github_app":{"id":123}}
                self.comments.append(row)
                return type("Response",(),{"json":lambda _self:row})()
            return type("Response",(),{"json":lambda _self:self.comments[0]})()
        def close(self): pass
    fake=FakeGitHub()
    monkeypatch.setattr(pr_intelligence, "installation_client", lambda _repo: fake)
    assert pr_intelligence.publish_findings(db, project, pr, [finding]) == "published"
    assert pr_intelligence.publish_findings(db, project, pr, [finding]) == "unchanged"
    assert fake.posts == 1


def test_repeated_verified_pull_request_webhook_dispatches_one_job(db, monkeypatch):
    import hashlib
    import hmac
    import json
    from fastapi.testclient import TestClient
    from backend.api import app
    from backend.db import get_db
    from backend import config, jobs
    project = Project(owner_id=f"webhook-{uuid.uuid4().hex}", repository="test-owner/webhook-repo",
        name="Webhook test")
    db.add(project)
    db.flush()
    monkeypatch.setattr(config.settings(), "github_webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(config.settings(), "github_installation_id", "42")
    monkeypatch.setattr(jobs, "recover_jobs", lambda: 1)
    payload = {"action": "synchronize", "installation": {"id": 42},
        "repository": {"full_name": project.repository, "private": False},
        "pull_request": {"number": 17}}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"test-webhook-secret", raw, hashlib.sha256).hexdigest()
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            headers = {"X-Hub-Signature-256": signature, "X-GitHub-Delivery": "delivery-pr-17",
                       "X-GitHub-Event": "pull_request"}
            first = client.post("/webhooks/github", content=raw, headers=headers)
            repeated = client.post("/webhooks/github", content=raw, headers=headers)
        assert first.status_code == 202 and first.json()["status"] == "dispatched"
        assert repeated.status_code == 202 and repeated.json()["status"] == "duplicate"
        assert db.scalar(select(func.count()).select_from(IngestionJob).where(
            IngestionJob.project_id == project.id, IngestionJob.kind == "github_pr_event")) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_failed_job_retry_preserves_cursor_and_dispatches(db, monkeypatch):
    project, *_ = base_records(db)
    job = IngestionJob(project_id=project.id, kind="github", status="failed", progress=65,
                       cursor={"completed": [1]}, attempts=2, error="transient")
    db.add(job)
    db.flush()
    dispatched = []
    monkeypatch.setattr(api, "enqueue", lambda job_id: dispatched.append(job_id))
    result = api.retry_job(project.id, job.id, db, project.owner_id)
    assert result["status"] == "queued"
    assert result["cursor"] == {"completed": [1]}
    assert dispatched == [job.id]


def test_job_progress_constraints(db):
    project, *_ = base_records(db)
    db.add(IngestionJob(project_id=project.id, kind="github", status="queued", progress=25,
                        cursor={}, attempts=0))
    db.flush()


def test_concurrent_project_writes(pg_engine):
    owner = f"integration-concurrent-{uuid.uuid4().hex}"
    repos = [f"test-owner/repo-{uuid.uuid4().hex}" for _ in range(2)]
    def insert(repo):
        with Session(pg_engine) as session:
            row = Project(owner_id=owner, repository=repo, name="Concurrent", status="new")
            session.add(row)
            session.commit()
            return row.id
    ids = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(insert, repos))
        with Session(pg_engine) as session:
            assert session.scalar(select(func.count()).select_from(Project).where(Project.id.in_(ids))) == 2
    finally:
        with Session(pg_engine) as session:
            session.execute(delete(Project).where(Project.owner_id == owner))
            session.commit()
