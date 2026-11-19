"""Evaluation-only scorer. This is the sole production script allowed to read answer_keys."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.evaluation import score

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "held-out"], required=True)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--persist", action="store_true", help="Persist a real adjudicated score in the configured application DB")
    parser.add_argument("predictions", nargs="+", type=Path)
    args = parser.parse_args()
    registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
    keys = json.loads((ROOT / "benchmarks/answer_keys/references.json").read_text())
    key_by_pep = keys["peps"]
    per_pep = {}
    source_count = 0
    aggregate_records = []
    for path in args.predictions:
        pep = path.name.split("-")[0]
        entry = next((r for r in registry["sources"] if str(r["pep"]) == pep and r["split"] == args.split), None)
        if not entry:
            raise SystemExit(f"Prediction file {path.name} is not in requested split")
        prediction = json.loads(path.read_text())
        version = registry["version"].replace("/", "-")
        blind_path = ROOT / "benchmarks/inputs" / f"{pep}-{args.split}-{version}.json"
        blind = json.loads(blind_path.read_text())
        if prediction["input_hash"] != blind["sha256"]:
            raise SystemExit(f"Input hash mismatch for PEP {pep}")
        references = key_by_pep[pep]
        predictions = prediction["predictions"]
        if args.adjudications is None or not args.adjudications.exists():
            raise SystemExit("No human adjudications supplied. Refusing to create or publish benchmark scores.")
        adjudication = json.loads(args.adjudications.read_text())["peps"][pep]
        matches = adjudication["matches"]
        citation_judgments = adjudication["citation_judgments"]
        record_map = {r["id"]: r for r in blind["records"]}
        for item in predictions:
            for citation in item["citations"]:
                citation_id = citation["message_version_id"].replace("-", "")
                source = next((r for r in record_map.values() if r["id"][:32] == citation_id), None)
                if source is None or citation["quote"] not in source["body"]:
                    raise SystemExit(f"Citation ID or exact quote does not resolve in blind input for prediction {item['id']}")
        metrics = score([p["id"] for p in predictions], [a["id"] for a in references], matches, citation_judgments)
        metrics["unsupported_extractions"] = sum(not citation_judgments[p["id"]] for p in predictions)
        metrics["rationale_correct_count"] = sum(m["rationale_correct"] for m in matches)
        metrics["citation_supported_count"] = sum(citation_judgments.values())
        metrics["input_hash"] = blind["sha256"]
        metrics["output_hash"] = prediction["output_hash"]
        metrics["predicted"] = len(predictions)
        metrics["reference_count"] = len(references)
        metrics["token_usage"] = prediction.get("token_usage")
        metrics["provider_cost_usd"] = prediction.get("provider_cost_usd")
        per_pep[pep] = metrics
        source_count += len(predictions)
        aggregate_records.append((predictions, references, matches, citation_judgments))
    ids, answers, matches, citation_judgments = [], [], [], {}
    for index, (preds, refs, match_rows, cites) in enumerate(aggregate_records):
        prefix = f"s{index}:"
        ids.extend(prefix + p["id"] for p in preds)
        answers.extend(prefix + a["id"] for a in refs)
        matches.extend({**m, "prediction_id": prefix + m["prediction_id"], "answer_id": prefix + m["answer_id"]} for m in match_rows)
        citation_judgments.update({prefix + k: v for k, v in cites.items()})
    aggregate = score(ids, answers, matches, citation_judgments)
    aggregate["unsupported_extractions"] = sum(not value for value in citation_judgments.values())
    aggregate["predicted"] = source_count
    aggregate["reference_count"] = len(answers)
    manifest_hash = hashlib.sha256("".join(per_pep[k]["input_hash"] for k in sorted(per_pep)).encode()).hexdigest()
    result = {"split": args.split, "dataset_version": registry["version"], "input_manifest_hash": manifest_hash,
              "rubric_version": keys["rubric_version"], "status": "human_adjudicated", "aggregate": aggregate,
              "per_pep": per_pep}
    output = ROOT / "benchmarks/results" / f"{args.split}-{manifest_hash[:12]}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.persist:
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import EvaluationDataset, EvaluationRun
        answer_key_hash = hashlib.sha256(json.dumps(
            {pep: key_by_pep[pep] for pep in sorted(per_pep)}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        model_names = sorted({json.loads(path.read_text())["model"] for path in args.predictions})
        if len(model_names) != 1:
            raise SystemExit("A persisted benchmark run must use one model ID across all inputs")
        with Session(engine()) as db:
            dataset = db.scalar(select(EvaluationDataset).where(EvaluationDataset.name == registry["name"],
                EvaluationDataset.version == f"{registry['version']}-{args.split}"))
            if not dataset:
                dataset = EvaluationDataset(name=registry["name"], version=f"{registry['version']}-{args.split}",
                    input_manifest={"peps": sorted(per_pep), "split": args.split, "input_hashes":
                                    {pep: data["input_hash"] for pep, data in per_pep.items()}},
                    input_hash=manifest_hash, answer_key_hash=answer_key_hash, split=args.split)
                db.add(dataset)
                db.flush()
            output_hash = hashlib.sha256("".join(per_pep[k]["output_hash"] for k in sorted(per_pep)).encode()).hexdigest()
            prior = db.scalar(select(EvaluationRun).where(EvaluationRun.dataset_id == dataset.id,
                EvaluationRun.input_hash == manifest_hash, EvaluationRun.output_hash == output_hash))
            if not prior:
                db.add(EvaluationRun(dataset_id=dataset.id, model=model_names[0], prompt_version="evidence-v1",
                    input_hash=manifest_hash, output_hash=output_hash, status="human_adjudicated",
                    configuration={"rubric_version": keys["rubric_version"], "per_pep": per_pep},
                    metrics=aggregate))
            db.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
