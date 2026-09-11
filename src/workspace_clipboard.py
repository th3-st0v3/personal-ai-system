"""Workspace copy, paste, and duplicate use cases."""
from __future__ import annotations

from typing import Any, Iterable

import file_storage
import workspace_browser
import workspace_storage



def _unique_name(project_id: int, folder_id: int | None, name: str) -> str:
    connection = workspace_browser._connection()
    try:
        candidate = name
        index = 1
        while True:
            folder_exists = connection.execute(
                "SELECT 1 FROM folders WHERE project_id=? AND folder_id IS ? AND name=? COLLATE NOCASE",
                (project_id, folder_id, candidate),
            ).fetchone()
            file_exists = connection.execute(
                "SELECT 1 FROM files WHERE project_id=? AND folder_id IS ? AND name=? COLLATE NOCASE",
                (project_id, folder_id, candidate),
            ).fetchone()
            note_exists = connection.execute(
                "SELECT 1 FROM workspace_notes WHERE project_id=? AND folder_id IS ? AND title=? COLLATE NOCASE",
                (project_id, folder_id, candidate),
            ).fetchone()
            if not (folder_exists or file_exists or note_exists):
                return candidate
            index += 1
            candidate = f"{name} (copy {index})" if index > 2 else f"{name} (copy)"
    finally:
        connection.close()


def _copy_item(storage_root, project_id: int, kind: workspace_browser.ItemKind, item_id: int, target_folder_id: int | None) -> int:
    if kind == "folder":
        source = workspace_storage.get_folder(item_id)
        if source is None or source[1] != project_id:
            raise ValueError(f"No folder found with ID {item_id} in project {project_id}.")
        new_folder = workspace_storage.create_folder(project_id, _unique_name(project_id, target_folder_id, source[3]), target_folder_id)
        for child in workspace_browser.list_children(project_id, item_id, sort="a_z"):
            _copy_item(storage_root, project_id, child.kind, child.id, new_folder)
        return new_folder

    if kind == "note":
        source = workspace_browser.get_note(item_id)
        if source is None or source.project_id != project_id:
            raise ValueError(f"No note found with ID {item_id} in project {project_id}.")
        return workspace_browser.create_note(project_id, _unique_name(project_id, target_folder_id, source.name), source.content or "", target_folder_id, metadata=source.metadata)

    source = workspace_storage.get_file(item_id)
    if source is None or source[1] != project_id:
        raise ValueError(f"No file found with ID {item_id} in project {project_id}.")
    data = file_storage.read_bytes(storage_root, source[4])
    return workspace_browser.create_file(storage_root, project_id, _unique_name(project_id, target_folder_id, source[3]), data, source[5], target_folder_id)


def duplicate_item(storage_root, project_id: int, kind: workspace_browser.ItemKind, item_id: int) -> int:
    parent_id = None
    if kind == "folder":
        source = workspace_storage.get_folder(item_id)
        if source is None or source[1] != project_id:
            raise ValueError(f"No folder found with ID {item_id} in project {project_id}.")
        parent_id = source[2]
    elif kind == "file":
        source = workspace_storage.get_file(item_id)
        if source is None or source[1] != project_id:
            raise ValueError(f"No file found with ID {item_id} in project {project_id}.")
        parent_id = source[2]
    else:
        source = workspace_browser.get_note(item_id)
        if source is None or source.project_id != project_id:
            raise ValueError(f"No note found with ID {item_id} in project {project_id}.")
        parent_id = source.parent_id
    return _copy_item(storage_root, project_id, kind, item_id, parent_id)


def copy_selection(storage_root, project_id: int, selection: Iterable[tuple[workspace_browser.ItemKind, int]]) -> list[dict[str, Any]]:
    selected = {(kind, int(item_id)) for kind, item_id in selection}
    if any(workspace_browser._item_project(kind, item_id) != project_id for kind, item_id in selected):
        raise ValueError("Selection contains an item from another project.")
    folders = {item_id for kind, item_id in selected if kind == "folder"}
    roots = {folder_id for folder_id in folders if not any(folder_id != other and workspace_browser._folder_contains(project_id, folder_id, other) for other in folders)}
    result = []
    for kind, item_id in sorted(selected):
        if kind == "folder" and item_id not in roots:
            continue
        if kind == "folder":
            row = workspace_storage.get_folder(item_id)
            result.append({"kind": kind, "id": item_id, "name": row[3], "parent_id": row[2]})
        elif kind == "note":
            note = workspace_browser.get_note(item_id)
            result.append({"kind": kind, "id": item_id, "name": note.name, "content": note.content or "", "metadata": note.metadata, "parent_id": note.parent_id})
        else:
            row = workspace_storage.get_file(item_id)
            result.append({"kind": kind, "id": item_id, "name": row[3], "mime_type": row[5], "data": file_storage.read_bytes(storage_root, row[4]), "parent_id": row[2]})
    return result


def paste_selection(storage_root, project_id: int, target_folder_id: int | None, clipboard: Iterable[dict[str, Any]]) -> list[int]:
    if target_folder_id is not None:
        connection = workspace_browser._connection()
        try:
            workspace_storage._require_folder_in_project(connection, target_folder_id, project_id)
        finally:
            connection.close()
    created = []
    for item in clipboard:
        kind = item["kind"]
        if kind == "folder":
            created.append(_copy_item(storage_root, project_id, kind, int(item["id"]), target_folder_id))
        elif kind == "note":
            created.append(workspace_browser.create_note(project_id, _unique_name(project_id, target_folder_id, item["name"]), item.get("content", ""), target_folder_id, metadata=item.get("metadata") or {}))
        elif kind == "file":
            created.append(workspace_browser.create_file(storage_root, project_id, _unique_name(project_id, target_folder_id, item["name"]), item["data"], item.get("mime_type"), target_folder_id))
        else:
            raise ValueError(f"Unsupported clipboard item kind '{kind}'.")
    return created
