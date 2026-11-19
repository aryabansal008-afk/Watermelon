# Backend and database setup

## Current Neon development database

The connected Neon project is **WATERMELON** (`floral-smoke-14061325`). The development branch is `development` (`br-snowy-darkness-azx68b1r`) and runs PostgreSQL 17. Read-only inspection found the `vector` extension at 0.8.7 and the canonical project, source, evidence, decision, code, graph, PR, chat, job, webhook, and evaluation tables. The production `main` branch was not changed. A separate empty `watermelon_test` database was created on the development branch for integration tests.

Use Neon’s **pooled** connection string for `DATABASE_URL`. Use the **direct/unpooled** connection string for `DATABASE_URL_UNPOOLED`, Alembic, backups, and any operation requiring session state. `TEST_DATABASE_URL` must target a disposable database with a name ending in `_test`; never point it at production. Keep all three connection strings in the backend `.env`; do not prefix them with `NEXT_PUBLIC_` or pass them to the browser.

If connecting a different Neon account, select the existing WATERMELON project (or the intended development project) in the Neon plugin, select its development branch and database, and copy both pooled and direct connection strings from Neon. Do not run schema changes against `main` as part of local setup.

## Local PostgreSQL and Redis

```sh
uv sync --frozen
docker compose --profile local-db up -d postgres redis
uv run alembic upgrade head
```

The local Postgres service uses `pgvector/pgvector:pg17`, matching the required vector extension. Set local `DATABASE_URL` and `DATABASE_URL_UNPOOLED` to the local service. Redis is used for RQ dispatch and atomic inference budgets. Start the API and worker in separate terminals:

```sh
uv run uvicorn backend.api:app --reload
uv run python -m backend.worker
```

## Migrations

Migrations are the source of truth; do not use `Base.metadata.create_all()` for application setup. Run upgrades using the direct connection:

```sh
uv run alembic upgrade head
uv run alembic current
```

The initial migration installs `vector` and creates every canonical table. The follow-up migration adds typed graph endpoint checks, self-edge prevention, graph traversal indexes, bounded job state, positive decision revisions, and identity-link uniqueness. Downgrades remove these constraints and indexes; review any downgrade against retained evidence first.

## Integration tests

The PostgreSQL integration suite is opt-in and refuses databases whose name does not end with `_test`. Migrate the disposable test database, then run:

```sh
DATABASE_URL_UNPOOLED="$TEST_DATABASE_URL" uv run alembic upgrade head
uv run pytest -q
```

Use `TEST_DATABASE_URL` only for the integration-test process. The tests run their CRUD, JSONB, vector, full-text, graph, decision-version, source-deduplication, foreign-key, job-state, and concurrent-write checks inside rolled-back transactions except for the explicitly concurrent inserts, which delete their isolated test rows in a `finally` block. Unit tests run without any database connection.

## API contract

The FastAPI application publishes its live OpenAPI contract at `/openapi.json`. Routes include project CRUD; issue/PR ingestion; `POST /v1/projects/{id}/reconcile` for incremental GitHub sync; `POST /v1/projects/{id}/github-discussions/{number}/ingest` for GraphQL Discussions; allowlisted Discourse topic ingestion by origin/topic ID or topic URL; job status and retry; decision list/detail/feedback; discussions; search with status/`as_of`; graph, timeline, code and PR analysis; chat; integrations; and benchmark metadata. Search returns `rank_score`, explicitly a retrieval rank rather than a probability of factual correctness. Errors use `{ "error": { "code", "message", "request_id" } }`. `/health` is process liveness; `/health/database` checks PostgreSQL and vector availability; `/ready` checks PostgreSQL and Redis with authenticated application credentials.

GitHub ingestion fetches issues/comments/timeline and, for PRs, metadata/reviews/inline comments/commits/changed files. Public GitHub Discussions use GraphQL comment and nested-reply pagination. REST component failures are persisted as partial coverage; retry reopens affected records. Reconciliation selects changed issues/PRs from the last successful watermark. GitHub cannot recover deleted comments or every historic edit. Discourse supports public, explicitly allowlisted sites and stores post IDs and revisions from the public topic API; it does not access private content.

Interpretation uses two stages: chronological decision-span detection followed by structured decision/alternative extraction. Exact source quotes and immutable message-version IDs are checked before writes; an independent verifier must support a claim, and explicit dispositions are required for accepted/rejected/deferred/superseded/reverted status. Unsupported claims and alternatives abstain. Decision revisions and supersession edges are versioned. Project-scoped search combines PostgreSQL FTS, optional pgvector, exact issue/PR references, and code paths/symbols. Tree-sitter parsing is selective for Python, TypeScript, and TSX at PR head. Renames use GitHub's `previous_filename`; PR/file relevance links are marked inferred unless directly proven.

Redis failures persist queued work as `enqueue_failed`; `POST .../jobs/{job_id}/retry` and the RQ reconciliation function recover durable jobs. Source acquisition and structured interpretation are separate transaction boundaries, so retries do not duplicate source messages or revisions. The AI provider is called only when server-side credentials and atomic rate budgets are available. `.env` and `.env.*` are ignored by Git; `.env.example` is the template. Verify with `git check-ignore -v .env` and never pass provider keys to the frontend. Redis is not running in the current workstation environment, so real OpenRouter extraction cannot execute until Redis is configured; the worker fails closed before calling the provider.

## Current verification status

The public candidate source [encode/httpx issue #3433](https://github.com/encode/httpx/issues/3433) currently resolves. Its activity records the issue being closed as “not planned” and the maintainer saying the behavior change would not be reverted. The thread also records the proposed alternative of merging query parameters (and arguments for why). This is source material only, **not a Watermelon extraction result**: no model output or decision was persisted because the Redis budget service is unavailable. Do not present this as reconstructed output until the live pipeline verifies and stores it.

The tests cover span detection, chronology, positive structured extraction shape, abstention, PostgreSQL CRUD/JSONB/vector/FTS/graph traversal, source deduplication, foreign keys, concurrent writes, relevant/irrelevant retrieval, and decision supersession. Run `TEST_DATABASE_NAME=watermelon_test uv run python scripts/run_pg_integration.py`; this uses only the disposable `_test` database. Neon production/main remains untouched.
