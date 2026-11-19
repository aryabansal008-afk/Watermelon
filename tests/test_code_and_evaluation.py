import pytest
from backend.code_awareness import symbols, git_changes
from backend.evaluation import Match, score, canonical_hash, validate_blind_manifest
from backend import inference
from backend.schemas import SpanDetection, Extraction, ExtractionBatch, DecisionSpan
from uuid import UUID, uuid4


def test_python_symbols_are_parsed_without_executing():
    source = b"import os\nos.system('never execute')\nclass Client:\n    def request(self):\n        pass\n"
    assert [(s["name"], s["line_start"]) for s in symbols(source, "python")] == [("Client", 3), ("request", 4)]


def test_typescript_symbols():
    assert [s["name"] for s in symbols(b"export interface Options { url: string }; export function send() {}", "typescript")] == ["Options", "send"]


def test_git_rejects_option_injection(tmp_path):
    with pytest.raises(ValueError):
        git_changes(tmp_path, "--output=/tmp/unsafe", "a" * 40)


def test_evaluation_counts_unmatched_predictions():
    match = Match(prediction_id="p1", answer_id="a1", rationale_correct=True, citation_supported=True,
                  adjudicator="reviewer-1", notes="Same rejected approach and correctly grounded reason")
    result = score(["p1", "p2"], ["a1", "a2", "a3"], [match], {"p1": True, "p2": False})
    assert result["precision"] == .5
    assert result["recall"] == pytest.approx(1 / 3)
    assert result["f1"] == pytest.approx(.4)
    assert result["citation_support_accuracy"] == .5


def test_benchmark_cannot_double_count():
    match = Match(prediction_id="p1", answer_id="a1", rationale_correct=True, citation_supported=True,
                  adjudicator="reviewer", notes="Supported match")
    with pytest.raises(ValueError, match="one-to-one"):
        score(["p1"], ["a1"], [match, match], {"p1": True})


def test_benchmark_requires_all_citation_judgments():
    with pytest.raises(ValueError, match="Every prediction"):
        score(["p1"], [], [], {})


def test_blind_manifest_rejects_key_leakage_and_tampering():
    manifest = {"version": "test", "split": "test", "source": "https://discuss.python.org/t/123",
        "records": [{"id": "a", "external_id": "1", "post_number": 1, "url": "https://discuss.python.org/t/123/1",
        "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z", "author": "user",
        "body": "A synthetic discussion fixture"}]}
    manifest["sha256"] = canonical_hash(manifest)
    assert validate_blind_manifest(manifest) == manifest
    with pytest.raises(ValueError, match="only model-visible"):
        validate_blind_manifest({**manifest, "answer_keys": []})
    contaminated = {**manifest, "records": [{**manifest["records"][0], "answer": "leaked"}]}
    contaminated["sha256"] = canonical_hash({key: value for key, value in contaminated.items() if key != "sha256"})
    with pytest.raises(ValueError, match="may not contain"):
        validate_blind_manifest(contaminated)


def test_extraction_uses_two_stages_and_preserves_chronology(monkeypatch):
    first, second = uuid4(), uuid4()
    messages = [
        {"message_version_id": str(second), "timestamp": "2024-02-01T00:00:00+00:00", "body": "Chosen.", "url": "u"},
        {"message_version_id": str(first), "timestamp": "2024-01-01T00:00:00+00:00", "body": "Proposal.", "url": "u"},
    ]
    calls = []
    def structured(schema, system, payload, model=None):
        calls.append(schema)
        if schema is SpanDetection:
            return SpanDetection(spans=[DecisionSpan(message_version_ids=[first, second], reason="proposal and explicit choice")], abstention_reason="")
        assert [r["message_version_id"] for r in payload["source_records"]] == [str(first), str(second)]
        return ExtractionBatch(decisions=[], abstention_reason="No supported decision")
    monkeypatch.setattr(inference, "structured", structured)
    result = inference.extract(messages)
    assert calls == [SpanDetection, ExtractionBatch]
    assert result.decisions == []
    assert result.abstention_reason == "No supported decision"


def test_oversized_discussion_is_split_into_overlapping_bounded_windows(monkeypatch):
    ids = [uuid4() for _ in range(10)]
    messages = [{"message_version_id": str(message_id), "timestamp": f"2024-01-{i + 1:02d}T00:00:00+00:00",
                 "body": f"Message {i}. " + ("context " * 55), "url": "https://example.test/thread"}
                for i, message_id in enumerate(ids)]
    monkeypatch.setattr(inference.settings(), "model_max_input_chars", 6000)
    spans_seen = []

    def structured(schema, system, payload, model=None):
        if schema is SpanDetection:
            records = payload["source_records"]
            spans_seen.append([UUID(row["message_version_id"]) for row in records])
            return SpanDetection(spans=[DecisionSpan(
                message_version_ids=[UUID(row["message_version_id"]) for row in records],
                reason="chronological window")], abstention_reason="")
        return ExtractionBatch(decisions=[], abstention_reason="No supported decision")

    monkeypatch.setattr(inference, "structured", structured)
    result = inference.extract(messages)

    assert len(spans_seen) > 1
    assert set().union(*map(set, spans_seen)) == set(ids)
    assert any(len(a & b) >= 1 for a, b in zip(map(set, spans_seen), map(set, spans_seen[1:])))
    assert result.decisions == []
    assert result.abstention_reason == "No supported decision"


def test_positive_extraction_is_structured_and_cited(monkeypatch):
    source_id = uuid4()
    claim = {"key": "keep-sync-api", "title": "Keep the synchronous API",
        "claim": "The project retained synchronous calls for existing callers.", "scope": "Client API",
        "status": "accepted", "citations": [{"message_version_id": source_id,
            "quote": "We will keep the synchronous API for existing callers."}], "alternatives": [],
        "open_questions": [], "possible_supersession": []}
    def structured(schema, system, payload, model=None):
        if schema is SpanDetection:
            return SpanDetection(spans=[DecisionSpan(message_version_ids=[source_id], reason="explicit maintainer decision")], abstention_reason="")
        return Extraction(decisions=[claim], abstention_reason="")
    monkeypatch.setattr(inference, "structured", structured)
    result = inference.extract([{"message_version_id": str(source_id), "timestamp": "2024-01-01T00:00:00+00:00",
                                 "body": "We will keep the synchronous API for existing callers."}])
    assert result.decisions[0].status == "accepted"
    assert result.decisions[0].citations[0].message_version_id == source_id


def test_span_detector_abstention_never_calls_decision_extractor(monkeypatch):
    calls = []
    def structured(schema, system, payload, model=None):
        calls.append(schema)
        return SpanDetection(spans=[], abstention_reason="No decision-bearing evidence")
    monkeypatch.setattr(inference, "structured", structured)
    result = inference.extract([{"message_version_id": str(uuid4()), "timestamp": "2024-01-01", "body": "I like this."}])
    assert calls == [SpanDetection]
    assert result.decisions == []
