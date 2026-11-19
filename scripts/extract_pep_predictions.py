"""Inference-only child process. This module has no answer-key imports or paths."""
import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

from backend.config import settings
from backend.inference import PROMPT_VERSION, extract_with_usage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    blind = json.loads(args.input.read_text())
    records = []
    for item in blind["records"]:
        ident = UUID(item["id"][:32])
        records.append({"message_version_id": ident, "timestamp": item["created_at"], "body": item["body"],
                        "url": item["url"], "author": item["author"]})
    windows = []
    current, chars = [], 0
    for record in records:
        size = len(record["body"])
        if current and (chars + size > 12_000 or len(current) >= 24):
            windows.append(current)
            current, chars = current[-2:], sum(len(r["body"]) for r in current[-2:])
        current.append(record)
        chars += size
    if current:
        windows.append(current)
    decisions, usage = [], {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": None}
    for window in windows:
        result, used = extract_with_usage(window)
        decisions.extend(result.decisions)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[key] += used[key]
        if used["cost_usd"] is not None:
            usage["cost_usd"] = (usage["cost_usd"] or 0) + used["cost_usd"]
    predictions = []
    seen = set()
    for decision in decisions:
        for index, alternative in enumerate(decision.alternatives):
            normalized = " ".join(alternative.approach.lower().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            predictions.append({"id": hashlib.sha256(f"{decision.key}:{index}:{alternative.approach}".encode()).hexdigest()[:20],
                                "alternative": alternative.approach, "rationale": alternative.rationale,
                                "status": alternative.status,
                                "citations": [{"message_version_id": str(c.message_version_id), "quote": c.quote}
                                              for c in alternative.citations]})
    output = {"input_hash": blind["sha256"], "prompt_version": PROMPT_VERSION,
              "predictions": predictions, "abstention_reason": "No supported alternatives found" if not predictions else "",
              "chunks": len(windows),
              "token_usage": usage, "provider_cost_usd": usage["cost_usd"],
              "model": settings().openrouter_model}
    output["output_hash"] = hashlib.sha256(json.dumps(output, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"predictions={len(predictions)} input_hash={output['input_hash']} output_hash={output['output_hash']}")


if __name__ == "__main__":
    main()
