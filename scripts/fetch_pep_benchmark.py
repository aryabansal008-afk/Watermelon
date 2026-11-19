"""Freeze public Discourse posts into blind inputs; never fetch or parse PEP pages here."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import httpx
from backend.evaluation import validate_blind_manifest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "benchmarks/registry.json"
INPUTS = ROOT / "benchmarks/inputs"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get_retry(client: httpx.Client, url: str, params=None):
    last_error = None
    for attempt in range(4):
        try:
            response = client.get(url, params=params)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                retry_after = response.headers.get("Retry-After", "")
                delay = min(60, int(retry_after)) if retry_after.isdigit() else 2 ** attempt
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    if last_error:
        raise RuntimeError("Discourse network request failed after retry budget") from last_error
    raise RuntimeError("Discourse returned a retryable error after retry budget")


def fetch_topic(client: httpx.Client, source: dict) -> dict:
    base = f"https://discuss.python.org/t/{source['topic_id']}"
    topic = get_retry(client, base + ".json").json()
    stream = topic["post_stream"]["stream"]
    posts = {p["id"]: p for p in topic["post_stream"]["posts"]}
    for offset in range(0, len(stream), 20):
        missing = [pid for pid in stream[offset:offset + 20] if pid not in posts]
        if not missing:
            continue
        params = [("post_ids[]", str(pid)) for pid in missing]
        page = get_retry(client, base + "/posts.json", params=params).json()
        for post in page.get("post_stream", {}).get("posts", []):
            posts[post["id"]] = post
    if len(posts) != len(stream):
        raise RuntimeError(f"Incomplete Discourse snapshot for topic {source['topic_id']}: {len(posts)}/{len(stream)} posts")
    records = []
    for number, post_id in enumerate(stream, 1):
        post = posts[post_id]
        body = post.get("raw") or post.get("cooked") or ""
        # Keep original discussion content, but strip direct links to canonical PEP pages so
        # the model cannot open the evaluation reference even if the provider has tools enabled.
        body = re.sub(r"\[[^\]]*\]\(https?://peps\.python\.org/pep-[^)]+\)", "[PEP reference omitted]", body, flags=re.I)
        body = re.sub(r"<a\b[^>]*href=[\"']https?://peps\.python\.org/pep-[^\"']*[\"'][^>]*>.*?</a>",
                      "[PEP reference omitted]", body, flags=re.I | re.S)
        body = re.sub(r"https?://peps\.python\.org/pep-\S+", "[PEP reference omitted]", body, flags=re.I)
        body = re.sub(r"\S*peps\.python\.org\S*", "[PEP reference omitted]", body, flags=re.I)
        if "peps.python.org" in body.lower():
            raise RuntimeError(f"Could not redact a PEP reference from public post {post_id}")
        record = {"external_id": str(post_id), "post_number": post.get("post_number", number),
                  "url": f"{base}/{post.get('post_number', number)}", "created_at": post["created_at"],
                  "updated_at": post.get("updated_at") or post["created_at"],
                  "author": post.get("username") or "unknown", "body": body}
        record["id"] = hashlib.sha256(f"{source['topic_id']}:{post_id}".encode()).hexdigest()
        records.append(record)
    return {"topic_url": base, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Write a new version; never silently replace frozen inputs")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text())
    INPUTS.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45, follow_redirects=False, headers={"User-Agent": "WatermelonPEPBenchmark/1.0"}) as client:
        for source in registry["sources"]:
            frozen = fetch_topic(client, source)
            blind = {"version": registry["version"], "split": source["split"], "source": frozen["topic_url"],
                     "records": frozen["records"]}
            blind["sha256"] = digest({k: v for k, v in blind.items() if k != "sha256"})
            validate_blind_manifest(blind)
            version = registry["version"].replace("/", "-")
            target = INPUTS / f"{source['pep']}-{source['split']}-{version}.json"
            if target.exists():
                existing = json.loads(target.read_text())
                if existing["sha256"] != blind["sha256"]:
                    raise RuntimeError(f"Frozen input changed for PEP {source['pep']}; bump the registry version before refreshing")
            else:
                older = list(INPUTS.glob(f"{source['pep']}-{source['split']}-*.json"))
                if older and not args.refresh:
                    raise RuntimeError(f"A prior snapshot exists for PEP {source['pep']}; bump registry version and pass --refresh")
                target.write_text(json.dumps(blind, ensure_ascii=False, indent=2) + "\n")
            print(f"PEP {source['pep']} {source['split']}: {len(blind['records'])} posts sha256={blind['sha256']}")


if __name__ == "__main__":
    main()
