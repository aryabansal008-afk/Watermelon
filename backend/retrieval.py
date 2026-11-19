import hashlib
import httpx
import re
from datetime import datetime
from sqlalchemy import select, func, or_
from backend.models import Decision, DecisionVersion, Embedding, Discussion, PullRequest, CodeEntity, CodeLink
from backend.config import settings
from backend.inference import budget, redis_connection, InferenceUnavailable


def embedding(text: str):
    config = settings()
    if not config.openrouter_api_key or not config.openrouter_embedding_model:
        return None
    if len(text) > 12000:
        raise InferenceUnavailable("Embedding input exceeds budget")
    budget(redis_connection(), "embedding:budget", config.model_calls_per_day * 10, 86400)
    with httpx.Client(timeout=40, follow_redirects=False) as client:
        response = client.post("https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            json={"model": config.openrouter_embedding_model, "input": text, "dimensions": 1536})
        if response.status_code != 200:
            raise InferenceUnavailable("Embedding provider unavailable")
        vector = response.json()["data"][0]["embedding"]
        if len(vector) != 1536:
            raise InferenceUnavailable("Embedding dimensions do not match the schema")
        return vector


def index_version(db, project_id, version):
    value = embedding(version.title + "\n" + version.claim)
    if value is None:
        return False
    from backend.memory import get_or_create
    get_or_create(db, Embedding, {"version_id": version.id, "model": settings().openrouter_embedding_model},
        project_id=project_id, content_hash=hashlib.sha256(version.claim.encode()).hexdigest(), vector=value)
    return True


def search(db, project_id, query: str, limit=20, status: str | None = None,
           as_of: datetime | None = None):
    vector = func.to_tsvector("english", DecisionVersion.title + " " + DecisionVersion.claim)
    terms = func.websearch_to_tsquery("english", query)
    base = select(DecisionVersion).join(Decision).where(Decision.project_id == project_id)
    if as_of:
        base = base.where(DecisionVersion.created_at <= as_of).where(DecisionVersion.revision ==
            select(func.max(DecisionVersion.revision)).where(DecisionVersion.decision_id == Decision.id,
                DecisionVersion.created_at <= as_of).scalar_subquery())
    else:
        base = base.where(Decision.current_revision == DecisionVersion.revision)
    if status:
        base = base.where(DecisionVersion.status == status)
    lexical = db.scalars(base.where(vector.op("@@")(terms))
                         .order_by(func.ts_rank_cd(vector, terms).desc()).limit(limit * 3)).all()
    mode = "full_text"
    ranking = {v.id: {"version": v, "score": 1 / (60 + i)} for i, v in enumerate(lexical, 1)}
    # Exact issue / PR references and file or symbol associations complement lexical ranking.
    exact_numbers = {int(n) for n in re.findall(r"(?<![A-Za-z0-9])#(\d+)\b", query)}
    exact_ids = set()
    if exact_numbers:
        exact_ids = set(db.scalars(select(DecisionVersion.id).join(Decision).join(Discussion,
            Discussion.id == Decision.discussion_id).outerjoin(PullRequest,
            PullRequest.discussion_id == Discussion.id).where(Decision.project_id == project_id,
            or_(Discussion.external_id.in_([str(n) for n in exact_numbers]),
                PullRequest.number.in_(exact_numbers)),
            Decision.current_revision == DecisionVersion.revision).limit(limit * 3)).all())
    code_terms = [term.strip("`'\".,:()") for term in query.split() if "/" in term or re.match(r"^[A-Za-z_$][\w$]{2,}$", term)]
    if code_terms:
        conditions = [or_(CodeEntity.path.ilike(f"%{term}%"), CodeEntity.symbol.ilike(f"%{term}%")) for term in code_terms]
        code_ids = db.scalars(select(CodeLink.version_id).join(CodeEntity).where(
            CodeLink.version_id.in_(select(DecisionVersion.id).join(Decision).where(Decision.project_id == project_id,
                Decision.current_revision == DecisionVersion.revision)), *conditions).limit(limit * 3)).all()
        exact_ids.update(code_ids)
    for version_id in exact_ids:
        version = db.get(DecisionVersion, version_id)
        if version and (status is None or version.status == status):
            ranking.setdefault(version.id, {"version": version, "score": 0})["score"] += 1 / 60
    config = settings()
    if config.openrouter_embedding_model and db.scalar(select(Embedding.id).where(
        Embedding.project_id == project_id, Embedding.model == config.openrouter_embedding_model).limit(1)):
        try:
            query_vector = embedding(query)
            semantic = db.scalars(base.join(Embedding, Embedding.version_id == DecisionVersion.id)
                .where(Embedding.project_id == project_id, Embedding.model == config.openrouter_embedding_model)
                .order_by(Embedding.vector.cosine_distance(query_vector)).limit(limit * 3)).all()
            for i, v in enumerate(semantic, 1):
                row = ranking.setdefault(v.id, {"version": v, "score": 0})
                row["score"] += 1 / (60 + i)
            mode = "hybrid"
        except Exception:
            mode = "full_text_embedding_unavailable"
    return sorted(ranking.values(), key=lambda row: row["score"], reverse=True)[:limit], mode
