# Verification status

Last checked: 2026-11-19 (local development workspace). A passing unit or mocked integration test does not prove a live external installation works.

## Feature verification matrix

| Capability | Status | Evidence / remaining work |
|---|---|---|
| FastAPI routes, typed schemas, project authorization, errors | Implemented and tested | Unit and PostgreSQL integration tests. Owner browser run navigated routes; one live database-backed view showed an explicit operation error. |
| Neon schema, migrations, JSONB, FTS, vector, constraints | Implemented and tested | Migrations and PostgreSQL integration tests ran against development/disposable `_test` databases; production data was not changed. |
| GitHub REST/GraphQL ingestion, pagination, dedupe, partial state | Implemented but unverified | Mocked HTTP and persistence tests; no live GitHub App installation/token or large-source stress run. |
| Public Discourse ingestion | Implemented but unverified | Fetcher and public topic pagination exercised against benchmark discussions; application connector ingestion and incremental reconciliation were not verified end to end. |
| Historical extraction, evidence validation, abstention, versioning | Implemented but unverified | Mocked extraction tests. No live OpenRouter model extraction was verified. |
| Hybrid retrieval, project scope, supersession filtering | Implemented and tested | PostgreSQL tests cover relevant/irrelevant and superseded paths; live embedding provider remains unverified. |
| PR Intelligence finding selection, current SHA, duplicate publication logic | Implemented but unverified | Mocked GitHub/App/provider paths. No live App installation, publication, or finding was verified. Browser view displayed a database error. |
| Alternative Explorer | Implemented but unverified | Memory-backed API/UI and unvalidated labeling exist; live OpenRouter recommendation generation was not verified. |
| Ask Watermelon grounded history answers | Implemented but unverified | PostgreSQL citation/abstention/session tests. Browser screenshot is a product-information answer, not a live historical answer. |
| Blind PEP benchmark | Partially implemented | Four frozen public topic snapshots, split registry, isolated reference key, production extractor runner, human adjudication rubric and scorer exist. No predictions, adjudications or measured score exist. |
| Docker Compose local topology and migrations | Implemented but unverified | Compose configuration validated with dummy local values; services were not started as a stack. |
| Production auth/rate hardening | Partially implemented | Production configuration checks and job/project limits exist; login throttling is process-local and production ingress/shared rate limiting remains necessary. |
| Complete journey from project setup through real PR and benchmark | Not implemented as a verified demonstration | Some browser routes and independent dataset fetch were exercised, but live queue, provider, GitHub App, application Discourse ingestion and complete source-to-answer journey were not available. |
| Mobile navigation and GSAP reduced-motion lifecycle | Implemented but unverified | Landing/mobile browser checks passed; exhaustive keyboard, reduced-motion and repeated mount/unmount audit was not run. |

## Test results

- `UV_CACHE_DIR=/tmp/watermelon-uv-cache uv run pytest -q`: **40 passed, 19 skipped**, one Starlette/httpx deprecation warning.
- `TEST_DATABASE_NAME=watermelon_test uv run python scripts/run_pg_integration.py`: **59 passed**, one deprecation warning, against a disposable `_test` database.
- `npm run api:types && npm run typecheck`: passed.
- `npm run build` (Webpack production build): passed.
- `docker compose --profile local-db --profile app config --quiet`: passed with dummy local environment values. No services were started.
- `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npm run test:e2e`: **3 passed**. Landing, mobile landing, auth behavior, and workspace route navigation were exercised. The PR Intelligence request hit an observed database operation failure and rendered its retry/error state; this is not a successful PR data test. The Ask Watermelon screenshot demonstrates the product FAQ response only.
- PEP snapshot fetch: all four configured public topics fetched with pagination and hashed; 130 posts (PEP 703), 141 (PEP 723), 181 (PEP 750), and 91 (PEP 824). Snapshot generation is not a model evaluation.

## Benchmark status

There are **no measured benchmark metrics**. No blind model predictions or independent human adjudications were produced, so precision, recall, F1, rationale correctness, citation-support correctness, unsupported extraction count, token usage and cost are not reported. PEP 703/723 are development sources; PEP 750/824 are the held-out sources. Model pretraining exposure may exist for all selected material and cannot be ruled out. See [benchmark methodology](../benchmarks/README.md).

## Known operational limits

- Redis/RQ worker processing was unavailable in this verification environment.
- No live GitHub App ID/private key/installation/webhook secret was configured, so callbacks and publication are unverified.
- No live OpenRouter completion was verified; a configured key is not proof of provider success.
- A browser database-backed request returned an operation failure; the full project-to-PR-to-chat journey is not verified.
- Application ingestion of configured Discourse topics was not exercised end to end. The benchmark fetcher independently accessed only public Python Discourse topics.
- Login throttling is per process. Use shared ingress or distributed rate limiting for multi-instance production.
- Large-source, provider interruption, stale-symbol, malicious-content, reduced-motion lifecycle and full mobile workspace stress tests remain outstanding.
