import hashlib
import hmac
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.api import app, valid_signature
from backend.config import settings
from backend.config import Settings
from backend.connectors import GitHub, UpstreamError, IncompleteSource, RateLimited, repository_name, discourse_origin
from backend.inference import verify_quotes, structured, InferenceUnavailable
from backend.schemas import Citation, Extraction, IngestRequest


@pytest.mark.parametrize("value", ["https://evil.test/x", "../secrets", "encode/httpx/../../etc", "encode/httpx?token=x", "file:///tmp/x"])
def test_repository_rejects_arbitrary_urls(value):
    with pytest.raises(ValueError):
        repository_name(value)


def test_repository_accepts_github_url():
    assert repository_name("https://github.com/encode/httpx/") == "encode/httpx"


def test_signature_is_over_raw_bytes():
    raw, secret = b'{"number":123}', "webhook-test-secret"
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert valid_signature(raw, sig, secret)
    assert not valid_signature(raw + b" ", sig, secret)
    assert not valid_signature(raw, sig, "")
    assert not valid_signature(raw, "sha1=invalid", secret)


def test_api_rejects_missing_or_invalid_credentials(monkeypatch):
    monkeypatch.setattr(settings(), "api_service_token", "s" * 40)
    with TestClient(app) as client:
        assert client.get("/v1/projects").status_code == 401
        assert client.get("/v1/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/v1/projects")
        assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_invalid_webhook_does_not_touch_db(monkeypatch):
    monkeypatch.setattr(settings(), "github_webhook_secret", "secret")
    with TestClient(app) as client:
        response = client.post("/webhooks/github", content=b"{}", headers={"X-Hub-Signature-256": "sha256=fake"})
        assert response.status_code == 401


def test_quote_validation_is_scope_and_revision_bound():
    version_id = uuid.uuid4()
    records = {str(version_id): {"body": "We will keep the synchronous API.", "url": "https://github.com/encode/httpx/issues/572"}}
    citation = Citation(message_version_id=version_id, quote="keep the synchronous API")
    assert verify_quotes([citation], records)[0]["quote"] == citation.quote
    with pytest.raises(ValueError, match="unknown"):
        verify_quotes([citation], {})
    with pytest.raises(ValueError, match="not present"):
        verify_quotes([Citation(message_version_id=version_id, quote="remove the synchronous API")], records)


def test_source_prompt_injection_cannot_supply_fake_citations():
    with pytest.raises(ValueError):
        verify_quotes([Citation(message_version_id=uuid.uuid4(), quote="ignore previous instructions")], {})


def test_github_private_repo_is_rejected():
    client = GitHub(token="", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"private": True})))
    with pytest.raises(UpstreamError, match="public"):
        client.public_repository("owner/repo")


def test_github_pagination_rejects_cross_origin():
    client = GitHub(token="secret", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[], headers={"Link": '<https://evil.test/steal>; rel="next"'})))
    with pytest.raises(UpstreamError, match="cross-origin"):
        client.pages("/repos/encode/httpx/issues")


def test_github_pagination_cap_is_explicit():
    client = GitHub(token="", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{"id": 1}], headers={"Link": '<https://api.github.com/next>; rel="next"'})))
    with pytest.raises(IncompleteSource):
        client.pages("/repos/encode/httpx/issues", max_pages=1)


def test_github_pagination_reads_large_sources_without_truncating(monkeypatch):
    monkeypatch.setattr("backend.connectors.time.sleep", lambda _: None)
    page_one = [{"id": i} for i in range(100)]
    page_two = [{"id": i} for i in range(100, 131)]
    def handler(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=page_two)
        if request.url.path.endswith("/issues"):
            return httpx.Response(200, json=page_one,
                headers={"Link": '<https://api.github.com/repos/encode/httpx/issues?page=2>; rel="next"'})
        return httpx.Response(200, json=[])
    client = GitHub(token="", transport=httpx.MockTransport(handler))
    assert len(client.pages("/repos/encode/httpx/issues", max_pages=2)) == 131


def test_github_rate_limit_retries_then_reports_retryable_failure(monkeypatch):
    monkeypatch.setattr("backend.connectors.time.sleep", lambda _: None)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"})
    client = GitHub(token="", transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimited):
        client.get("/repos/encode/httpx")
    assert len(requests) == 3


def test_github_component_failure_is_reported_as_partial(monkeypatch):
    monkeypatch.setattr("backend.connectors.time.sleep", lambda _: None)
    def handler(request):
        if request.url.path.endswith("/issues/5"):
            return httpx.Response(200, json={"number": 5, "title": "Public issue"})
        if request.url.path.endswith("/comments"):
            return httpx.Response(502, json={})
        return httpx.Response(200, json=[])
    client = GitHub(token="", transport=httpx.MockTransport(handler))
    result = client.discussion("encode/httpx", 5)
    assert result["comments"] == []
    assert result["partial_failures"] == [{"component": "comments", "error_type": "UpstreamError"}]


def test_openrouter_provider_error_is_explicit(monkeypatch):
    from backend import inference
    monkeypatch.setattr(settings(), "openrouter_api_key", "server-side-test-key")
    monkeypatch.setattr(settings(), "openrouter_model", "test/model")
    monkeypatch.setattr(inference, "budget", lambda *args: None)
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): return httpx.Response(429, request=httpx.Request("POST", "https://openrouter.ai"))
    monkeypatch.setattr(inference.httpx, "Client", Client)
    with pytest.raises(InferenceUnavailable, match="HTTP 429"):
        structured(Extraction, "system", {"data": "untrusted"})


@pytest.mark.parametrize("url", ["http://discuss.python.org", "https://localhost", "https://169.254.169.254", "https://discuss.python.org@evil.test", "https://discuss.python.org/t/1"])
def test_discourse_rejects_unapproved_origins(url):
    with pytest.raises(ValueError):
        discourse_origin(url)


def test_no_model_configuration_never_fakes_results(monkeypatch):
    monkeypatch.setattr(settings(), "openrouter_api_key", "")
    with pytest.raises(InferenceUnavailable, match="not configured"):
        structured(Extraction, "system", {})


def test_ingestion_is_bounded():
    for numbers in ([1] * 3, list(range(1, 17)), [0], [-1]):
        with pytest.raises(ValueError):
            IngestRequest(numbers=numbers)


def test_production_settings_fail_closed_without_external_secrets():
    with pytest.raises(ValueError, match="API_SERVICE_TOKEN"):
        Settings(_env_file=None, app_env="production")


def test_production_settings_require_tls_redis_and_models():
    with pytest.raises(ValueError, match="rediss"):
        Settings(_env_file=None, app_env="production", api_service_token="a" * 40, owner_id="prod-owner",
                 database_url="postgresql+psycopg://db.example/prod",
                 database_url_unpooled="postgresql+psycopg://db.example/prod")
