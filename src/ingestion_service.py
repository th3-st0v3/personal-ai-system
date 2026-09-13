"""Safe project-source ingestion primitives for grounded engineering Q&A."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import urlsplit

import ai_security
import engineering_schema
import workspace_storage

MAX_SOURCE_CHARS = 2_000_000
DEFAULT_CHUNK_CHARS = 4_000
MAX_TITLE_CHARS = 240
MAX_VERSION_CHARS = 120
MAX_URL_CHARS = 2_000
SOURCE_TYPES = frozenset({"text", "github", "pdf", "document", "web", "api", "external"})


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunks(content: str, size: int) -> list[str]:
    if not isinstance(size, int) or isinstance(size, bool) or not 100 <= size <= 20_000:
        raise ValueError("chunk size must be an integer between 100 and 20000 characters")
    return [content[i:i + size] for i in range(0, len(content), size)] or [""]


def _require_project(connection: sqlite3.Connection, project_id: int) -> None:
    if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id <= 0:
        raise ValueError("project_id must be a positive integer")
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


def _ensure_schema(connection: sqlite3.Connection) -> None:
    # Keep the compatibility path for direct callers while preventing the
    # ingestion functions from each maintaining their own slightly different
    # initialization sequence.
    workspace_storage._initialize_schema(connection)
    engineering_schema.initialize(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)").fetchall()}
    if "trust_level" not in columns:
        connection.execute("ALTER TABLE sources ADD COLUMN trust_level TEXT NOT NULL DEFAULT 'untrusted'")
    connection.commit()


def _validate_metadata(title: object, source_type: object, version: object, url: object) -> tuple[str, str, str | None, str | None]:
    normalized_title = " ".join(str(title).split()).strip()
    if not normalized_title:
        raise ValueError("title must be non-empty")
    if len(normalized_title) > MAX_TITLE_CHARS:
        raise ValueError(f"title exceeds {MAX_TITLE_CHARS} characters")
    if not isinstance(source_type, str) or source_type.casefold() not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
    normalized_version = None if version is None else " ".join(str(version).split()).strip()
    if normalized_version and len(normalized_version) > MAX_VERSION_CHARS:
        raise ValueError(f"version exceeds {MAX_VERSION_CHARS} characters")
    normalized_url = None if url is None else str(url).strip()
    if normalized_url:
        if len(normalized_url) > MAX_URL_CHARS:
            raise ValueError(f"url exceeds {MAX_URL_CHARS} characters")
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http or https URL")
    return normalized_title, source_type.casefold(), normalized_version or None, normalized_url or None


def ingest_text(
    connection: sqlite3.Connection,
    project_id: int,
    title: str,
    content: str,
    *,
    source_type: str = "text",
    version: str | None = None,
    url: str | None = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> dict[str, object]:
    """Store external source text as inert, traceable, explicitly untrusted data."""
    _ensure_schema(connection)
    _require_project(connection, project_id)
    content = ai_security.validate_external_text(content, field="content", max_chars=MAX_SOURCE_CHARS)
    title, source_type, version, url = _validate_metadata(title, source_type, version, url)
    checksum = _checksum(content)
    inspection = ai_security.inspect_untrusted_text(content, label=f"source:{source_type}", max_chars=MAX_SOURCE_CHARS)
    existing = connection.execute(
        "SELECT id, checksum FROM sources WHERE project_id = ? AND title = ? ORDER BY id DESC LIMIT 1",
        (project_id, title),
    ).fetchone()
    if existing and existing[1] == checksum:
        return get_source(connection, int(existing[0]))
    cursor = connection.execute(
        "INSERT INTO sources (project_id, title, source_type, version, url, checksum, trust_level) VALUES (?, ?, ?, ?, ?, ?, 'untrusted')",
        (project_id, title, source_type, version, url, checksum),
    )
    source_id = cursor.lastrowid
    if source_id is None:
        raise RuntimeError("Database did not return a source ID.")
    parts = _chunks(content, chunk_chars)
    for index, part in enumerate(parts):
        connection.execute(
            "INSERT INTO source_chunks (source_id, chunk_index, content, location_text, checksum) VALUES (?, ?, ?, ?, ?)",
            (source_id, index, part, f"chunk {index + 1}/{len(parts)}", _checksum(part)),
        )
    connection.commit()
    result = get_source(connection, int(source_id))
    result["inspection"] = inspection
    return result


def get_source(connection: sqlite3.Connection, source_id: int) -> dict[str, object]:
    if not isinstance(source_id, int) or isinstance(source_id, bool) or source_id <= 0:
        raise ValueError("source_id must be a positive integer")
    _ensure_schema(connection)
    row = connection.execute(
        "SELECT id, project_id, title, source_type, version, url, checksum, created_at, trust_level FROM sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No source found with ID {source_id}.")
    chunks = connection.execute(
        "SELECT id, chunk_index, location_text, checksum, length(content) FROM source_chunks WHERE source_id = ? ORDER BY chunk_index",
        (source_id,),
    ).fetchall()
    return {
        "id": row[0], "project_id": row[1], "title": row[2], "source_type": row[3],
        "version": row[4], "url": row[5], "checksum": row[6], "created_at": row[7],
        "trust_level": row[8] or "untrusted",
        "chunks": [{"id": r[0], "index": r[1], "location": r[2], "checksum": r[3], "chars": r[4]} for r in chunks],
    }


def get_chunk(connection: sqlite3.Connection, project_id: int, chunk_id: int) -> dict[str, object]:
    """Return one source chunk only when it belongs to the requested project."""
    _ensure_schema(connection)
    _require_project(connection, project_id)
    if not isinstance(chunk_id, int) or isinstance(chunk_id, bool) or chunk_id <= 0:
        raise ValueError("chunk_id must be a positive integer")
    row = connection.execute(
        """
        SELECT sc.id, sc.source_id, s.title, s.source_type, s.version, s.url,
               sc.chunk_index, sc.content, sc.location_text, sc.checksum, s.checksum, s.trust_level
        FROM source_chunks sc JOIN sources s ON s.id = sc.source_id
        WHERE sc.id = ? AND s.project_id = ?
        """,
        (chunk_id, project_id),
    ).fetchone()
    if row is None:
        raise ValueError("Source chunk not found in project.")
    return {
        "chunk_id": int(row[0]), "source_id": int(row[1]), "source": str(row[2]),
        "source_type": str(row[3]), "version": None if row[4] is None else str(row[4]),
        "url": None if row[5] is None else str(row[5]), "chunk_index": int(row[6]),
        "content": str(row[7]), "location": str(row[8]), "checksum": str(row[9]),
        "source_checksum": str(row[10]), "trust_level": str(row[11] or "untrusted"),
    }


def search_chunks(connection: sqlite3.Connection, project_id: int, query: str, limit: int = 10) -> list[dict[str, object]]:
    _ensure_schema(connection)
    _require_project(connection, project_id)
    query = re.sub(r"\s+", " ", str(query)).strip()
    if not query:
        raise ValueError("query must be non-empty")
    if len(query) > ai_security.MAX_QUERY_CHARS:
        raise ValueError(f"query exceeds {ai_security.MAX_QUERY_CHARS} characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    rows = connection.execute("""
        SELECT sc.id, sc.source_id, s.title, sc.chunk_index, sc.content,
               sc.location_text, s.checksum, s.trust_level
        FROM source_chunks sc JOIN sources s ON s.id = sc.source_id
        WHERE s.project_id = ? AND sc.content LIKE ?
        ORDER BY s.id DESC, sc.chunk_index LIMIT ?
    """, (project_id, f"%{query}%", limit)).fetchall()
    return [{
        "chunk_id": r[0], "source_id": r[1], "source": r[2], "chunk_index": r[3],
        "content": r[4], "location": r[5], "source_checksum": r[6],
        "trust_level": r[7] or "untrusted",
    } for r in rows]
