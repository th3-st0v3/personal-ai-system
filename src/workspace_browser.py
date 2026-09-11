"""UI-agnostic beta workspace browser contract."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Literal

import db
import workspace_storage
from workspace_file_service import create_file as create_stored_file
from workspace_file_service import delete_file as delete_stored_file
from workspace_file_service import delete_files as delete_stored_files

ItemKind = Literal["folder", "note", "file"]
SORT_ALIASES = {"name_asc":"a_z","name_desc":"z_a","created_new_old":"recent_old","created_old_new":"old_recent","modified_new_old":"last_modified_new_old","modified_old_new":"last_modified_old_new"}
SORT_OPTIONS = {"a_z":"name","z_a":"name","recent_old":"created_at","old_recent":"created_at","last_modified_new_old":"updated_at","last_modified_old_new":"updated_at"}

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


def _connection() -> sqlite3.Connection:
    connection = db.get_connection()
    workspace_storage._initialize_schema(connection)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspace_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            folder_id INTEGER, title TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(folder_id, project_id) REFERENCES folders(id, project_id) ON DELETE RESTRICT
        )""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_notes_parent ON workspace_notes(project_id, folder_id, updated_at)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_notes_sibling_name ON workspace_notes(project_id, folder_id, title COLLATE NOCASE)")
    connection.commit()
    return connection


def _require_project(connection, project_id: int) -> None:
    if connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
        raise ValueError(f"No project found with ID {project_id}.")


def _note(connection, note_id: int) -> BrowserItem | None:
    row = connection.execute("SELECT id, project_id, folder_id, title, content, created_at, updated_at, metadata FROM workspace_notes WHERE id=?", (note_id,)).fetchone()
    return None if row is None else BrowserItem("note", row[0], row[1], row[2], row[3], "text/markdown", row[4], None, row[5], row[6], json.loads(row[7] or "{}"))


def create_note(project_id: int, title: str, content: str = "", folder_id: int | None = None, *, metadata: dict[str, Any] | None = None) -> int:
    title = title.strip()
    if not title: raise ValueError("Note title is required.")
    connection = _connection()
    try:
        _require_project(connection, project_id)
        if folder_id is not None: workspace_storage._require_folder_in_project(connection, folder_id, project_id)
        cursor = connection.execute("INSERT INTO workspace_notes(project_id,folder_id,title,content,metadata) VALUES(?,?,?,?,?)", (project_id,folder_id,title,content,json.dumps(metadata or {},sort_keys=True)))
        connection.commit(); return cursor.lastrowid
    finally: connection.close()


def get_note(note_id: int) -> BrowserItem | None:
    connection = _connection()
    try: return _note(connection, note_id)
    finally: connection.close()


def update_note(note_id: int, *, title: str | None = None, content: str | None = None, metadata: dict[str, Any] | None = None) -> BrowserItem:
    connection = _connection()
    try:
        note = _note(connection,note_id)
        if note is None: raise ValueError(f"No note found with ID {note_id}.")
        updates=[]; params=[]
        if title is not None:
            title=title.strip()
            if not title: raise ValueError("Note title is required.")
            updates += ["title=?"]; params += [title]
        if content is not None: updates += ["content=?"]; params += [content]
        if metadata is not None: updates += ["metadata=?"]; params += [json.dumps(metadata,sort_keys=True)]
        if updates:
            connection.execute(f"UPDATE workspace_notes SET {', '.join(updates)}, updated_at=datetime('now') WHERE id=?", (*params,note_id)); connection.commit()
        return _note(connection,note_id)  # type: ignore[return-value]
    finally: connection.close()


def move_note(note_id: int, folder_id: int | None) -> None:
    connection=_connection()
    try:
        note=_note(connection,note_id)
        if note is None: raise ValueError(f"No note found with ID {note_id}.")
        if folder_id is not None: workspace_storage._require_folder_in_project(connection,folder_id,note.project_id)
        connection.execute("UPDATE workspace_notes SET folder_id=?, updated_at=datetime('now') WHERE id=?",(folder_id,note_id)); connection.commit()
    finally: connection.close()


def delete_note(note_id: int) -> None:
    connection=_connection()
    try:
        if _note(connection,note_id) is None: raise ValueError(f"No note found with ID {note_id}.")
        connection.execute("DELETE FROM workspace_notes WHERE id=?",(note_id,)); connection.commit()
    finally: connection.close()


def list_children(project_id: int, folder_id: int | None = None, *, sort: str = "a_z") -> list[BrowserItem]:
    sort=SORT_ALIASES.get(sort,sort)
    if sort not in SORT_OPTIONS: raise ValueError(f"Unknown sort '{sort}'.")
    connection=_connection()
    try:
        _require_project(connection,project_id)
        folders=[BrowserItem("folder",r[0],r[1],r[2],r[3],None,None,None,r[5],r[6],{}) for r in workspace_storage.get_folders(project_id,folder_id)]
        files=[BrowserItem("file",r[0],r[1],r[2],r[3],r[5],None,r[6],r[9],r[10],{"sha256":r[7],"lifecycle_status":r[8]}) for r in workspace_storage.get_files(project_id,folder_id)]
        notes=[item for row in connection.execute("SELECT id FROM workspace_notes WHERE project_id=? AND folder_id IS ?",(project_id,folder_id)).fetchall() if (item:=_note(connection,row[0])) is not None]
        items=folders+files+notes; field=SORT_OPTIONS[sort]
        if field=="name": return sorted(items,key=lambda x:(x.name.casefold(),x.kind,x.id),reverse=sort=="z_a")
        return sorted(items,key=lambda x:(getattr(x,field),x.id),reverse=sort in {"recent_old","last_modified_new_old"})
    finally: connection.close()


def list_project_items(project_id: int, *, recursive: bool = True, sort: str = "a_z") -> list[BrowserItem]:
    result=[]; queue=[None]
    while queue:
        folder_id=queue.pop(0); children=list_children(project_id,folder_id,sort=sort); result.extend(children)
        if recursive: queue.extend(item.id for item in children if item.kind=="folder")
    return result


def create_file(storage_root, project_id: int, name: str, data: bytes, mime_type: str | None = None, folder_id: int | None = None) -> int:
    return create_stored_file(storage_root,project_id,name,data,mime_type,folder_id)


def move_item(kind: ItemKind, item_id: int, target_folder_id: int | None) -> None:
    {"folder": workspace_storage.move_folder, "file": workspace_storage.move_file, "note": move_note}[kind](item_id,target_folder_id)


def rename_item(kind: ItemKind, item_id: int, name: str) -> None:
    if kind=="folder": workspace_storage.rename_folder(item_id,name)
    elif kind=="file": workspace_storage.rename_file(item_id,name)
    else: update_note(item_id,title=name)


def _folder_descendants(project_id: int, folder_id: int) -> list[int]:
    connection=_connection()
    try:
        return [r[0] for r in connection.execute("WITH RECURSIVE tree(id) AS (SELECT id FROM folders WHERE id=? AND project_id=? UNION ALL SELECT f.id FROM folders f JOIN tree t ON f.parent_folder_id=t.id) SELECT id FROM tree",(folder_id,project_id)).fetchall()]
    finally: connection.close()


def delete_all_files(storage_root, project_id: int, folder_id: int | None = None) -> int:
    folder_ids=_folder_descendants(project_id,folder_id) if folder_id is not None else []
    if folder_id is None: file_ids=[item.id for item in list_project_items(project_id) if item.kind=="file"]
    else: file_ids=[r[0] for fid in folder_ids for r in workspace_storage.get_files(project_id,fid)]
    return delete_stored_files(storage_root,file_ids) if file_ids else 0


def _folder_contains(project_id: int, folder_id: int | None, ancestor_id: int) -> bool:
    current=folder_id
    while current is not None:
        if current==ancestor_id: return True
        row=workspace_storage.get_folder(current)
        if row is None or row[1]!=project_id: return False
        current=row[2]
    return False


def _delete_folder_tree(storage_root, project_id: int, folder_id: int) -> None:
    descendants=_folder_descendants(project_id,folder_id); delete_all_files(storage_root,project_id,folder_id)
    connection=_connection()
    try: note_ids=[r[0] for r in connection.execute(f"SELECT id FROM workspace_notes WHERE project_id=? AND folder_id IN ({','.join('?'*len(descendants))})",(project_id,*descendants)).fetchall()]
    finally: connection.close()
    for note_id in note_ids: delete_note(note_id)
    for fid in reversed(descendants):
        try: workspace_storage.delete_folder(fid)
        except ValueError: pass


def delete_selection(storage_root, project_id: int, selection: Iterable[tuple[ItemKind,int]]) -> int:
    selected=set((kind,int(item_id)) for kind,item_id in selection)
    if any(not _exists(kind,item_id) for kind,item_id in selected): raise ValueError("Selection contains a missing workspace item.")
    folders=[item_id for kind,item_id in selected if kind=="folder"]
    roots=[fid for fid in folders if not any(fid!=other and _folder_contains(project_id,fid,other) for other in folders)]
    deleted=0
    for fid in roots: _delete_folder_tree(storage_root,project_id,fid); deleted+=1
    for kind,item_id in selected:
        if kind=="folder": continue
        if kind=="file":
            row=workspace_storage.get_file(item_id); parent=None if row is None else row[2]
            if any(_folder_contains(project_id,parent,fid) for fid in roots): continue
            delete_stored_file(storage_root,item_id)
        else:
            note=get_note(item_id)
            if note is not None and any(_folder_contains(project_id,note.parent_id,fid) for fid in roots): continue
            delete_note(item_id)
        deleted+=1
    return deleted


def _exists(kind: ItemKind, item_id: int) -> bool:
    return (workspace_storage.get_folder(item_id) is not None if kind=="folder" else workspace_storage.get_file(item_id) is not None if kind=="file" else get_note(item_id) is not None)


def _item_project(kind: ItemKind,item_id: int) -> int:
    if kind=="folder": row=workspace_storage.get_folder(item_id); value=None if row is None else row[1]
    elif kind=="file": row=workspace_storage.get_file(item_id); value=None if row is None else row[1]
    else:
        note=get_note(item_id); value=None if note is None else note.project_id
    if value is None: raise ValueError(f"No {kind} found with ID {item_id}.")
    return value


def get_context_actions(kind: ItemKind, *, selection_count: int=1) -> tuple[str,...]:
    if selection_count>1: return ("open","copy","move","delete","properties")
    if kind=="folder": return ("open","new_folder","new_note","upload_file","paste","sort","rename","duplicate","move","copy","delete","delete_all_files","properties")
    if kind=="note": return ("open","edit","new_note","new_folder","duplicate","move","copy","export","pin","delete","properties")
    return ("open","preview","download","rename","duplicate","move","copy","replace","delete","properties")


def project_context_actions() -> tuple[str,...]:
    return ("open","new_folder","new_note","upload_file","paste","sort","search","delete_all_files","properties")


def get_breadcrumbs(kind: ItemKind,item_id: int) -> list[tuple[str,int,str]]:
    project_id=_item_project(kind,item_id)
    if kind=="folder": folder_id=item_id
    elif kind=="file": folder_id=workspace_storage.get_file(item_id)[2]
    else: folder_id=get_note(item_id).parent_id
    result=[]
    while folder_id is not None:
        folder=workspace_storage.get_folder(folder_id)
        if folder is None: break
        result.append(("folder",folder[0],folder[3])); folder_id=folder[2]
    result.reverse(); return [("project",project_id,"Project")]+result
