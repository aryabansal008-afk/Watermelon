from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Contributor, EvidenceReference, Message, MessageVersion


def citations_for_version(db: Session, version_id):
    rows = db.execute(select(EvidenceReference, MessageVersion, Message, Contributor)
        .join(MessageVersion, MessageVersion.id == EvidenceReference.message_version_id)
        .join(Message, Message.id == MessageVersion.message_id)
        .outerjoin(Contributor, Contributor.id == Message.contributor_id)
        .where(EvidenceReference.version_id == version_id)).all()
    return [{**{c.name: getattr(ref, c.name) for c in ref.__table__.columns},
             "url": message.url, "author": author.handle if author else "unknown",
             "body": version.body, "source_updated_at": version.source_updated_at,
             "content_hash": version.content_hash}
            for ref, version, message, author in rows]
