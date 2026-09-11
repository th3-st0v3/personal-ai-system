"""Project-scoped workspace primitives for the beta architecture.

A project is a durable workspace, not a note with a name and description.
Workspace items form an arbitrarily deep tree. Items can be folders, notes,
files, links, datasets, or future application-specific resources.

The module intentionally keeps storage and presentation separate:
- SQLite stores hierarchy and metadata.
- file_storage stores opaque file bytes.
- callers can build desktop-like or browser-like UIs on the same API.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from db import DATABASE_PATH, get_connection
from file_storage import delete_bytes, read_bytes, save_bytes, storage_path

ItemType = Literal["folder", "note", "file", "link", "dataset", "resource"]
SORT_KEYS = {
    "name_asc": "LOWER(name) ASC, id ASC",
    "name_desc": "LOWER(name) DESC, id DESC",
    "created_new_old": "created_at DESC, id DESC",
    "created_old_new": "created_at ASC, id ASC",
    "modified_new_old": "updated_at DESC, id DESC",
    "modified_old_new": "updated_at ASC, id ASC",
}


@dataclass(frozen=True)
class WorkspaceItem:
    id: int
    project_id: int
    parent_id: int | None
    item_type: ItemType
    name: str
    mime_type: str | None
    extension: str | None
    content: str | None
    storage_key: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    accessed_at: str | None
    sort_order: int

    @property
    def is_container(self) -> bool:
        return self.item_type == "folder"


def _storage_root() -> Path:
    return Path(DATABASE_PATH).resolve().parent / "workspace_data"


def initialize_workspace(connection: sqlite3.Connection) -> None:
    """Create workspace tables/indexes without coupling them to UI code."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS project_workspaces (
            project_id INTEGER PRIMARY KEY,
            root_item_id INTEGER,
            settings TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspace_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            parent_id INTEGER,
            item_type TEXT NOT NULL CHECK (item_type IN ('folder','note','file','link','dataset','resource')),
            name TEXT NOT NULL,
            mime_type TEXT,
            extension TEXT,
            content TEXT,
            storage_key TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            accessed_at TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES workspace_items(id) ON DELETE CASCADE,
            CHECK ((item_type = 'folder' AND content IS NULL AND storage_key IS NULL)
                OR item_type <> 'folder')
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_items_parent ON workspace_items(project_id, parent_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_items_type ON workspace_items(project_id, item_type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_items_name ON workspace_items(project_id, name COLLATE NOCASE)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_items_modified ON workspace_items(project_id, updated_at)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_item_sibling_name ON workspace_items(project_id, parent_id, name COLLATE NOCASE)")


def _ensure_schema() -> None:
    connection = get_connection()
    try:
        initialize_workspace(connection)
        connection.commit()
    finally:
        connection.close()


def _row_to_item(row: sqlite3.Row | tuple) -> WorkspaceItem:
    return WorkspaceItem(
        id=row[0], project_id=row[1], parent_id=row[2], item_type=row[3], name=row[4],
        mime_type=row[5], extension=row[6], content=row[7], storage_key=row[8],
        metadata=json.loads(row[9] or "{}"), created_at=row[10], updated_at=row[11],
        accessed_at=row[12], sort_order=row[13],
    )


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("name must be a non-empty single workspace component")
    return value


def _get_item(connection: sqlite3.Connection, item_id: int) -> WorkspaceItem | None:
    row = connection.execute("""
        SELECT id, project_id, parent_id, item_type, name, mime_type, extension,
               content, storage_key, metadata, created_at, updated_at, accessed_at, sort_order
        FROM workspace_items WHERE id = ?
    """, (item_id,)).fetchone()
    return None if row is None else _row_to_item(row)


def _require_project(connection: sqlite3.Connection, project_id: int) -> None:
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


def _require_parent(connection: sqlite3.Connection, project_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    row = connection.execute(
        "SELECT project_id, item_type FROM workspace_items WHERE id = ?", (parent_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No workspace item found with ID {parent_id}.")
    if row[0] != project_id:
        raise ValueError("Parent item belongs to a different project.")
    if row[1] != "folder":
        raise ValueError("Only folders can contain children.")


def ensure_project_workspace(project_id: int) -> int:
    """Ensure a project has an isolated root folder and return its item id."""
    _ensure_schema()
    connection = get_connection()
    try:
        _require_project(connection, project_id)
        row = connection.execute(
            "SELECT root_item_id FROM project_workspaces WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is not None and row[0] is not None:
            return row[0]

        cursor = connection.execute("""
            INSERT INTO workspace_items (project_id, parent_id, item_type, name, metadata)
            VALUES (?, NULL, 'folder', ?, '{}')
        """, (project_id, "Project"))
        root_id = cursor.lastrowid
        connection.execute("""
            INSERT INTO project_workspaces (project_id, root_item_id)
            VALUES (?, ?)
            ON CONFLICT(project_id) DO UPDATE SET root_item_id = excluded.root_item_id,
                                                 updated_at = datetime('now')
        """, (project_id, root_id))
        connection.commit()
        return root_id
    finally:
        connection.close()


def create_project_workspace(project_id: int, *, settings: dict[str, Any] | None = None) -> int:
    root_id = ensure_project_workspace(project_id)
    if settings is not None:
        connection = get_connection()
        try:
            connection.execute(
                "UPDATE project_workspaces SET settings = ?, updated_at = datetime('now') WHERE project_id = ?",
                (json.dumps(settings, sort_keys=True), project_id),
            )
            connection.commit()
        finally:
            connection.close()
    return root_id


def get_project_workspace(project_id: int) -> dict[str, Any]:
    root_id = ensure_project_workspace(project_id)
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT project_id, root_item_id, settings, created_at, updated_at FROM project_workspaces WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return {
            "project_id": row[0],
            "root_item_id": root_id,
            "settings": json.loads(row[2] or "{}"),
            "created_at": row[3],
            "updated_at": row[4],
        }
    finally:
        connection.close()


def _create_item(project_id: int, parent_id: int | None, item_type: ItemType, name: str,
                 *, content: str | None = None, storage_key: str | None = None,
                 mime_type: str | None = None, extension: str | None = None,
                 metadata: dict[str, Any] | None = None) -> int:
    _ensure_schema()
    name = _validate_name(name)
    connection = get_connection()
    try:
        _require_project(connection, project_id)
        _require_parent(connection, project_id, parent_id)
        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM workspace_items WHERE project_id = ? AND parent_id IS ?",
            (project_id, parent_id),
        ).fetchone()[0]
        cursor = connection.execute("""
            INSERT INTO workspace_items (
                project_id, parent_id, item_type, name, mime_type, extension,
                content, storage_key, metadata, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, parent_id, item_type, name, mime_type, extension,
            content, storage_key, json.dumps(metadata or {}, sort_keys=True), next_order,
        ))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def create_folder(project_id: int, name: str, parent_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    if parent_id is None:
        parent_id = ensure_project_workspace(project_id)
    return _create_item(project_id, parent_id, "folder", name, metadata=metadata)


def create_note(project_id: int, name: str, content: str = "", parent_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    if parent_id is None:
        parent_id = ensure_project_workspace(project_id)
    return _create_item(project_id, parent_id, "note", name, content=content, mime_type="text/markdown", extension=".md", metadata=metadata)


def create_link(project_id: int, name: str, target: str, parent_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    if parent_id is None:
        parent_id = ensure_project_workspace(project_id)
    data = dict(metadata or {})
    data["target"] = target
    return _create_item(project_id, parent_id, "link", name, metadata=data)


def create_resource(project_id: int, name: str, resource_type: str, parent_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    if parent_id is None:
        parent_id = ensure_project_workspace(project_id)
    data = dict(metadata or {})
    data["resource_type"] = resource_type
    return _create_item(project_id, parent_id, "resource", name, metadata=data)


def create_file(project_id: int, name: str, data: bytes, parent_id: int | None = None, *, mime_type: str | None = None, metadata: dict[str, Any] | None = None) -> int:
    if parent_id is None:
        parent_id = ensure_project_workspace(project_id)
    name = _validate_name(name)
    extension = Path(name).suffix.lower() or None
    mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    storage_key = f"projects/{project_id}/{secrets.token_hex(12)}{extension or ''}"
    digest = save_bytes(_storage_root(), storage_key, data)
    data_metadata = dict(metadata or {})
    data_metadata.update({"sha256": digest, "size": len(data)})
    return _create_item(project_id, parent_id, "file", name, storage_key=storage_key, mime_type=mime, extension=extension, metadata=data_metadata)


def get_item(item_id: int) -> WorkspaceItem | None:
    _ensure_schema()
    connection = get_connection()
    try:
        return _get_item(connection, item_id)
    finally:
        connection.close()


def list_children(project_id: int, parent_id: int | None = None, *, sort: str = "name_asc", item_type: ItemType | None = None) -> list[WorkspaceItem]:
    _ensure_schema()
    if sort not in SORT_KEYS:
        raise ValueError(f"Unknown sort '{sort}'.")
    connection = get_connection()
    try:
        _require_project(connection, project_id)
        where = ["project_id = ?", "parent_id IS ?"]
        params: list[Any] = [project_id, parent_id]
        if item_type is not None:
            where.append("item_type = ?")
            params.append(item_type)
        rows = connection.execute(
            f"""SELECT id, project_id, parent_id, item_type, name, mime_type, extension,
                       content, storage_key, metadata, created_at, updated_at, accessed_at, sort_order
                FROM workspace_items WHERE {' AND '.join(where)} ORDER BY {SORT_KEYS[sort]}""",
            params,
        ).fetchall()
        return [_row_to_item(row) for row in rows]
    finally:
        connection.close()


def update_item(item_id: int, *, name: str | None = None, content: str | None = None,
                metadata: dict[str, Any] | None = None) -> WorkspaceItem:
    _ensure_schema()
    connection = get_connection()
    try:
        item = _get_item(connection, item_id)
        if item is None:
            raise ValueError(f"No workspace item found with ID {item_id}.")
        updates: list[str] = []
        params: list[Any] = []
        if name is not None:
            updates.append("name = ?")
            params.append(_validate_name(name))
        if content is not None:
            if item.item_type not in {"note", "resource", "dataset", "link"}:
                raise ValueError("Only content-capable items can update inline content.")
            updates.append("content = ?")
            params.append(content)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, sort_keys=True))
        if not updates:
            return item
        updates.append("updated_at = datetime('now')")
        params.append(item_id)
        connection.execute(f"UPDATE workspace_items SET {', '.join(updates)} WHERE id = ?", params)
        connection.commit()
        result = _get_item(connection, item_id)
        assert result is not None
        return result
    finally:
        connection.close()


def move_item(item_id: int, new_parent_id: int | None) -> None:
    _ensure_schema()
    connection = get_connection()
    try:
        item = _get_item(connection, item_id)
        if item is None:
            raise ValueError(f"No workspace item found with ID {item_id}.")
        if item.parent_id == new_parent_id:
            return
        _require_parent(connection, item.project_id, new_parent_id)
        if new_parent_id == item_id:
            raise ValueError("An item cannot contain itself.")

        cursor = new_parent_id
        while cursor is not None:
            if cursor == item_id:
                raise ValueError("Cannot move an item into one of its descendants.")
            parent = connection.execute("SELECT parent_id FROM workspace_items WHERE id = ?", (cursor,)).fetchone()
            cursor = None if parent is None else parent[0]

        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM workspace_items WHERE project_id = ? AND parent_id IS ?",
            (item.project_id, new_parent_id),
        ).fetchone()[0]
        connection.execute(
            "UPDATE workspace_items SET parent_id = ?, sort_order = ?, updated_at = datetime('now') WHERE id = ?",
            (new_parent_id, next_order, item_id),
        )
        connection.commit()
    finally:
        connection.close()


def reorder_item(item_id: int, target_index: int) -> None:
    _ensure_schema()
    connection = get_connection()
    try:
        item = _get_item(connection, item_id)
        if item is None:
            raise ValueError(f"No workspace item found with ID {item_id}.")
        siblings = connection.execute(
            "SELECT id FROM workspace_items WHERE project_id = ? AND parent_id IS ? AND id <> ? ORDER BY sort_order, id",
            (item.project_id, item.parent_id, item_id),
        ).fetchall()
        target_index = max(0, min(target_index, len(siblings)))
        ordered = [row[0] for row in siblings]
        ordered.insert(target_index, item_id)
        for index, sibling_id in enumerate(ordered):
            connection.execute("UPDATE workspace_items SET sort_order = ?, updated_at = CASE WHEN id = ? THEN datetime('now') ELSE updated_at END WHERE id = ?", (index, item_id, sibling_id))
        connection.commit()
    finally:
        connection.close()


def delete_item(item_id: int, *, recursive: bool = True) -> int:
    """Delete a file/folder subtree and return number of metadata items deleted."""
    _ensure_schema()
    connection = get_connection()
    try:
        item = _get_item(connection, item_id)
        if item is None:
            raise ValueError(f"No workspace item found with ID {item_id}.")
        if item.parent_id is None:
            raise ValueError("The project workspace root cannot be deleted.")
        descendants = connection.execute("""
            WITH RECURSIVE subtree(id) AS (
                SELECT id FROM workspace_items WHERE id = ?
                UNION ALL
                SELECT child.id FROM workspace_items child JOIN subtree ON child.parent_id = subtree.id
            ) SELECT id, item_type, storage_key FROM workspace_items WHERE id IN (SELECT id FROM subtree)
        """, (item_id,)).fetchall()
        if not recursive and any(row[1] == "folder" for row in descendants):
            children = connection.execute("SELECT 1 FROM workspace_items WHERE parent_id = ? LIMIT 1", (item_id,)).fetchone()
            if children is not None:
                raise ValueError("Folder is not empty; pass recursive=True to delete its subtree.")
        storage_keys = [row[2] for row in descendants if row[2]]
        connection.execute("DELETE FROM workspace_items WHERE id IN (SELECT id FROM (WITH RECURSIVE subtree(id) AS (SELECT ? UNION ALL SELECT child.id FROM workspace_items child JOIN subtree ON child.parent_id = subtree.id) SELECT id FROM subtree))", (item_id,))
        connection.commit()
    finally:
        connection.close()
    for key in storage_keys:
        delete_bytes(_storage_root(), key)
    return len(descendants)


def delete_all_children(project_id: int, parent_id: int | None = None) -> int:
    """Remove every child below a folder/project root, preserving the container itself."""
    items = list_children(project_id, parent_id, sort="name_asc")
    total = 0
    for item in items:
        total += delete_item(item.id, recursive=True)
    return total


def duplicate_item(item_id: int, *, new_parent_id: int | None = None, new_name: str | None = None) -> int:
    """Deep-copy a workspace item, including file bytes."""
    _ensure_schema()
    source = get_item(item_id)
    if source is None:
        raise ValueError(f"No workspace item found with ID {item_id}.")
    target_parent = source.parent_id if new_parent_id is None else new_parent_id
    root_name = _validate_name(new_name or f"{source.name} copy")

    if source.item_type == "folder":
        new_id = create_folder(source.project_id, root_name, target_parent, metadata=source.metadata)
    elif source.item_type == "note":
        new_id = create_note(source.project_id, root_name, source.content or "", target_parent, metadata=source.metadata)
    elif source.item_type == "file":
        payload = read_bytes(_storage_root(), source.storage_key)  # type: ignore[arg-type]
        new_id = create_file(source.project_id, root_name, payload, target_parent, mime_type=source.mime_type, metadata=source.metadata)
    elif source.item_type == "link":
        target = source.metadata.get("target", "")
        new_id = create_link(source.project_id, root_name, target, target_parent, metadata={k: v for k, v in source.metadata.items() if k != "target"})
    else:
        new_id = create_resource(source.project_id, root_name, source.metadata.get("resource_type", source.item_type), target_parent, metadata=source.metadata)
        if source.content is not None:
            update_item(new_id, content=source.content)

    if source.item_type == "folder":
        for child in list_children(source.project_id, source.id, sort="created_old_new"):
            duplicate_item(child.id, new_parent_id=new_id)
    return new_id


def find_items(project_id: int, query: str, *, recursive: bool = True) -> list[WorkspaceItem]:
    _ensure_schema()
    query = query.strip()
    if not query:
        return []
    connection = get_connection()
    try:
        _require_project(connection, project_id)
        rows = connection.execute("""
            SELECT id, project_id, parent_id, item_type, name, mime_type, extension,
                   content, storage_key, metadata, created_at, updated_at, accessed_at, sort_order
            FROM workspace_items
            WHERE project_id = ? AND (name LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE)
            ORDER BY updated_at DESC, id DESC
        """, (project_id, f"%{query}%", f"%{query}%")).fetchall()
        return [_row_to_item(row) for row in rows]
    finally:
        connection.close()


def get_context_actions(item_id: int) -> list[str]:
    """Return file-explorer/Obsidian-style actions based on the clicked item type."""
    item = get_item(item_id)
    if item is None:
        raise ValueError(f"No workspace item found with ID {item_id}.")
    common = ["open", "rename", "duplicate", "move", "copy", "delete", "properties"]
    if item.item_type == "folder":
        return ["open", "new_folder", "new_note", "new_file", "paste", "sort", "rename", "duplicate", "move", "copy", "delete", "delete_all_children", "properties"]
    if item.item_type == "note":
        return ["open", "edit", "new_note", "new_folder", "duplicate", "move", "copy", "export", "pin", "delete", "properties"]
    if item.item_type == "file":
        return ["open", "preview", "download", "rename", "duplicate", "move", "copy", "replace", "delete", "properties"]
    if item.item_type == "link":
        return ["open", "open_target", "edit_target", "rename", "duplicate", "move", "copy", "delete", "properties"]
    return common


def get_item_ancestors(item_id: int) -> list[WorkspaceItem]:
    _ensure_schema()
    connection = get_connection()
    try:
        item = _get_item(connection, item_id)
        if item is None:
            raise ValueError(f"No workspace item found with ID {item_id}.")
        chain: list[WorkspaceItem] = []
        cursor = item.parent_id
        while cursor is not None:
            parent = _get_item(connection, cursor)
            if parent is None:
                break
            chain.append(parent)
            cursor = parent.parent_id
        chain.reverse()
        return chain
    finally:
        connection.close()


def bulk_delete(item_ids: Iterable[int]) -> int:
    """Delete a selection while avoiding double-deleting nested selections."""
    selected = {int(item_id) for item_id in item_ids}
    if not selected:
        return 0
    total = 0
    for item_id in sorted(selected, key=lambda value: len(get_item_ancestors(value)), reverse=False):
        item = get_item(item_id)
        if item is None:
            continue
        ancestors = {ancestor.id for ancestor in get_item_ancestors(item_id)}
        if selected.intersection(ancestors):
            continue
        total += delete_item(item_id, recursive=True)
    return total
