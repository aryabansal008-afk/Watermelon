# Deployment and integrations

## Runtime layout

Deploy three independently restartable services from this repository: Next.js frontend, FastAPI API, and RQ worker. Add Redis and Neon PostgreSQL as managed services. The frontend calls FastAPI only through its same-origin authenticated route. Workers use the same DB schema and Redis queue. Put all external services behind TLS/network access controls; never expose `.env` or API service tokens to browser JavaScript.

### Environment variables

Use separate values per development, staging, and production environment. `.env.example` contains names and placeholders only.

| Variable | Consumer | Notes |
|---|---|---|
| `DATABASE_URL` | API, worker | Neon pooled URL for ordinary traffic; `postgresql+psycopg` scheme. |
| `DATABASE_URL_UNPOOLED` | Alembic and session-sensitive tasks | Neon direct URL. Do not use pooled URL for migrations. |
| `DOCKER_DATABASE_URL`, `DOCKER_DATABASE_URL_UNPOOLED` | Compose containers | Container-reachable local Postgres or Neon pooled/direct URLs. |
| `REDIS_URL` | API, worker | Private Redis endpoint; fail-closed model budgets and RQ queue depend on it. |
| `API_SERVICE_TOKEN`, `SESSION_SECRET`, `OWNER_PASSWORD` | API / web | Independent high-entropy secrets, minimum 32 characters for service/session secrets. |
| `OWNER_ID`, `APP_ENV`, `APP_ORIGIN` | API / web | Distinct stable owner; production origin must be HTTPS. |
| `GITHUB_TOKEN` | Worker | Optional fine-grained token for public API throughput/Discussions. |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_INSTALLATION_ID` | Worker/API | Needed for installation API actions and webhook authorization. Store private key as multiline env secret supported by the platform. |
| `GITHUB_WEBHOOK_SECRET` | API | Random webhook secret, at least 32 characters. |
| `GITHUB_PUBLISH_ENABLED` | Worker | Default false. Enable only after validating a least-privilege installation and comment idempotency. |
| `OPENROUTER_API_KEY` | API / worker | Server-side only. Never prefix with `NEXT_PUBLIC_`. |
| `OPENROUTER_MODEL`, `OPENROUTER_VERIFY_MODEL` | Worker / API | Must support strict JSON Schema output. Verification is a separate call, not a truth guarantee. |
| `OPENROUTER_EMBEDDING_MODEL` | Worker | Optional semantic retrieval; lexical fallback remains explicit. |
| `MODEL_CALLS_PER_DAY`, `MODEL_MAX_OUTPUT_TOKENS`, `MODEL_MAX_INPUT_CHARS`, `JOBS_PER_PROJECT_PER_HOUR` | API / worker | Conservative quotas; tune with cost monitoring. |
| `DISCOURSE_ORIGINS` | Worker/API | Comma-separated exact public HTTPS origin allowlist, e.g. `https://discuss.python.org`. |

## Compose

Copy `.env.example` to `.env`, replace placeholders with generated local-only values, and keep `.env` out of Git. Set local host URLs for direct `uv` commands and container host `postgres` URLs for `DOCKER_DATABASE_URL*`. For Neon, set those Docker variables to its pooled/direct URLs instead. Then:

```sh
docker compose --profile local-db up -d postgres redis
uv sync --frozen
uv run alembic upgrade head
docker compose --profile local-db --profile app up --build
```

Compose binds web/API/Postgres/Redis ports to loopback. It restarts API, worker, web, and backing services. Production must use managed Postgres/Redis, platform secret management, durable backups, TLS, and external monitoring rather than this single-host local topology.

## Migration and rollout order

1. Create a Neon development/staging branch; inspect extensions and confirm `vector` is supported. Keep `main`/production separate from development.
2. Configure the pooled app URL and direct migration URL as separate secrets.
3. Deploy the API image once, execute `uv run alembic upgrade head` as a one-shot migration job with the direct URL, and verify `alembic current`.
4. Roll out API, then worker, then frontend. Check `/health`, `/health/database`, `/ready`, worker heartbeat, and a bounded sample job. Roll back app images without running destructive Alembic downgrades.
5. Verify backup/restore and webhook reconciliation in staging before production. No claim of zero downtime is made for these MVP migrations.

## GitHub App setup

Create a GitHub App owned by the organization/account operating Watermelon. Use webhook URL `https://<api-host>/webhooks/github`, content type JSON, and a newly generated webhook secret. Subscribe to `pull_request` (`opened`, `reopened`, `synchronize`), `issues`, `issue_comment`, `pull_request_review`, `pull_request_review_comment`, and relevant discussion/release events only if needed. Grant read access to repository metadata, issues, contents, and pull requests. Grant pull-request issue-comment write only if the operator intentionally enables finding comments. Install on a test public repository first; record app ID, installation ID, and private key in server-side secrets.

Keep `GITHUB_PUBLISH_ENABLED=false` for preview-only deployment. For publication, verify HMAC signature, installation identity, current-head SHA, exact source citations, stable finding identifier and duplicate delivery behavior. GitHub does not reveal deleted historical comments or all edit history. Check results/comments can be written only from the worker after fresh evidence validation.

## Discourse setup

Configure exact public HTTPS origins in `DISCOURSE_ORIGINS`. Use the public topic API and canonical topic URLs; pagination is required. Do not configure a private Discourse API key or scrape private topics. DNS validation rejects private/loopback addresses and redirects are disabled. Some site anti-bot/rate-limit policies may still make a public topic unavailable; failed pages are recorded as partial source failures.

## OpenRouter setup

Use a backend-only OpenRouter key. Select a model exposing the `structured_outputs` capability for the requested JSON schema, set a distinct verification model, and set a conservative daily budget. Redis is required for atomic paid-inference budgets; with Redis down the service intentionally refuses paid calls. Provider cost may be absent from responses, in which case Watermelon stores null rather than an estimate. Verify model/vendor terms, data retention, and regional requirements with the provider before sending source text.

## Operations and security

- Keep secrets in the hosting platform's secret manager; rotate service/session/webhook credentials. `.env.example` must never contain real secrets.
- Restrict Postgres to API/worker/migration networks and Redis to API/worker only. Use Neon IP allowlists where practical.
- Put TLS, ingress request limits, distributed login throttling, and WAF/rate controls in front of Next/API. The app's current owner-login throttle is process-local and is not a distributed production control.
- Alert on `/ready` failures, queue age, retries, partial source imports, provider errors, quota exhaustion, unexpected publication states, DB pool saturation, and stale reconciliation watermarks.
- Back up Neon and practice restoring a branch. Set retention and audit policy for source text, chat history, and provider logs.
- Never trust imported content as instructions or render it as HTML. Treat source content as untrusted, bound request/body sizes, keep auth/project filters on every API route, and keep generated citations resolved by the backend.
