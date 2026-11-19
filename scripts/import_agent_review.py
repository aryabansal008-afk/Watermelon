"""Import explicitly labelled agent-assisted candidates. Never mark them model-verified."""
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.db import engine
from backend.models import Discussion, Project
from backend.config import settings
from backend.memory import evidence_records, persist_extraction
from backend.schemas import Extraction

packet = json.loads(Path("data/httpx-agent-review.json").read_text())
with Session(engine()) as db:
    project = db.scalar(select(Project).where(Project.repository == "encode/httpx", Project.owner_id == settings().owner_id))
    for entry in packet["candidates"]:
        discussion = db.scalar(select(Discussion).where(Discussion.project_id == project.id,
                                                       Discussion.external_id == str(entry["number"])))
        if not discussion:
            print("Missing discussion:", entry["number"])
            continue
        records = evidence_records(db, discussion.id)
        def resolve(evidence):
            refs = []
            for item in evidence:
                record = next((r for r in records if r["url"] == item["url"] and item["quote"] in r["body"]), None)
                if not record:
                    raise ValueError(f"Exact source excerpt not found for {item['url']}")
                refs.append({"message_version_id": record["message_version_id"], "quote": item["quote"]})
            return refs
        value = {k: v for k, v in entry.items() if k not in ("number", "evidence", "alternatives")}
        value["citations"] = resolve(entry["evidence"])
        value["alternatives"] = [{**{k: v for k, v in alt.items() if k != "evidence"},
                                 "citations": resolve(alt["evidence"])} for alt in entry["alternatives"]]
        extraction = Extraction.model_validate({"decisions": [value], "abstention_reason": ""})
        saved = persist_extraction(db, discussion, extraction, model="agent-assisted / Codex (not OpenRouter)", semantic=False)
        db.commit()
        print("Saved review-required candidate:", entry["number"], saved[0].title, flush=True)
