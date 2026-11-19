from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.connectors import repository_name


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(StrictModel):
    message_version_id: UUID
    quote: str = Field(min_length=8, max_length=5000)


class AlternativeClaim(StrictModel):
    approach: str = Field(min_length=3, max_length=1000)
    status: Literal["rejected", "deferred", "considered", "accepted"]
    rationale: str = Field(min_length=3, max_length=3000)
    citations: list[Citation] = Field(min_length=1, max_length=8)


class DecisionClaim(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9_-]{3,100}$")
    title: str = Field(min_length=3, max_length=200)
    claim: str = Field(min_length=10, max_length=4000)
    scope: str = Field(max_length=1000)
    status: Literal["proposed", "accepted", "rejected", "deferred", "unresolved", "superseded", "reverted"]
    citations: list[Citation] = Field(min_length=1, max_length=8)
    alternatives: list[AlternativeClaim] = Field(max_length=8)
    open_questions: list[str] = Field(max_length=10)
    possible_supersession: list[str] = Field(max_length=5)


class Extraction(StrictModel):
    # The model emits at most 12 per window; aggregation can span many windows.
    decisions: list[DecisionClaim] = Field(max_length=100)
    abstention_reason: str


class ExtractionBatch(StrictModel):
    decisions: list[DecisionClaim] = Field(max_length=12)
    abstention_reason: str


class DecisionSpan(StrictModel):
    message_version_ids: list[UUID] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=3, max_length=500)


class SpanDetection(StrictModel):
    spans: list[DecisionSpan] = Field(max_length=12)
    abstention_reason: str


class Verification(StrictModel):
    supported: bool
    explicit_disposition: bool
    rationale: str


class ProjectCreate(StrictModel):
    repository: str

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value):
        return repository_name(value)


class IngestRequest(StrictModel):
    numbers: list[int] = Field(min_length=1, max_length=15)
    extract: bool = True

    @field_validator("numbers")
    @classmethod
    def valid_numbers(cls, value):
        if any(n <= 0 for n in value) or len(set(value)) != len(value):
            raise ValueError("Issue/PR numbers must be positive and unique")
        return value


class AskRequest(StrictModel):
    question: str = Field(min_length=3, max_length=3000)
    session_id: UUID | None = None


class AlternativeRequest(StrictModel):
    objective: str = Field(min_length=8, max_length=2000)


class AnswerClaim(StrictModel):
    text: str = Field(max_length=3000)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class Answer(StrictModel):
    claims: list[AnswerClaim] = Field(max_length=8)
    abstention_reason: str


class FeedbackRequest(StrictModel):
    category: Literal["incorrect", "unsupported", "outdated", "helpful"]
    comment: str = Field(min_length=3, max_length=2000)


class DiscourseRequest(StrictModel):
    origin: str | None = None
    topic_id: int | None = Field(default=None, gt=0)
    topic_url: str | None = Field(default=None, max_length=2000)

    @field_validator("topic_url")
    @classmethod
    def valid_topic_url(cls, value):
        if value and (not value.startswith("https://") or "@" in value or "?" in value or "#" in value):
            raise ValueError("Use a public HTTPS Discourse topic URL without credentials or query parameters")
        return value

    @model_validator(mode="after")
    def require_source(self):
        if self.topic_url is None and (self.origin is None or self.topic_id is None):
            raise ValueError("Provide topic_url or both origin and topic_id")
        if self.topic_url is not None and (self.origin is not None or self.topic_id is not None):
            raise ValueError("Use topic_url or origin and topic_id, not both")
        return self


T = TypeVar("T")


class ApiPage(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: str
    repository: str
    name: str
    status: str
    created_at: datetime

    model_config = ConfigDict(extra="ignore")


class ProjectDetailResponse(ProjectResponse):
    counts: dict[str, int]


class JobResponse(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    status: str
    progress: int
    error: str | None
    cursor: dict
    attempts: int
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(extra="ignore")
