"""Relational evidence and interpretation model. Schema changes go through Alembic."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (String, Text, DateTime, ForeignKey, UniqueConstraint, Integer, Boolean,
                        Float, Index, CheckConstraint, literal_column)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Record, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("owner_id", "repository"),)
    owner_id: Mapped[str] = mapped_column(String(200), index=True)
    repository: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="new")


class SourceConnection(Record, Base):
    __tablename__ = "source_connections"
    __table_args__ = (UniqueConstraint("project_id", "provider", "origin"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    origin: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(String(200), default="")
    cursor: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="not_synced")
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contributor(Record, Base):
    __tablename__ = "contributors"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)
    provider: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(100))
    handle: Mapped[str] = mapped_column(String(200))
    profile_url: Mapped[str] = mapped_column(Text)


class IdentityLink(Record, Base):
    __tablename__ = "identity_links"
    __table_args__ = (CheckConstraint("left_id <> right_id", name="ck_identity_links_distinct"),
                      UniqueConstraint("left_id", "right_id", name="uq_identity_links_pair"))
    left_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contributors.id"))
    right_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contributors.id"))
    proof_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="needs_review")


class Discussion(Record, Base):
    __tablename__ = "discussions"
    __table_args__ = (UniqueConstraint("connection_id", "external_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_connections.id"))
    external_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)


class Message(Record, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("discussion_id", "external_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    discussion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discussions.id"), index=True)
    contributor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contributors.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"))
    external_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40))
    source_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageVersion(Record, Base):
    __tablename__ = "message_versions"
    __table_args__ = (UniqueConstraint("message_id", "content_hash"),)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Decision(Record, Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("discussion_id", "stable_key"),
                      CheckConstraint("current_revision > 0", name="ck_decision_revision_positive"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    discussion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discussions.id"))
    stable_key: Mapped[str] = mapped_column(String(100))
    current_revision: Mapped[int] = mapped_column(Integer, default=1)


class DecisionVersion(Record, Base):
    __tablename__ = "decision_versions"
    __table_args__ = (UniqueConstraint("decision_id", "revision"),
                     Index("ix_decision_fts", literal_column("to_tsvector('english', title || ' ' || claim)"),
                           postgresql_using="gin"))
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decisions.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    claim: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    verification: Mapped[str] = mapped_column(String(40), default="needs_review")
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class Alternative(Record, Base):
    __tablename__ = "alternatives"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"), index=True)
    approach: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    rationale: Mapped[str] = mapped_column(Text)


class EvidenceReference(Record, Base):
    __tablename__ = "evidence_references"
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"), index=True)
    alternative_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alternatives.id"))
    message_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("message_versions.id"))
    claim: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String(40))


class CodeEntity(Record, Base):
    __tablename__ = "code_entities"
    __table_args__ = (UniqueConstraint("project_id", "path", "symbol", "commit_sha"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    path: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="file")
    commit_sha: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class CodeLink(Record, Base):
    __tablename__ = "code_links"
    __table_args__ = (UniqueConstraint("version_id", "entity_id"),)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"))
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("code_entities.id"))
    provenance: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40))
    proof_url: Mapped[str] = mapped_column(Text)


class GraphEdge(Record, Base):
    __tablename__ = "graph_edges"
    __table_args__ = (UniqueConstraint("project_id", "source_id", "target_id", "relation"),
        CheckConstraint("source_id <> target_id", name="ck_graph_no_self_edge"),
        CheckConstraint("source_kind IN ('decision','discussion','message','alternative','code_entity','pull_request')",
                        name="ck_graph_source_kind"),
        CheckConstraint("target_kind IN ('decision','discussion','message','alternative','code_entity','pull_request')",
                        name="ck_graph_target_kind"),
        Index("ix_graph_edges_project_source", "project_id", "source_id"),
        Index("ix_graph_edges_project_target", "project_id", "target_id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_kind: Mapped[str] = mapped_column(String(40))
    target_kind: Mapped[str] = mapped_column(String(40))
    relation: Mapped[str] = mapped_column(String(80))
    provenance: Mapped[str] = mapped_column(String(40))


class Embedding(Record, Base):
    __tablename__ = "embeddings"
    __table_args__ = (UniqueConstraint("version_id", "model"),
                     Index("ix_embedding_cosine", "vector", postgresql_using="hnsw",
                           postgresql_ops={"vector": "vector_cosine_ops"}))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"))
    model: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[list[float]] = mapped_column(Vector(1536))


class PullRequest(Record, Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("project_id", "number"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    discussion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discussions.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    head_sha: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSONB)


class PRFinding(Record, Base):
    __tablename__ = "pr_findings"
    __table_args__ = (UniqueConstraint("pr_id", "head_sha", "version_id"),)
    pr_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pull_requests.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"))
    head_sha: Mapped[str] = mapped_column(String(64))
    relevance: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    publication: Mapped[str] = mapped_column(String(40), default="draft")
    external_comment_id: Mapped[str | None] = mapped_column(String(100))


class AISuggestion(Record, Base):
    __tablename__ = "ai_suggestions"
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pr_findings.id"))
    model: Mapped[str] = mapped_column(String(200))
    approach: Mapped[str] = mapped_column(Text)
    tradeoffs: Mapped[str] = mapped_column(Text)
    constraints: Mapped[str] = mapped_column(Text)
    untested: Mapped[bool] = mapped_column(Boolean, default=True)


class ChatSession(Record, Base):
    __tablename__ = "chat_sessions"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(200))


class ChatMessage(Record, Base):
    __tablename__ = "chat_messages"
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)


class IngestionJob(Record, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_jobs_project_created", "project_id", "created_at"),
                      CheckConstraint("progress >= 0 AND progress <= 100", name="ck_job_progress_range"),
                      CheckConstraint("attempts >= 0", name="ck_job_attempts_nonnegative"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="github")
    status: Mapped[str] = mapped_column(String(40), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    cursor: Mapped[dict] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDelivery(Record, Base):
    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(200), unique=True)
    event: Mapped[str] = mapped_column(String(80))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40), default="received")


class Feedback(Record, Base):
    __tablename__ = "feedback"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision_versions.id"))
    actor: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text)


class EvaluationDataset(Record, Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("name", "version"),)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(100))
    input_manifest: Mapped[dict] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    answer_key_hash: Mapped[str] = mapped_column(String(64))
    split: Mapped[str] = mapped_column(String(40))


class EvaluationRun(Record, Base):
    __tablename__ = "evaluation_runs"
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_datasets.id"))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40))
