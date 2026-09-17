from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from automation.computer_use.research import HTTPSResearchAdapter

PERPLEXITY_SEARCH_URL = "https://api.perplexity.ai/search"
MAX_QUERY_CHARS = 500
MAX_RESULTS = 10
MAX_RESPONSE_BYTES = 2_000_000


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError:
        raise
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("search response exceeded the configured size limit")
    payload_value = json.loads(body.decode("utf-8"))
    if not isinstance(payload_value, dict):
        raise ValueError("search response must be a JSON object")
    return payload_value


def search(query: str, *, limit: int = MAX_RESULTS) -> dict[str, Any]:
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError("query must be non-empty and at most 500 characters")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")
    key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PERPLEXITY_API_KEY is not configured")
    payload = _post_json(PERPLEXITY_SEARCH_URL, {"query": query, "max_results": limit}, key)
    return {"query": query, "results": payload.get("results", []), "raw": payload}


def read_public_https(url: str) -> dict[str, Any]:
    observation = HTTPSResearchAdapter().read(url)
    return dict(observation.data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded public-web search and HTTPS scraping for PASI research.")
    parser.add_argument("--search", default="")
    parser.add_argument("--read", default="")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if bool(args.search) == bool(args.read):
        parser.error("provide exactly one of --search or --read")
    try:
        if args.search:
            print(json.dumps(search(args.search, limit=args.limit), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(read_public_https(args.read), indent=2, ensure_ascii=False))
    except (RuntimeError, ValueError, urllib.error.HTTPError, OSError) as exc:
        print(f"research failed: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
