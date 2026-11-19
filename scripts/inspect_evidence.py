"""Export a bounded, local review packet from stored public records. Contains no credentials."""
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.db import engine
from backend.models import Discussion
from backend.memory import evidence_records

with Session(engine()) as db:
    discussions = db.scalars(select(Discussion).order_by(Discussion.source_created_at)).all()
    packet = []
    for discussion in discussions:
        records = evidence_records(db, discussion.id)
        packet.append({"number": discussion.external_id, "id": str(discussion.id), "title": discussion.title,
                       "url": discussion.url, "records": records})
        print(f"\n=== #{discussion.external_id}: {discussion.title} ===")
        maintainer = [r for r in records if r["author_association"] in ("OWNER", "MEMBER", "COLLABORATOR")
                      and r["kind"] != "timeline"]
        for record in maintainer[:5]:
            print(record["message_version_id"], record["author"], record["url"])
            print(record["body"][:1600])
    Path(".artifacts").mkdir(exist_ok=True)
    Path(".artifacts/httpx-review-packet.json").write_text(json.dumps(packet, indent=2))
