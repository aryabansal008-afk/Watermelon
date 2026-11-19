"""Read-only candidate discovery; saves API metadata, never crawls repositories."""
import json
from pathlib import Path
from backend.connectors import GitHub

client = GitHub()
queries = [
    'repo:encode/httpx is:issue created:<2024-01-01 comments:>8 sort:comments-desc',
    'repo:encode/httpx is:pr is:merged created:<2024-01-01 comments:>5 sort:comments-desc',
]
out = []
for query in queries:
    data = client.get("/search/issues", q=query, per_page=20)
    out.extend({k: x.get(k) for k in ("number", "title", "comments", "html_url", "created_at", "body", "pull_request")}
               for x in data["items"])
Path(".artifacts").mkdir(exist_ok=True)
Path(".artifacts/httpx-candidates.json").write_text(json.dumps(out, indent=2))
for x in out:
    print(x["number"], "PR" if x["pull_request"] else "issue", x["comments"], x["created_at"], x["title"])
client.close()
