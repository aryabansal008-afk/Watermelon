# Blind Python PEP rejected-alternative benchmark

This is an independent evaluation package, not an application dataset. The FastAPI image copies only `backend/`, `data/`, `migrations/`, and `scripts/`; it does not copy this directory. No application endpoint, retrieval function, or production ingestion job reads the benchmark registry or `answer_keys/`.

## Frozen selection and splits

| Split | PEP | Public discussion input | PEP reference (answer key only) |
|---|---:|---|---|
| development | 703 | [PEP 703 discussion](https://discuss.python.org/t/pep-703-making-the-global-interpreter-lock-optional/22606) | [PEP 703](https://peps.python.org/pep-0703/) |
| development | 723 | [PEP 723 discussion](https://discuss.python.org/t/31151) | [PEP 723](https://peps.python.org/pep-0723/) |
| held-out | 750 | [PEP 750 discussion](https://discuss.python.org/t/pep750-template-strings-new-updates/71594) | [PEP 750](https://peps.python.org/pep-0750/) |
| held-out | 824 | [PEP 824 discussion](https://discuss.python.org/t/pep-824-none-coalescing-operators/109161) | [PEP 824](https://peps.python.org/pep-0824/) |

Each listed PEP has a documented `Rejected Ideas` section. PEP 723's canonical Discourse topic is PEP 722's transition discussion; PEP 723 references it as its discussion thread. The topic URL and source post IDs are retained. Registry metadata is kept out of each model input: the blind input contains only the selected public topic URL, immutable post IDs/URLs, timestamps, authors, post bodies, and hashes. Direct links to `peps.python.org` are redacted in message bodies, so inference has no canonical answer-key link. The original discussion can itself discuss proposals and dispositions; that is intentional evidence, not answer-key text.

PEP 703 and 723 are development data. PEP 750 and 824 are held out at the PEP level. PEP 824 was published in 2026 and is especially unlikely to be in a model's training snapshot, but this cannot be guaranteed. The other PEPs and discussions are public and may be in pretraining. Results measure performance on these frozen snapshots, not uncontaminated generalization. This small purposive set is not representative of all engineering discussions.

## Prepare and run

Use a disposable environment with `uv`, network access to public `discuss.python.org`, a server-side `OPENROUTER_API_KEY`, a selected model with strict structured output, and Redis. Do not run extraction on the held-out set while choosing prompts/models. The extraction process receives only the blind JSON files; the evaluator reads answer keys only after prediction files are frozen.

```sh
uv run python scripts/fetch_pep_benchmark.py
uv run python scripts/run_pep_benchmark.py --split development
# Freeze/tune from development before the held-out run.
uv run python scripts/run_pep_benchmark.py --split held-out
```

Fetch records an input SHA-256 and topic post count. A rerun verifies that any already-frozen input still matches its hash. To freeze changed public source data, bump `version` in `registry.json`, then rerun with `--refresh`; old versioned snapshots remain in place. Inference uses the same two-stage `backend.inference.extract` function as historical ingestion and its normal budget limits. A provider, budget, or Redis failure exits nonzero and creates no successful score.

The evaluator expects a separate adjudication JSON created by two human reviewers, with one entry per PEP:

```json
{
  "peps": {
    "703": {
      "matches": [
        {"prediction_id": "frozen prediction id", "answer_id": "703-concurrent-gc",
         "rationale_correct": true, "citation_supported": true,
         "adjudicator": "reviewer-1 + reviewer-2", "notes": "Why this is a same-scope match"}
      ],
      "citation_judgments": {"frozen prediction id": true}
    }
  }
}
```

Save it outside any model-visible input and run `uv run python scripts/score_pep_benchmark.py --split development --adjudications /secure/path/adjudications.json benchmarks/predictions/703-development-2026-11-19-v2.json benchmarks/predictions/723-development-2026-11-19-v2.json`. Add `--persist` only when the configured DB is the intended evaluation database. The scorer intentionally does not generate semantic matches. A reviewer assigns one-to-one matches against answer IDs, rates rationale correctness and independently judges whether each prediction's discussion citations support it. The tie-break and adjudication rationale must be recorded. Citation-existence/quote checks are deterministic; semantic citation support and semantic equivalence still need human review.

## Matching rubric

Two alternatives are a match only if they pursue the same engineering design or behavior for the same decision scope. Surface wording and examples may differ. A broad family is not a match when it hides a materially different behavior (for example, a method vs a new operator). One prediction and one reference may be matched at most once. A missing or ambiguous reference is unmatched; reviewers must not force a match. Rationale correctness is scored only on matched alternatives and requires the predicted reason to capture the documented causal/compatibility/complexity reason, not merely say “not preferred.” Citation support is judged independently for every predicted alternative: the cited public post must contain evidence for the alternative and, when claimed, its rejection rationale. Unsupported extractions count every prediction without supported evidence, whether or not it matches an answer.

Precision = matched predictions / all predictions; recall = matched references / all references; F1 is their harmonic mean. Rationale correctness = matched alternatives with a correct rationale / matched alternatives. Citation-support correctness = supported predictions / all predictions. Empty prediction sets have precision 0; empty references have recall 0. Per-PEP and aggregate results include counts, all metric denominators, input/output hashes, prompt/model IDs, provider-reported token usage and provider-reported cost when present. Missing cost remains null; it is never estimated or invented.

No benchmark score is checked in as successful. The answer key and adjudication files in this checkout are private evaluation inputs; keep them outside any public release. The application and Docker images must never copy them.
