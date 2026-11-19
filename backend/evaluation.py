"""Offline evaluator. Answer keys never enter the extraction function or its filesystem inputs."""
import hashlib
import json
from pydantic import Field
from backend.schemas import StrictModel


class Match(StrictModel):
    prediction_id: str
    answer_id: str
    rationale_correct: bool
    citation_supported: bool
    adjudicator: str = Field(min_length=3)
    notes: str = Field(min_length=3)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_blind_manifest(manifest):
    if set(manifest) != {"version", "split", "source", "records", "sha256"}:
        raise ValueError("Blind input manifest must contain only model-visible source records and integrity metadata")
    if not manifest.get("records"):
        raise ValueError("Blind dataset needs sources")
    from urllib.parse import urlsplit
    url = urlsplit(manifest["source"])
    if url.scheme != "https" or url.hostname != "discuss.python.org" or not url.path.startswith("/t/"):
        raise ValueError("Blind extraction accepts only frozen discuss.python.org topic snapshots")
    required = {"id", "external_id", "post_number", "url", "created_at", "updated_at", "author", "body"}
    if any(set(record) != required for record in manifest["records"]):
        raise ValueError("Blind records may not contain PEP metadata, references, labels, or answer-key fields")
    ids, external_ids = set(), set()
    for record in manifest["records"]:
        post_url = urlsplit(record["url"])
        if post_url.scheme != "https" or post_url.hostname != "discuss.python.org" or not post_url.path.startswith(url.path):
            raise ValueError("Every frozen citation URL must resolve within the selected public Discourse topic")
        if record["id"] in ids or record["external_id"] in external_ids:
            raise ValueError("Blind source record identifiers must be unique")
        ids.add(record["id"])
        external_ids.add(record["external_id"])
    if "peps.python.org" in json.dumps(manifest).lower():
        raise ValueError("Blind source metadata must not link to PEP reference documents")
    payload = {key: value for key, value in manifest.items() if key != "sha256"}
    if canonical_hash(payload) != manifest["sha256"]:
        raise ValueError("Blind input hash mismatch")
    return manifest


def score(prediction_ids, answer_ids, matches: list[Match], citation_judgments: dict[str, bool]):
    predictions, answers = set(prediction_ids), set(answer_ids)
    if len(predictions) != len(prediction_ids) or len(answers) != len(answer_ids):
        raise ValueError("Prediction and answer IDs must be unique")
    if set(citation_judgments) != predictions:
        raise ValueError("Every prediction needs an independent citation-support judgment")
    matched_predictions, matched_answers = set(), set()
    for match in matches:
        if match.prediction_id not in predictions or match.answer_id not in answers:
            raise ValueError("Unknown adjudication ID")
        if match.prediction_id in matched_predictions or match.answer_id in matched_answers:
            raise ValueError("Matches must be one-to-one")
        if match.citation_supported != citation_judgments[match.prediction_id]:
            raise ValueError("Inconsistent citation-support adjudication")
        matched_predictions.add(match.prediction_id)
        matched_answers.add(match.answer_id)
    tp = len(matches)
    precision = tp / len(predictions) if predictions else 0.0
    recall = tp / len(answers) if answers else 0.0
    return {"precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "rationale_correctness": sum(m.rationale_correct for m in matches) / tp if tp else 0.0,
            "citation_support_accuracy": sum(citation_judgments.values()) / len(predictions) if predictions else 0.0,
            "true_positives": tp, "false_positives": len(predictions) - tp, "false_negatives": len(answers) - tp}
