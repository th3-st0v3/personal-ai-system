"""UI-agnostic workspace browser contract for the beta application.

This layer makes folders, notes, and uploaded files behave as one project
workspace while preserving the existing storage/application boundaries.
A frontend can render this API as a tree, list, canvas, tabs, or another UI.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Literal

import db
import workspace_storage
from workspace_file_service import create_file as create_stored_file, delete_file as delete_stored_file, delete_files as delete_stored_files

ItemKind = Literal["folder", "note", "file"]
SORT_OPTIONS = {
    "a_z": "name ASC, kind ASC, id ASC",
    "z_a": "name DESC, kind DESC, id DESC",
    "recent_old": "created_at DESC, id DESC",
    "old_recent": "created_at ASC, id ASC",
    "last_modified_new_old": "updated_at DESC, id DESC",
    "last_modified_old_new": "updated_at ASC, id ASC",
}
SORT_ALIASES = {
    "name_asc": "a_z", "name_desc": "z_a",
    "created_new_old": "recent_old", "created_old_new": "old_recent",
    "modified_new_old": "last_modified_new_old", "modified_old_new": "last_modified_old_new",
}


@dataclass(frozen=True)
class BrowserItem:
    kind: ItemKind
    id: int
    project_id: int
    parent_id: int | None
    name: str
    mime_type: str | None
    content: str | None
    size_bytes: int | None
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


def _init(connection: sqlite3.Connection) -> None:
    workspace_storage._initialize_schema(connection)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspace_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            folder_id INTEGER,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (folder_id, project_id) REFERENCES folders(id, project_id) ON DELETE RESTRICT
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_notes_parent ON workspace_notes(project_id, folder_id, updated_at)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_notes_sibling_name ON workspace_notes(project_id, folder_id, title COLLATE NOCASE)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_notes_name ON workspace_notes(project_id, title COLLATE NOCASE)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_notes_modified ON workspace_notes(project_id, updated_at)")
    connection.commit()


def _connection() -> sqlite3.Connection:
    connection = db.get_connection()
    _init(connection)
    return connection


def _project(connection: sqlite3.Connection, project_id: int) -> None:
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


def _note_row(row) -> BrowserItem:
    return BrowserItem("note", row[0], row[1], row[2], row[3], "text/markdown", row[4], None, row[5], row[6], json.loads(row[7] or "{}"))


def _note(connection: sqlite3.Connection, note_id: int) -> BrowserItem | None:
    row = connection.execute("SELECT id, project_id, folder_id, title, content, created_at, updated_at, metadata FROM workspace_notes WHERE id = ?", (note_id,)).fetchone()
    return None if row is None else _note_row(row)


def create_note(project_id: int, title: str, content: str = "", folder_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    title = title.strip()
    if not title:
        raise ValueError("Note title is required.")
    connection = _connection()
    try:
        _project(connection, project_id)
        if folder_id is not None:
            workspace_storage._require_folder_in_project(connection, folder_id, project_id)
        cursor = connection.execute("INSERT INTO workspace_notes (project_id, folder_id, title, content, metadata) VALUES (?, ?, ?, ?, ?)", (project_id, folder_id, title, content, json.dumps(metadata or {}, sort_keys=True)))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_note(note_id: int) -> BrowserItem | None:
    connection = _connection()
    try:
        return _note(connection, note_id)
    finally:
        connection.close()


def update_note(note_id: int, *, title: str | None = None, content: str | None = None, metadata: dict[str, Any] | None = None) -> BrowserItem:
    connection = _connection()
    try:
        note = _note(connection, note_id)
        if note is None:
            raise ValueError(f"No note found with ID {note_id}.")
        updates, params = [], []
        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError("Note title is required.")
            updates.append("title = ?"); params.append(title)
        if content is not None:
            updates.append("content = ?"); params.append(content)
        if metadata is not None:
            updates.append("metadata = ?"); params.append(json.dumps(metadata, sort_keys=True))
        if updates:
            params.append(note_id)
            connection.execute(f"UPDATE workspace_notes SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = ?", params)
            connection.commit()
        result = _note(connection, note_id)
        assert result is not None
        return result
    finally:
        connection.close()


def _validate_note_move(connection: sqlite3.Connection, note_id: int, folder_id: int | None) -> None:
    note = _note(connection, note_id)
    if note is None:
        raise ValueError(f"No note found with ID {note_id}.")
    if folder_id is not None:
        workspace_storage._require_folder_in_project(connection, folder_id, note.project_id)


def move_note(note_id: int, folder_id: int | None) -> None:
    connection = _connection()
    try:
        _validate_note_move(connection, note_id, folder_id)
        connection.execute("UPDATE workspace_notes SET folder_id = ?, updated_at = datetime('now') WHERE id = ?", (folder_id, note_id))
        connection.commit()
    finally:
        connection.close()


def delete_note(note_id: int) -> None:
    connection = _connection()
    try:
        if _note(connection, note_id) is None:
            raise ValueError(f"No note found with ID {note_id}.")
        connection.execute("DELETE FROM workspace_notes WHERE id = ?", (note_id,))
        connection.commit()
    finally:
        connection.close()


def list_children(project_id: int, folder_id: int | None = None, *, sort: str = "a_z") -> list[BrowserItem]:
    sort = SORT_ALIASES.get(sort, sort)
    if sort not in SORT_OPTIONS:
        raise ValueError(f"Unknown sort '{sort}'.")
    connection = _connection()
    try:
        _project(connection, project_id)
        folders = [
            BrowserItem("folder", r[0], r[1], r[2], r[3], None, None, None, r[5], r[6], {})
            for r in workspace_storage.get_folders(project_id, folder_id)
        ]
        files = [
            BrowserItem("file", r[0], r[1], r[2], r[3], r[5], None, r[6], r[9], r[10], {"sha256": r[7], "lifecycle_status": r[8]})
            for r in workspace_storage.get_files(project_id, folder_id)
        ]
        note_rows = connection.execute(
            "SELECT id, project_id, folder_id, title, content, created_at, updated_at, metadata FROM workspace_notes WHERE project_id = ? AND folder_id IS ?",
            (project_id, folder_id),
        ).fetchall()
        notes = [_note_row(r) for r in note_rows]
        items = folders + files + notes
        if sort in {"a_z", "z_a"}:
            reverse = sort == "z_a"
            return sorted(items, key=lambda i: (i.name.casefold(), i.kind, i.id), reverse=reverse)
        reverse = sort in {"recent_old", "last_modified_new_old"}
        field = "created_at" if sort in {"recent_old", "old_recent"} else "updated_at"
        return sorted(items, key=lambda i: (getattr(i, field), i.id), reverse=reverse)
    finally:
        connection.close()


def list_project_items(project_id: int, *, recursive: bool = True, sort: str = "a_z") -> list[BrowserItem]:
    result: list[BrowserItem] = []
    queue = [None]
    while queue:
        folder_id = queue.pop(0)
        children = list_children(project_id, folder_id, sort=sort)
        result.extend(children)
        if recursive:
            queue.extend(item.id for item in children if item.kind == "folder")
    return result


def create_file(storage_root, project_id: int, name: str, data: bytes, mime_type: str | None = None, folder_id: int | None = None) -> int:
    return create_stored_file(storage_root, project_id, name, data, mime_type, folder_id)


def move_item(kind: ItemKind, item_id: int, target_folder_id: int | None) -> None:
    if kind == "folder":
        workspace_storage.move_folder(item_id, target_folder_id)
    elif kind == "file":
        workspace_storage.move_file(item_id, target_folder_id)
    elif kind == "note":
        move_note(item_id, target_folder_id)
    else:
        raise ValueError(f"Unsupported workspace item kind: {kind}")


def rename_item(kind: ItemKind, item_id: int, name: str) -> None:
    if kind == "folder":
        workspace_storage.rename_folder(item_id, name)
    elif kind == "file":
        workspace_storage.rename_file(item_id, name)
    elif kind == "note":
        update_note(item_id, title=name)
    else:
        raise ValueError(f"Unsupported workspace item kind: {kind}")


def delete_item(storage_root, kind: ItemKind, item_id: int) -> None:
    if kind == "folder":
        # Folder deletion is intentionally non-recursive in the legacy storage API;
        # callers should use delete_selection/delete_all_children for explicit subtree semantics.
        children = list_children(_item_project(item_id, "folder"), item_id)
        if children:
            raise ValueError("Folder is not empty. Delete or move its children first.")
        workspace_storage.delete_folder(item_id)
    elif kind == "file":
        delete_stored_file(storage_root, item_id)
    elif kind == "note":
        delete_note(item_id)


def _item_project(item_id: int, kind: ItemKind) -> int:
    if kind == "folder":
        row = workspace_storage.get_folder(item_id)
    elif kind == "file":
        row = workspace_storage.get_file(item_id)
    else:
        row = get_note(item_id)
        return -1 if row is None else row.project_id
    if row is None:
        raise ValueError(f"No {kind} found with ID {item_id}.")
    return row[1] if kind != "note" else row.project_id


def _exists(kind: ItemKind, item_id: int) -> bool:
    if kind == "folder": return workspace_storage.get_folder(item_id) is not None
    if kind == "file": return workspace_storage.get_file(item_id) is not None
    return get_note(item_id) is not None


def delete_all_files(storage_root, project_id: int, folder_id: int | None = None) -> int:
    file_ids = [item.id for item in list_project_items(project_id, recursive=True, sort="a_z") if item.kind == "file" and (folder_id is None or _under_folder(project_id, item.id, folder_id))]
    return delete_stored_files(storage_root, file_ids) if file_ids else 0


def _under_folder(project_id: int, file_id: int, folder_id: int) -> bool:
    record = workspace_storage.get_file(file_id)
    if record is None or record[1] != project_id:
        return False
    current = record[2]
    while current is not None:
        if current == folder_id:
            return True
        parent = workspace_storage.get_folder(current)
        current = None if parent is None else parent[2]
    return False


def delete_selection(storage_root, project_id: int, selection: Iterable[tuple[ItemKind, int]]) -> int:
    selected = [(kind, int(item_id)) for kind, item_id in selection]
    selected_set = set(selected)
    if any(not _exists(kind, item_id) for kind, item_id in selected_set):
        raise ValueError("Selection contains a missing workspace item.")
    deleted = 0
    # Delete files/notes first; folders are removed only when empty. A selected
    # folder with descendants is intentionally a subtree operation.
    for kind, item_id in sorted(selected_set, key=lambda value: 0 if value[0] != "folder" else 1):
        if kind == "folder":
            project_id_for_item = _item_project(item_id, kind)
            descendants = list_children(project_id_for_item, item_id)
            if descendants:
                delete_all_files(storage_root, project_id_for_item, item_id)
                connection = _connection()
                try:
                    note_ids = [r[0] for r in connection.execute("WITH RECURSIVE subtree(id) AS (SELECT ? UNION ALL SELECT f.id FROM folders f JOIN subtree s ON f.parent_folder_id = s.id) SELECT n.id FROM workspace_notes n JOIN folders f ON n.folder_id = f.id WHERE f.id IN (SELECT id FROM subtree)", (item_id,)).fetchall()]
                finally:
                    connection.close()
                for note_id in note_ids:
                    delete_note(note_id)
                # Remove empty descendants bottom-up.
                folder_ids = []
                queue = [item_id]
                while queue:
                    fid = queue.pop()
                    folder_ids.append(fid)
                    queue.extend(r[0] for r in workspace_storage.get_folders(project_id_for_item, fid))
                for fid in reversed(folder_ids):
                    try:
                        workspace_storage.delete_folder(fid)
                    except ValueError:
                        pass
                deleted += 1
            else:
                workspace_storage.delete_folder(item_id); deleted += 1
        elif kind == "file":
            delete_stored_file(storage_root, item_id); deleted += 1
        else:
            delete_note(item_id); deleted += 1
    return deleted


def get_context_actions(kind: ItemKind, *, selection_count: int = 1) -> tuple[str, ...]:
    if selection_count > 1:
        return ("open", "copy", "move", "delete", "properties")
    if kind == "folder":
        return ("open", "new_folder", "new_note", "upload_file", "paste", "sort", "rename", "duplicate", "move", "copy", "delete", "delete_all_files", "properties")
    if kind == "note":
        return ("open", "edit", "new_note", "new_folder", "duplicate", "move", "copy", "export", "pin", "delete", "properties")
    return ("open", "preview", "download", "rename", "duplicate", "move", "copy", "replace", "delete", "properties")


def project_context_actions() -> tuple[str, ...]:
    return ("open", "new_folder", "new_note", "upload_file", "paste", "sort", "search", "delete_all_files", "properties")


def get_breadcrumbs(kind: ItemKind, item_id: int) -> list[tuple[str, int, str]]:
    project_id = _item_project(item_id, kind)
    folder_id = item_id if kind == "folder" else (workspace_storage.get_file(item_id)[2] if kind == "file" else get_note(item_id).parent_id)
    folders: list[tuple[str, int, str]] = []
    while folder_id is not None:
        folder = workspace_storage.get_folder(folder_id)
        if folder is None: break
        folders.append(("folder", folder[0], folder[3]))
        folder_id = folder[2]
    folders.reverse()
    return [("project", project_id, "Project")] + folders
