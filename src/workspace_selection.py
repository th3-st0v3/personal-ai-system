"""Atomic multi-selection operations for the beta workspace."""

import db
import engineering_schema
import workspace_storage
from project_workspace import context_actions


SUPPORTED_TYPES = {"folder", "file", "note"}


def _connection():
    connection = db.get_connection()
    engineering_schema.initialize(connection)
    workspace_storage._initialize_schema(connection)
    return connection


def _normalize(selection):
    items = []
    seen = set()
    for item in selection:
        if not isinstance(item, dict) or item.get("type") not in SUPPORTED_TYPES:
            raise ValueError("Each selected item must have type folder, file, or note.")
        item_id = item.get("id")
        if not isinstance(item_id, int):
            raise ValueError("Each selected item ID must be an integer.")
        key = (item["type"], item_id)
        if key not in seen:
            seen.add(key)
            items.append(key)
    if not items:
        raise ValueError("Selection cannot be empty.")
    return items


def _project_id(connection, item_type, item_id):
    table = {"folder": "folders", "file": "files", "note": "notes"}[item_type]
    row = connection.execute(
        f"SELECT project_id FROM {table} WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No {item_type} found with ID {item_id}.")
    return row[0]


def validate_selection(project_id, selection):
    items = _normalize(selection)
    connection = _connection()
    try:
        for item_type, item_id in items:
            if _project_id(connection, item_type, item_id) != project_id:
                raise ValueError("All selected items must belong to the same project.")
        return [{"type": item_type, "id": item_id} for item_type, item_id in items]
    finally:
        connection.close()


def available_actions(project_id, selection):
    items = validate_selection(project_id, selection)
    actions = None
    for item in items:
        row = next(
            r for r in _rows_for_items(project_id, [item]) if r["type"] == item["type"] and r["id"] == item["id"]
        )
        item_actions = set(context_actions(item["type"], row["lifecycle_status"], len(items)))
        actions = item_actions if actions is None else actions & item_actions
    return sorted(actions or [])


def _rows_for_items(project_id, selection):
    connection = _connection()
    try:
        result = []
        for item_type, item_id in _normalize(selection):
            if _project_id(connection, item_type, item_id) != project_id:
                raise ValueError("All selected items must belong to the same project.")
            table = {"folder": "folders", "file": "files", "note": "notes"}[item_type]
            row = connection.execute(
                f"SELECT lifecycle_status FROM {table} WHERE id = ?", (item_id,)
            ).fetchone()
            result.append({"type": item_type, "id": item_id, "lifecycle_status": row[0]})
        return result
    finally:
        connection.close()


def update_lifecycle(project_id, selection, lifecycle_status):
    items = validate_selection(project_id, selection)
    if lifecycle_status not in db.LIFECYCLE_STATUSES:
        raise ValueError("Invalid lifecycle status.")
    connection = _connection()
    try:
        for item in items:
            table = {"folder": "folders", "file": "files", "note": "notes"}[item["type"]]
            connection.execute(
                f"UPDATE {table} SET lifecycle_status = ?, updated_at = datetime('now') WHERE id = ?",
                (lifecycle_status, item["id"]),
            )
        connection.commit()
    finally:
        connection.close()


def delete_selection(project_id, selection):
    items = validate_selection(project_id, selection)
    connection = _connection()
    try:
        folders = [item["id"] for item in items if item["type"] == "folder"]
        notes = [item["id"] for item in items if item["type"] == "note"]
        files = [item["id"] for item in items if item["type"] == "file"]

        for folder_id in folders:
            if connection.execute("SELECT 1 FROM folders WHERE parent_folder_id = ? LIMIT 1", (folder_id,)).fetchone():
                raise ValueError(f"Folder {folder_id} is not empty.")
            if connection.execute("SELECT 1 FROM files WHERE folder_id = ? LIMIT 1", (folder_id,)).fetchone():
                raise ValueError(f"Folder {folder_id} is not empty.")

        for note_id in notes:
            if connection.execute("SELECT 1 FROM notes WHERE parent_note_id = ? LIMIT 1", (note_id,)).fetchone():
                raise ValueError(f"Note {note_id} has child notes; move or delete them first.")

        if files:
            placeholders = ",".join("?" for _ in files)
            connection.execute(
                "DELETE FROM tag_assignments WHERE target_type = 'file' AND target_id IN (" + placeholders + ")",
                files,
            )
            connection.execute("DELETE FROM files WHERE id IN (" + placeholders + ")", files)
        if notes:
            placeholders = ",".join("?" for _ in notes)
            connection.execute(
                "DELETE FROM tag_assignments WHERE target_type = 'note' AND target_id IN (" + placeholders + ")",
                notes,
            )
            connection.execute("DELETE FROM notes WHERE id IN (" + placeholders + ")", notes)
        if folders:
            placeholders = ",".join("?" for _ in folders)
            connection.execute(
                "DELETE FROM tag_assignments WHERE target_type = 'folder' AND target_id IN (" + placeholders + ")",
                folders,
            )
            connection.execute("DELETE FROM folders WHERE id IN (" + placeholders + ")", folders)
        connection.commit()
    finally:
        connection.close()


def move_selection(project_id, selection, destination_folder_id=None):
    items = validate_selection(project_id, selection)
    connection = _connection()
    try:
        if destination_folder_id is not None:
            row = connection.execute(
                "SELECT project_id FROM folders WHERE id = ?", (destination_folder_id,)
            ).fetchone()
            if row is None or row[0] != project_id:
                raise ValueError("Destination folder must belong to the same project.")

        for item in items:
            if item["type"] == "file":
                connection.execute(
                    "UPDATE files SET folder_id = ?, updated_at = datetime('now') WHERE id = ?",
                    (destination_folder_id, item["id"]),
                )
            elif item["type"] == "note":
                connection.execute(
                    "UPDATE notes SET folder_id = ?, parent_note_id = NULL, updated_at = datetime('now') WHERE id = ?",
                    (destination_folder_id, item["id"]),
                )
            else:
                if destination_folder_id == item["id"]:
                    raise ValueError("A folder cannot be moved into itself.")
                current = destination_folder_id
                while current is not None:
                    if current == item["id"]:
                        raise ValueError("A folder cannot be moved into itself or its descendants.")
                    row = connection.execute(
                        "SELECT parent_folder_id FROM folders WHERE id = ?", (current,)
                    ).fetchone()
                    current = None if row is None else row[0]
                connection.execute(
                    "UPDATE folders SET parent_folder_id = ?, updated_at = datetime('now') WHERE id = ?",
                    (destination_folder_id, item["id"]),
                )
        connection.commit()
    finally:
        connection.close()
