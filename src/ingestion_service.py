"""Safe project-source ingestion primitives for grounded engineering Q&A."""
from __future__ import annotations

import hashlib
import re
import sqlite3

import engineering_schema
import workspace_storage

MAX_SOURCE_CHARS = 2_000_000
DEFAULT_CHUNK_CHARS = 4_000


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunks(content: str, size: int) -> list[str]:
    if size < 100:
        raise ValueError("chunk size must be at least 100 characters")
    return [content[i:i + size] for i in range(0, len(content), size)] or [""]


def _require_project(connection: sqlite3.Connection, project_id: int) -> None:
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


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
    """Store source text as inert, traceable data; never execute or interpret it as instructions."""
    workspace_storage._initialize_schema(connection)
    engineering_schema.initialize(connection)
    _require_project(connection, project_id)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if len(content) > MAX_SOURCE_CHARS:
        raise ValueError(f"content exceeds {MAX_SOURCE_CHARS} characters")
    title = str(title).strip()
    if not title:
        raise ValueError("title must be non-empty")
    checksum = _checksum(content)
    existing = connection.execute("SELECT id, checksum FROM sources WHERE project_id = ? AND title = ? ORDER BY id DESC LIMIT 1", (project_id, title)).fetchone()
    if existing and existing[1] == checksum:
        return get_source(connection, int(existing[0]))
    cursor = connection.execute(
        "INSERT INTO sources (project_id, title, source_type, version, url, checksum) VALUES (?, ?, ?, ?, ?, ?)",
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
    return get_source(connection, int(source_id))


def get_source(connection: sqlite3.Connection, source_id: int) -> dict[str, object]:
    row = connection.execute("SELECT id, project_id, title, source_type, version, url, checksum, created_at FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise ValueError(f"No source found with ID {source_id}.")
    chunks = connection.execute("SELECT id, chunk_index, location_text, checksum, length(content) FROM source_chunks WHERE source_id = ? ORDER BY chunk_index", (source_id,)).fetchall()
    return {"id": row[0], "project_id": row[1], "title": row[2], "source_type": row[3], "version": row[4], "url": row[5], "checksum": row[6], "created_at": row[7], "chunks": [{"id": r[0], "index": r[1], "location": r[2], "checksum": r[3], "chars": r[4]} for r in chunks]}


def get_chunk(connection: sqlite3.Connection, project_id: int, chunk_id: int) -> dict[str, object]:
    """Return one source chunk only when it belongs to the requested project."""
    workspace_storage._initialize_schema(connection)
    engineering_schema.initialize(connection)
    _require_project(connection, project_id)
    row = connection.execute(
        """
        SELECT sc.id, sc.source_id, s.title, s.source_type, s.version, s.url,
               sc.chunk_index, sc.content, sc.location_text, sc.checksum, s.checksum
        FROM source_chunks sc
        JOIN sources s ON s.id = sc.source_id
        WHERE sc.id = ? AND s.project_id = ?
        """,
        (chunk_id, project_id),
    ).fetchone()
    if row is None:
        raise ValueError("Source chunk not found in project.")
    return {
        "chunk_id": int(row[0]),
        "source_id": int(row[1]),
        "source": str(row[2]),
        "source_type": str(row[3]),
        "version": None if row[4] is None else str(row[4]),
        "url": None if row[5] is None else str(row[5]),
        "chunk_index": int(row[6]),
        "content": str(row[7]),
        "location": str(row[8]),
        "checksum": str(row[9]),
        "source_checksum": str(row[10]),
    }


def search_chunks(connection: sqlite3.Connection, project_id: int, query: str, limit: int = 10) -> list[dict[str, object]]:
    workspace_storage._initialize_schema(connection)
    engineering_schema.initialize(connection)
    _require_project(connection, project_id)
    query = re.sub(r"\s+", " ", str(query)).strip()
    if not query:
        raise ValueError("query must be non-empty")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    rows = connection.execute("""
        SELECT sc.id, sc.source_id, s.title, sc.chunk_index, sc.content,
               sc.location_text, s.checksum
        FROM source_chunks sc JOIN sources s ON s.id = sc.source_id
        WHERE s.project_id = ? AND sc.content LIKE ?
        ORDER BY s.id DESC, sc.chunk_index LIMIT ?
    """, (project_id, f"%{query}%", limit)).fetchall()
    return [{"chunk_id": r[0], "source_id": r[1], "source": r[2], "chunk_index": r[3], "content": r[4], "location": r[5], "source_checksum": r[6]} for r in rows]
