"""Project-scoped hierarchical notes for the beta workspace."""

import db
import engineering_schema
import workspace_storage


LIFECYCLE_STATUSES = {"Active", "Archived", "Invalidated", "Superseded"}
SORTS = {
    "name_asc": "COALESCE(title, content) COLLATE NOCASE ASC, id ASC",
    "name_desc": "COALESCE(title, content) COLLATE NOCASE DESC, id DESC",
    "created_desc": "created_at DESC, id DESC",
    "created_asc": "created_at ASC, id ASC",
    "modified_desc": "COALESCE(updated_at, created_at) DESC, id DESC",
    "modified_asc": "COALESCE(updated_at, created_at) ASC, id ASC",
}


def _connection():
    connection = db.get_connection()
    engineering_schema.initialize(connection)
    workspace_storage._initialize_schema(connection)
    return connection


def _require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _require_lifecycle(status):
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(
            "Invalid lifecycle status. Choose Active, Archived, Invalidated, or Superseded."
        )


def _require_project(connection, project_id):
    if connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


def _require_folder(connection, folder_id, project_id):
    if folder_id is None:
        return
    if connection.execute(
        "SELECT id FROM folders WHERE id = ? AND project_id = ?",
        (folder_id, project_id),
    ).fetchone() is None:
        raise ValueError(f"Folder {folder_id} does not belong to project {project_id}.")


def _require_parent_note(connection, note_id, project_id, current_note_id=None):
    if note_id is None:
        return
    if current_note_id is not None and note_id == current_note_id:
        raise ValueError("A note cannot be its own parent.")
    row = connection.execute("SELECT project_id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"No parent note found with ID {note_id}.")
    if row[0] != project_id:
        raise ValueError("Parent note must belong to the same project.")


def _would_create_cycle(connection, note_id, parent_note_id):
    current = parent_note_id
    while current is not None:
        if current == note_id:
            return True
        row = connection.execute("SELECT parent_note_id FROM notes WHERE id = ?", (current,)).fetchone()
        current = None if row is None else row[0]
    return False


def _row(row):
    return {
        "id": row[0],
        "project_id": row[1],
        "folder_id": row[2],
        "parent_note_id": row[3],
        "title": row[4],
        "content": row[5],
        "source": row[6],
        "lifecycle_status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def create_note(project_id, title, content, *, folder_id=None, parent_note_id=None, source="user"):
    title = _require_text(title, "title")
    content = _require_text(content, "content")
    source = _require_text(source, "source")
    if folder_id is not None and parent_note_id is not None:
        raise ValueError("A note may be placed in a folder or inside another note, not both.")

    connection = _connection()
    try:
        _require_project(connection, project_id)
        _require_folder(connection, folder_id, project_id)
        _require_parent_note(connection, parent_note_id, project_id)
        cursor = connection.execute(
            "INSERT INTO notes (project_id, folder_id, parent_note_id, title, content, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (project_id, folder_id, parent_note_id, title, content, source),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_note(note_id):
    connection = _connection()
    try:
        row = connection.execute(
            "SELECT id, project_id, folder_id, parent_note_id, title, content, source, "
            "lifecycle_status, created_at, updated_at FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        return None if row is None else _row(row)
    finally:
        connection.close()


def list_notes(project_id, *, folder_id=None, parent_note_id=None, sort="modified_desc"):
    if sort not in SORTS:
        raise ValueError(f"Unsupported sort: {sort}")
    if folder_id is not None and parent_note_id is not None:
        raise ValueError("A note listing cannot target both a folder and a parent note.")

    connection = _connection()
    try:
        _require_project(connection, project_id)
        _require_folder(connection, folder_id, project_id)
        _require_parent_note(connection, parent_note_id, project_id)
        rows = connection.execute(
            "SELECT id, project_id, folder_id, parent_note_id, title, content, source, "
            "lifecycle_status, created_at, updated_at FROM notes "
            "WHERE project_id = ? AND folder_id IS ? AND parent_note_id IS ? "
            f"ORDER BY {SORTS[sort]}",
            (project_id, folder_id, parent_note_id),
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        connection.close()


def move_note(note_id, *, folder_id=None, parent_note_id=None):
    if folder_id is not None and parent_note_id is not None:
        raise ValueError("A note may be moved to a folder or another note, not both.")

    connection = _connection()
    try:
        row = connection.execute("SELECT project_id FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise ValueError(f"No note found with ID {note_id}.")
        project_id = row[0]
        _require_folder(connection, folder_id, project_id)
        _require_parent_note(connection, parent_note_id, project_id, note_id)
        if _would_create_cycle(connection, note_id, parent_note_id):
            raise ValueError("A note cannot be moved inside itself or one of its descendants.")
        connection.execute(
            "UPDATE notes SET folder_id = ?, parent_note_id = ?, updated_at = datetime('now') WHERE id = ?",
            (folder_id, parent_note_id, note_id),
        )
        connection.commit()
    finally:
        connection.close()


def update_note(note_id, *, title=None, content=None, source=None):
    connection = _connection()
    try:
        if connection.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone() is None:
            raise ValueError(f"No note found with ID {note_id}.")
        updates = []
        values = []
        if title is not None:
            updates.append("title = ?")
            values.append(_require_text(title, "title"))
        if content is not None:
            updates.append("content = ?")
            values.append(_require_text(content, "content"))
        if source is not None:
            updates.append("source = ?")
            values.append(_require_text(source, "source"))
        if not updates:
            raise ValueError("At least one note field must be provided.")
        values.append(note_id)
        connection.execute(
            "UPDATE notes SET " + ", ".join(updates) + ", updated_at = datetime('now') WHERE id = ?",
            values,
        )
        connection.commit()
    finally:
        connection.close()


def update_note_lifecycle_status(note_id, lifecycle_status):
    _require_lifecycle(lifecycle_status)
    connection = _connection()
    try:
        cursor = connection.execute(
            "UPDATE notes SET lifecycle_status = ?, updated_at = datetime('now') WHERE id = ?",
            (lifecycle_status, note_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"No note found with ID {note_id}.")
        connection.commit()
    finally:
        connection.close()


def delete_note(note_id):
    connection = _connection()
    try:
        if connection.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone() is None:
            raise ValueError(f"No note found with ID {note_id}.")
        child = connection.execute("SELECT 1 FROM notes WHERE parent_note_id = ? LIMIT 1", (note_id,)).fetchone()
        if child is not None:
            raise ValueError(f"Note {note_id} has child notes; move or delete them first.")
        connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        connection.commit()
    finally:
        connection.close()


def delete_notes(note_ids):
    note_ids = list(dict.fromkeys(note_ids))
    if not note_ids:
        return
    if any(not isinstance(note_id, int) for note_id in note_ids):
        raise ValueError("note_ids must contain only integers.")

    connection = _connection()
    try:
        placeholders = ",".join("?" for _ in note_ids)
        child = connection.execute(
            "SELECT id FROM notes WHERE parent_note_id IN (" + placeholders + ") LIMIT 1",
            note_ids,
        ).fetchone()
        if child is not None:
            raise ValueError("Bulk note deletion cannot remove notes that still have child notes.")
        connection.execute("DELETE FROM notes WHERE id IN (" + placeholders + ")", note_ids)
        connection.commit()
    finally:
        connection.close()
