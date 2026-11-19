from bs4 import BeautifulSoup
from backend.connectors import discourse_topic
from backend.memory import get_or_create, source_connection, save_message, stamp
from backend.models import Discussion, now


def ingest_topic(db, project, origin, topic_id):
    topic = discourse_topic(origin, topic_id)
    connection = source_connection(db, project, "discourse", origin)
    discussion = get_or_create(db, Discussion,
        {"connection_id": connection.id, "external_id": str(topic_id)},
        project_id=project.id, kind="discourse", title=topic["title"], url=f"{origin}/t/{topic_id}",
        source_created_at=stamp(topic["created_at"]), source_updated_at=stamp(topic.get("last_posted_at")), raw=topic)
    discussion.raw, discussion.title = topic, topic["title"]
    discussion.source_updated_at = stamp(topic.get("last_posted_at"))
    parents = {}
    for post in topic["post_stream"]["posts"]:
        body = post.get("raw") or BeautifulSoup(post["cooked"], "html.parser").get_text("\n")
        version = save_message(db, discussion, post, "post", provider=f"discourse:{origin}", body=body,
            external_id=str(post["id"]), url=f"{origin}/t/{topic_id}/{post['post_number']}",
            author={"id": post["user_id"], "login": post["username"], "html_url": f"{origin}/u/{post['username']}"},
            parent_id=parents.get(post.get("reply_to_post_number")),
            created=post["created_at"], updated=post.get("updated_at") or post["created_at"])
        parents[post["post_number"]] = version.message_id
    connection.status, connection.last_sync = "source_ingested", now()
    connection.cursor = {"topic_id": topic_id, "post_count": len(topic["post_stream"]["posts"])}
    return discussion
