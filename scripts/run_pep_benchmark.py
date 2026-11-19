"""Run extraction first; only after each prediction file is frozen, invoke the scorer."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "held-out"], required=True)
    args = parser.parse_args()
    registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
    files = []
    for source in registry["sources"]:
        if source["split"] != args.split:
            continue
        version = registry["version"].replace("/", "-")
        input_path = ROOT / "benchmarks/inputs" / f"{source['pep']}-{args.split}-{version}.json"
        if not input_path.exists():
            raise SystemExit(f"Missing frozen input {input_path}; run scripts/fetch_pep_benchmark.py first")
        output_path = ROOT / "benchmarks/predictions" / f"{source['pep']}-{args.split}-{version}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/extract_pep_predictions.py"),
                                     str(input_path), str(output_path)], cwd=ROOT, env=os.environ.copy())
        if completed.returncode:
            raise SystemExit(completed.returncode)
        files.append(str(output_path))
    print("Predictions are frozen. Independent human matching/citation adjudication is required before scoring.")
    print("Prediction files: " + ", ".join(files))


if __name__ == "__main__":
    main()
