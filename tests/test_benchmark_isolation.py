import json
from pathlib import Path
import httpx

from scripts.fetch_pep_benchmark import get_retry

ROOT = Path(__file__).parents[1]


def test_benchmark_splits_peps_and_keeps_answer_keys_out_of_runtime_package():
    registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
    assert {row["split"] for row in registry["sources"]} == {"development", "held-out"}
    assert len({row["pep"] for row in registry["sources"]}) == 4
    dockerfile = (ROOT / "Dockerfile.backend").read_text()
    assert "COPY benchmarks" not in dockerfile
    assert "COPY scripts ./scripts" in dockerfile
    extraction = (ROOT / "scripts/extract_pep_predictions.py").read_text()
    assert "answer_keys" not in extraction
    assert "references.json" not in extraction


def test_benchmark_reference_set_covers_each_registered_pep():
    registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
    references = json.loads((ROOT / "benchmarks/answer_keys/references.json").read_text())
    assert {str(row["pep"]) for row in registry["sources"]} == set(references["peps"])
    assert all(len(items) >= 2 for items in references["peps"].values())
    assert all(item["reference"].startswith("https://peps.python.org/pep-")
               for rows in references["peps"].values() for item in rows)


def test_public_topic_fetcher_retries_rate_limits(monkeypatch):
    monkeypatch.setattr("scripts.fetch_pep_benchmark.time.sleep", lambda _: None)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"}) if len(calls) == 1 else httpx.Response(200, json={"ok": True})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert get_retry(client, "https://discuss.python.org/t/1.json").json() == {"ok": True}
    assert len(calls) == 2
