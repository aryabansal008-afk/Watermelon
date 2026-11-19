"""Bounded public-source clients. Imported source content is always untrusted data."""
import hashlib
import ipaddress
import re
import socket
import time
from urllib.parse import urlsplit, quote
import httpx
from backend.config import settings


class UpstreamError(Exception):
    pass


class RateLimited(UpstreamError):
    pass


class IncompleteSource(UpstreamError):
    pass


def repository_name(value: str) -> str:
    value = value.removeprefix("https://github.com/").removesuffix("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError("Use a public GitHub owner/repository, without a branch or query.")
    return value


class GitHub:
    origin = "https://api.github.com"

    def __init__(self, token: str | None = None, transport=None):
        token = settings().github_token if token is None else token
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "Watermelon/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=30, follow_redirects=False, transport=transport)

    def close(self):
        self.client.close()

    def request(self, path, method="GET", **kwargs):
        url = path if path.startswith("https://") else self.origin + path
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise UpstreamError("Rejected cross-origin GitHub URL")
        for attempt in range(3):
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise UpstreamError("GitHub network request failed after three attempts") from exc
            if response.status_code in (403, 429):
                retry_after = response.headers.get("retry-after")
                reset = response.headers.get("x-ratelimit-reset")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else max(1, int(reset) - int(time.time())) if response.headers.get("x-ratelimit-remaining") == "0" and reset and reset.isdigit() else 60 * (2 ** attempt)
                if attempt < 2:
                    time.sleep(min(delay, 300))
                    continue
                raise RateLimited(f"GitHub rate limited or denied access; retry after approximately {delay}s.")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            if response.status_code >= 300:
                raise UpstreamError(f"GitHub returned HTTP {response.status_code}")
            return response
        raise UpstreamError("GitHub retries exhausted")

    def get(self, path, **params):
        return self.request(path, params=params).json()

    def pages(self, path, max_pages=10, **params):
        result = []
        url = path
        for page in range(max_pages):
            response = self.request(url, params={"per_page": 100, **params} if page == 0 else None)
            data = response.json()
            if not isinstance(data, list):
                raise UpstreamError("Expected paginated list")
            result.extend(data)
            url = response.links.get("next", {}).get("url")
            if not url:
                return result
        raise IncompleteSource("Pagination cap reached; discussion was not silently truncated.")

    def public_repository(self, repository):
        repository = repository_name(repository)
        meta = self.get(f"/repos/{repository}")
        if meta.get("private") is not False or meta.get("visibility", "public") != "public":
            raise UpstreamError("Only public repositories are supported")
        return meta

    def file_content(self, repository: str, path: str, ref: str, max_bytes: int = 1_000_000):
        if path.startswith("/") or ".." in path.split("/") or not re.fullmatch(r"[0-9a-f]{40,64}", ref):
            raise ValueError("Unsafe repository path or commit reference")
        data = self.get(f"/repos/{repository}/contents/{quote(path, safe='/')}", ref=ref)
        if data.get("encoding") != "base64" or data.get("size", max_bytes + 1) > max_bytes:
            raise IncompleteSource("File is unsupported or exceeds the symbol indexing size limit")
        import base64
        source = base64.b64decode(data.get("content", ""), validate=False)
        if len(source) > max_bytes:
            raise IncompleteSource("File content exceeds the symbol indexing size limit")
        return source

    def discussion(self, repository: str, number: int, updated_since: str | None = None):
        root = f"/repos/{repository}"
        issue = self.get(f"{root}/issues/{number}")
        failures = []
        def fetch(name, path, **kwargs):
            try:
                return self.pages(path, **kwargs)
            except RateLimited:
                raise
            except (UpstreamError, httpx.HTTPError, ValueError) as exc:
                failures.append({"component": name, "error_type": type(exc).__name__})
                return []
        data = {"issue": issue, "comments": fetch("comments", f"{root}/issues/{number}/comments"),
                "timeline": fetch("timeline", f"{root}/issues/{number}/timeline")}
        if "pull_request" in issue:
            data.update({"pr": self.get(f"{root}/pulls/{number}"),
                         "reviews": fetch("reviews", f"{root}/pulls/{number}/reviews"),
                         "review_comments": fetch("review_comments", f"{root}/pulls/{number}/comments"),
                         "commits": fetch("commits", f"{root}/pulls/{number}/commits"),
                         "files": fetch("files", f"{root}/pulls/{number}/files", max_pages=30)})
            if data["pr"].get("changed_files", len(data["files"])) > len(data["files"]):
                failures.append({"component": "files", "error_type": "IncompleteSource"})
        data["partial_failures"] = failures
        data["updated_since"] = updated_since
        return data

    def graphql_discussion(self, repository: str, number: int):
        """GraphQL comment and reply cursors are paginated independently."""
        owner, name = repository_name(repository).split("/")
        query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String){
          repository(owner:$owner,name:$name){isPrivate discussion(number:$number){id number title url body createdAt updatedAt
          author{login url} comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
          nodes{id body url createdAt updatedAt author{login url} replies(first:100){pageInfo{hasNextPage endCursor}
          nodes{id body url createdAt updatedAt author{login url}}}}}}}}"""
        cursor, all_comments, discussion = None, [], None
        for _ in range(10):
            payload = self.request("/graphql", method="POST", json={"query": query,
                "variables": {"owner": owner, "name": name, "number": number, "cursor": cursor}}).json()
            if payload.get("errors"):
                raise UpstreamError("GitHub Discussions unavailable or permission denied")
            repo = payload["data"]["repository"]
            if not repo or repo["isPrivate"] or not repo["discussion"]:
                raise UpstreamError("Public discussion unavailable")
            discussion = repo["discussion"]
            for comment in discussion["comments"]["nodes"]:
                replies = comment["replies"]
                reply_nodes = list(replies["nodes"])
                for _ in range(10):
                    if not replies["pageInfo"]["hasNextPage"]:
                        break
                    reply_query = """query($id:ID!,$cursor:String){node(id:$id){... on DiscussionComment{
                      replies(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
                      nodes{id body url createdAt updatedAt author{login url}}}}}}"""
                    out = self.request("/graphql", method="POST", json={"query": reply_query,
                        "variables": {"id": comment["id"], "cursor": replies["pageInfo"]["endCursor"]}}).json()
                    if out.get("errors"):
                        raise UpstreamError("Discussion reply pagination failed")
                    replies = out["data"]["node"]["replies"]
                    reply_nodes.extend(replies["nodes"])
                if replies["pageInfo"]["hasNextPage"]:
                    raise IncompleteSource("Discussion reply pagination cap")
                comment["replies"] = reply_nodes
                all_comments.append(comment)
            page = discussion["comments"]["pageInfo"]
            if not page["hasNextPage"]:
                discussion["comments"] = all_comments
                return discussion
            cursor = page["endCursor"]
        raise IncompleteSource("Discussion comment pagination cap")


def discourse_origin(value: str) -> str:
    parsed = urlsplit(value)
    origin = f"https://{parsed.netloc}"
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or origin not in settings().discourse_origins.split(",")):
        raise ValueError("Discourse origin must be HTTPS and operator-allowlisted")
    for addr in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[4][0]).is_global:
            raise ValueError("Discourse origin resolves to a non-public address")
    return origin


def discourse_topic(origin: str, topic_id: int):
    origin = discourse_origin(origin)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        def get(path, params=None):
            for attempt in range(3):
                try:
                    response = client.get(f"{origin}{path}", params=params)
                except httpx.TransportError as exc:
                    if attempt == 2:
                        raise UpstreamError("Discourse network request failed after three attempts") from exc
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        raise UpstreamError(f"Discourse returned retryable HTTP {response.status_code}")
                    retry_after = response.headers.get("retry-after", "")
                    delay = int(retry_after) if retry_after.isdigit() else 2 ** attempt
                    time.sleep(min(delay, 60))
                    continue
                if response.status_code >= 300:
                    raise UpstreamError(f"Discourse returned HTTP {response.status_code}")
                return response
            raise UpstreamError("Discourse retries exhausted")

        response = get(f"/t/{topic_id}.json")
        topic = response.json()
        if not topic.get("visible", True) or topic.get("archetype") == "private_message":
            raise UpstreamError("Only public Discourse topics are allowed")
        stream = topic["post_stream"]
        if len(stream["stream"]) > 2000:
            raise IncompleteSource("Topic exceeds configured 2000-post budget")
        posts = {p["id"]: p for p in stream["posts"]}
        missing = [pid for pid in stream["stream"] if pid not in posts]
        for start in range(0, len(missing), 20):
            r = get(f"/t/{topic_id}/posts.json",
                    params=[("post_ids[]", pid) for pid in missing[start:start + 20]])
            posts.update({p["id"]: p for p in r.json()["post_stream"]["posts"]})
        if set(stream["stream"]) != set(posts):
            raise IncompleteSource("Discourse omitted posts")
        topic["post_stream"]["posts"] = [posts[pid] for pid in stream["stream"]]
        return topic


def digest(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()
