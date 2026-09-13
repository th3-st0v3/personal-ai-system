"""Bounded, read-only ingestion of public GitHub text files."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

import ingestion_service

MAX_GITHUB_BYTES = 2_000_000
ALLOWED_HOST = "api.github.com"


def _parse(url: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        raise ValueError("Only https://api.github.com URLs are allowed.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 5 or parts[:2] != ["repos", parts[1]] or parts[3] != "contents":
        raise ValueError("Expected a GitHub repository contents URL.")
    owner, repo = parts[1], parts[2]
    path = "/".join(parts[4:])
    if not owner or not repo or not path:
        raise ValueError("GitHub owner, repository, and file path are required.")
    query = urllib.parse.parse_qs(parsed.query)
    ref = query.get("ref", [""])[0]
    return owner, repo, path, ref


def fetch_public_file(url: str) -> dict[str, object]:
    owner, repo, path, ref = _parse(url)
    endpoint = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/contents/{urllib.parse.quote(path, safe='/')}"
    if ref:
        endpoint += "?ref=" + urllib.parse.quote(ref, safe="")
    request = urllib.request.Request(endpoint, headers={"Accept": "application/vnd.github+json", "User-Agent": "personal-ai-system"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(MAX_GITHUB_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub request failed with HTTP {exc.code}.") from exc
    if len(body) > MAX_GITHUB_BYTES:
        raise ValueError("GitHub file exceeds the ingestion size limit.")
    data = json.loads(body.decode("utf-8"))
    if data.get("type") != "file" or "content" not in data:
        raise ValueError("GitHub URL did not resolve to a single file.")
    try:
        content = base64.b64decode(data["content"], validate=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("GitHub file is not UTF-8 text.") from exc
    return {"title": path.rsplit("/", 1)[-1], "content": content, "source_type": "github", "version": data.get("sha"), "url": url, "path": path, "repository": f"{owner}/{repo}"}


def ingest_public_file(connection, project_id: int, url: str) -> dict[str, object]:
    fetched = fetch_public_file(url)
    return ingestion_service.ingest_text(connection, project_id, fetched["title"], fetched["content"], source_type="github", version=fetched["version"], url=fetched["url"])
