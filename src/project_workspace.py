"""Stable application boundary for the project's browsable workspace.

The frontend can treat this module as the source of truth for project
navigation without coupling itself to SQLite rows. It intentionally returns
entity types, lifecycle state, location, and available actions separately.
"""

import db
import engineering_schema
import workspace_notes
import workspace_storage


SORTS = {
    "name_asc",
    "name_desc",
    "created_desc",
    "created_asc",
    "modified_desc",
    "modified_asc",
}

PROJECT_TOOLS = (
    "folders",
    "notes",
    "files",
    "calculations",
    "requirements",
    "evidence",
    "sources",
    "wells",
    "design_cases",
    "decisions",
    "reviews",
)


def _connection():
    connection = db.get_connection()
    engineering_schema.initialize(connection)
    workspace_storage._initialize_schema(connection)
    return connection


def _require_project(connection, project_id):
    row = connection.execute(
        "SELECT id, name, description, created_at, workspace_id, owner_id, status, updated_at "
        "FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No project found with ID {project_id}.")
    return row


def get_project_workspace(project_id):
    connection = _connection()
    try:
        row = _require_project(connection, project_id)
        return {
            "project": {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "created_at": row[3],
                "workspace_id": row[4],
                "owner_id": row[5],
                "status": row[6],
                "updated_at": row[7],
            },
            "tools": list(PROJECT_TOOLS),
        }
    finally:
        connection.close()


def _folder_items(project_id, folder_id, sort):
    rows = workspace_storage.get_folders(project_id, folder_id)
    items = []
    for row in rows:
        items.append(_item("folder", row[0], row[3], row[4], row[5], row[6], folder_id))
    return items


def _file_items(project_id, folder_id, sort):
    rows = workspace_storage.get_files(project_id, folder_id)
    items = []
    for row in rows:
        items.append(_item("file", row[0], row[3], row[8], row[9], row[10], folder_id))
    return items


def _note_items(project_id, folder_id, note_id, sort):
    rows = workspace_notes.list_notes(
        project_id,
        folder_id=folder_id,
        parent_note_id=note_id,
        sort=sort,
    )
    return [
        _item(
            "note",
            row["id"],
            row["title"],
            row["lifecycle_status"],
            row["created_at"],
            row["updated_at"],
            folder_id,
            parent_id=row["parent_note_id"],
        )
        for row in rows
    ]


def _item(item_type, item_id, name, lifecycle_status, created_at, updated_at, parent_id, *, parent_id_override=None, parent_id=None):
    if parent_id_override is not None:
        parent_id = parent_id_override
    return {
        "type": item_type,
        "id": item_id,
        "name": name,
        "lifecycle_status": lifecycle_status,
        "created_at": created_at,
        "updated_at": updated_at,
        "parent_id": parent_id,
        "actions": context_actions(item_type, lifecycle_status),
    }


def _sort_items(items, sort):
    if sort not in SORTS:
        raise ValueError(f"Unsupported sort: {sort}")
    if sort == "name_asc":
        return sorted(items, key=lambda item: (item["name"].casefold(), item["type"], item["id"]))
    if sort == "name_desc":
        return sorted(items, key=lambda item: (item["name"].casefold(), item["type"], item["id"]), reverse=True)
    if sort == "created_desc":
        return sorted(items, key=lambda item: (item["created_at"] or "", item["id"]), reverse=True)
    if sort == "created_asc":
        return sorted(items, key=lambda item: (item["created_at"] or "", item["id"]))
    if sort == "modified_desc":
        return sorted(items, key=lambda item: (item["updated_at"] or item["created_at"] or "", item["id"]), reverse=True)
    return sorted(items, key=lambda item: (item["updated_at"] or item["created_at"] or "", item["id"]))


def list_children(project_id, *, folder_id=None, note_id=None, sort="modified_desc"):
    if folder_id is not None and note_id is not None:
        raise ValueError("A location cannot be both a folder and a note.")
    connection = _connection()
    try:
        _require_project(connection, project_id)
    finally:
        connection.close()

    if note_id is not None:
        return _sort_items(_note_items(project_id, None, note_id, sort), sort)

    items = []
    items.extend(_folder_items(project_id, folder_id, sort))
    items.extend(_file_items(project_id, folder_id))
    items.extend(_note_items(project_id, folder_id, None, sort))
    return _sort_items(items, sort)


def context_actions(item_type, lifecycle_status="Active", selected_count=1):
    if selected_count < 1:
        raise ValueError("selected_count must be at least 1.")
    if item_type == "project":
        actions = ["open", "rename", "archive", "restore", "delete", "new_folder", "new_note", "add_file"]
    elif item_type == "folder":
        actions = ["open", "rename", "move", "tag", "archive", "restore", "invalidate", "delete", "new_folder", "new_note", "add_file"]
    elif item_type == "note":
        actions = ["open", "rename", "move", "tag", "archive", "restore", "invalidate", "delete", "new_child_note"]
    elif item_type == "file":
        actions = ["open", "rename", "move", "tag", "archive", "restore", "invalidate", "delete"]
    elif item_type == "calculation":
        actions = ["open", "rerun", "duplicate", "link_evidence", "archive"]
    elif item_type == "requirement":
        actions = ["open", "edit", "evaluate_evidence", "add_evidence", "archive"]
    else:
        actions = ["open"]

    if selected_count > 1:
        bulk = {"rename", "open", "rerun", "duplicate", "new_child_note"}
        actions = [action for action in actions if action not in bulk]
        actions.extend(["move", "tag", "archive", "restore", "invalidate", "delete"])

    if lifecycle_status == "Archived":
        actions = [action for action in actions if action not in {"archive", "invalidate"}]
    elif lifecycle_status == "Invalidated":
        actions = [action for action in actions if action not in {"archive", "invalidate"}]
    elif lifecycle_status == "Superseded":
        actions = [action for action in actions if action not in {"archive", "invalidate"}]
    else:
        actions = [action for action in actions if action != "restore"]

    return list(dict.fromkeys(actions))
