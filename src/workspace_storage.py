import re
import sqlite3

import db


STORAGE_SCHEMA_VERSION = 1
FILE_LIFECYCLE_STATUSES = {"Active", "Archived", "Invalidated", "Superseded"}
TAG_TARGET_TYPES = {"project", "folder", "file", "well", "design_case", "requirement", "evidence"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_COLUMNS = "id, project_id, folder_id, name, storage_key, mime_type, size_bytes, sha256, lifecycle_status, created_at, updated_at"


def _initialize_schema(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS workspace_storage_schema (version INTEGER NOT NULL)")
    row = connection.execute("SELECT version FROM workspace_storage_schema LIMIT 1").fetchone()
    if row is not None and row[0] > STORAGE_SCHEMA_VERSION:
        raise RuntimeError("Workspace storage schema is newer than this application supports.")
    if row is not None and row[0] == STORAGE_SCHEMA_VERSION:
        return
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        parent_folder_id INTEGER,
        name TEXT NOT NULL,
        lifecycle_status TEXT NOT NULL DEFAULT 'Active' CHECK (lifecycle_status IN ('Active','Archived','Invalidated','Superseded')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(project_id, id),
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (parent_folder_id, project_id) REFERENCES folders(id, project_id) ON DELETE RESTRICT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_project_parent_name ON folders(project_id, COALESCE(parent_folder_id, 0), name);
    CREATE INDEX IF NOT EXISTS idx_folders_project ON folders(project_id);
    CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_folder_id);
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        folder_id INTEGER,
        name TEXT NOT NULL,
        storage_key TEXT NOT NULL UNIQUE,
        mime_type TEXT,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
        lifecycle_status TEXT NOT NULL DEFAULT 'Active' CHECK (lifecycle_status IN ('Active','Archived','Invalidated','Superseded')),
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (folder_id, project_id) REFERENCES folders(id, project_id) ON DELETE RESTRICT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_files_project_folder_name ON files(project_id, COALESCE(folder_id, 0), name);
    CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
    CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_id);
    CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
    CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(file_id, target_type, target_id),
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_attachments_target ON attachments(target_type, target_id);
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(project_id, name),
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );
    CREATE INDEX IF NOT EXISTS idx_tags_project ON tags(project_id);
    CREATE TABLE IF NOT EXISTS tag_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(tag_id, target_type, target_id),
        FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_tag_assignments_target ON tag_assignments(target_type, target_id);
    """)
    connection.execute("DELETE FROM workspace_storage_schema")
    connection.execute("INSERT INTO workspace_storage_schema(version) VALUES (?)", (STORAGE_SCHEMA_VERSION,))
    connection.commit()


def _connection() -> sqlite3.Connection:
    connection = db.get_connection(); _initialize_schema(connection); return connection


def _require_name(name, field="name"):
    if not isinstance(name, str) or not name.strip(): raise ValueError(f"{field} must be a non-empty string.")
    return name.strip()


def _require_lifecycle(status):
    if status not in FILE_LIFECYCLE_STATUSES: raise ValueError("Invalid lifecycle status. Choose Active, Archived, Invalidated, or Superseded.")


def _require_project(connection, project_id):
    if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None: raise ValueError(f"No project found with ID {project_id}.")


def _require_folder_in_project(connection, folder_id, project_id):
    if folder_id is not None and connection.execute("SELECT 1 FROM folders WHERE id=? AND project_id=?", (folder_id,project_id)).fetchone() is None: raise ValueError(f"Folder {folder_id} does not belong to project {project_id}.")


def create_folder(project_id, name, parent_folder_id=None):
    name=_require_name(name); c=_connection()
    try:
        _require_project(c,project_id); _require_folder_in_project(c,parent_folder_id,project_id); cur=c.execute("INSERT INTO folders(project_id,parent_folder_id,name) VALUES(?,?,?)",(project_id,parent_folder_id,name)); c.commit(); return cur.lastrowid
    finally: c.close()


def get_folder(folder_id):
    c=_connection()
    try: return c.execute("SELECT id,project_id,parent_folder_id,name,lifecycle_status,created_at,updated_at FROM folders WHERE id=?",(folder_id,)).fetchone()
    finally: c.close()


def get_folders(project_id=None,parent_folder_id=None):
    c=_connection()
    try:
        if project_id is None: return c.execute("SELECT id,project_id,parent_folder_id,name,lifecycle_status,created_at,updated_at FROM folders ORDER BY id").fetchall()
        if parent_folder_id is None: return c.execute("SELECT id,project_id,parent_folder_id,name,lifecycle_status,created_at,updated_at FROM folders WHERE project_id=? AND parent_folder_id IS NULL ORDER BY id",(project_id,)).fetchall()
        return c.execute("SELECT id,project_id,parent_folder_id,name,lifecycle_status,created_at,updated_at FROM folders WHERE project_id=? AND parent_folder_id=? ORDER BY id",(project_id,parent_folder_id)).fetchall()
    finally: c.close()


def _would_create_folder_cycle(connection,folder_id,new_parent_id):
    seen=set(); current=new_parent_id
    while current is not None:
        if current==folder_id or current in seen: return True
        seen.add(current); row=connection.execute("SELECT parent_folder_id FROM folders WHERE id=?",(current,)).fetchone(); current=None if row is None else row[0]
    return False


def move_folder(folder_id,parent_folder_id=None):
    c=_connection()
    try:
        row=c.execute("SELECT project_id FROM folders WHERE id=?",(folder_id,)).fetchone()
        if row is None: raise ValueError(f"No folder found with ID {folder_id}.")
        _require_folder_in_project(c,parent_folder_id,row[0])
        if _would_create_folder_cycle(c,folder_id,parent_folder_id): raise ValueError("A folder cannot be moved into itself or one of its descendants.")
        c.execute("UPDATE folders SET parent_folder_id=?,updated_at=datetime('now') WHERE id=?",(parent_folder_id,folder_id)); c.commit()
    finally: c.close()


def rename_folder(folder_id,name):
    name=_require_name(name); c=_connection()
    try:
        if c.execute("SELECT 1 FROM folders WHERE id=?",(folder_id,)).fetchone() is None: raise ValueError(f"No folder found with ID {folder_id}.")
        c.execute("UPDATE folders SET name=?,updated_at=datetime('now') WHERE id=?",(name,folder_id)); c.commit()
    finally: c.close()


def delete_folder(folder_id):
    c=_connection()
    try:
        if c.execute("SELECT 1 FROM folders WHERE id=?",(folder_id,)).fetchone() is None: raise ValueError(f"No folder found with ID {folder_id}.")
        if c.execute("SELECT 1 FROM folders WHERE parent_folder_id=? LIMIT 1",(folder_id,)).fetchone() or c.execute("SELECT 1 FROM files WHERE folder_id=? LIMIT 1",(folder_id,)).fetchone(): raise ValueError(f"Folder {folder_id} is not empty.")
        c.execute("DELETE FROM tag_assignments WHERE target_type='folder' AND target_id=?",(folder_id,)); c.execute("DELETE FROM folders WHERE id=?",(folder_id,)); c.commit()
    finally: c.close()


def update_folder_lifecycle_status(folder_id,lifecycle_status):
    _require_lifecycle(lifecycle_status); c=_connection()
    try:
        cur=c.execute("UPDATE folders SET lifecycle_status=?,updated_at=datetime('now') WHERE id=?",(lifecycle_status,folder_id))
        if cur.rowcount==0: raise ValueError(f"No folder found with ID {folder_id}.")
        c.commit()
    finally: c.close()


def create_file(project_id,name,storage_key,size_bytes,sha256,mime_type=None,folder_id=None):
    name=_require_name(name); storage_key=_require_name(storage_key,"storage_key")
    if not isinstance(size_bytes,int) or size_bytes<0: raise ValueError("size_bytes must be a non-negative integer.")
    if not isinstance(sha256,str) or _SHA256_RE.fullmatch(sha256.lower()) is None: raise ValueError("sha256 must be a 64-character hexadecimal SHA-256 digest.")
    c=_connection()
    try:
        _require_project(c,project_id); _require_folder_in_project(c,folder_id,project_id); cur=c.execute("INSERT INTO files(project_id,folder_id,name,storage_key,mime_type,size_bytes,sha256) VALUES(?,?,?,?,?,?,?)",(project_id,folder_id,name,storage_key,mime_type,size_bytes,sha256.lower())); c.commit(); return cur.lastrowid
    finally: c.close()


def get_file(file_id):
    c=_connection()
    try: return c.execute(f"SELECT {_FILE_COLUMNS} FROM files WHERE id=?",(file_id,)).fetchone()
    finally: c.close()


def get_files(project_id=None,folder_id=None):
    c=_connection()
    try:
        if project_id is None: return c.execute(f"SELECT {_FILE_COLUMNS} FROM files ORDER BY id").fetchall()
        if folder_id is None: return c.execute(f"SELECT {_FILE_COLUMNS} FROM files WHERE project_id=? AND folder_id IS NULL ORDER BY id",(project_id,)).fetchall()
        return c.execute(f"SELECT {_FILE_COLUMNS} FROM files WHERE project_id=? AND folder_id=? ORDER BY id",(project_id,folder_id)).fetchall()
    finally: c.close()


def move_file(file_id,folder_id=None):
    c=_connection()
    try:
        row=c.execute("SELECT project_id FROM files WHERE id=?",(file_id,)).fetchone()
        if row is None: raise ValueError(f"No file found with ID {file_id}.")
        _require_folder_in_project(c,folder_id,row[0]); c.execute("UPDATE files SET folder_id=?,updated_at=datetime('now') WHERE id=?",(folder_id,file_id)); c.commit()
    finally: c.close()


def rename_file(file_id,name):
    name=_require_name(name); c=_connection()
    try:
        if c.execute("SELECT 1 FROM files WHERE id=?",(file_id,)).fetchone() is None: raise ValueError(f"No file found with ID {file_id}.")
        c.execute("UPDATE files SET name=?,updated_at=datetime('now') WHERE id=?",(name,file_id)); c.commit()
    finally: c.close()


def update_file_lifecycle_status(file_id,lifecycle_status):
    _require_lifecycle(lifecycle_status); c=_connection()
    try:
        cur=c.execute("UPDATE files SET lifecycle_status=?,updated_at=datetime('now') WHERE id=?",(lifecycle_status,file_id))
        if cur.rowcount==0: raise ValueError(f"No file found with ID {file_id}.")
        c.commit()
    finally: c.close()


def replace_file_record(file_id,storage_key,size_bytes,sha256,mime_type=None):
    storage_key=_require_name(storage_key,"storage_key")
    if not isinstance(size_bytes,int) or size_bytes<0: raise ValueError("size_bytes must be a non-negative integer.")
    if not isinstance(sha256,str) or _SHA256_RE.fullmatch(sha256.lower()) is None: raise ValueError("sha256 must be a 64-character hexadecimal SHA-256 digest.")
    c=_connection()
    try:
        if c.execute("SELECT 1 FROM files WHERE id=?",(file_id,)).fetchone() is None: raise ValueError(f"No file found with ID {file_id}.")
        c.execute("UPDATE files SET storage_key=?,size_bytes=?,sha256=?,mime_type=?,updated_at=datetime('now') WHERE id=?",(storage_key,size_bytes,sha256.lower(),mime_type,file_id)); c.commit()
    finally: c.close()


def delete_file(file_id):
    c=_connection()
    try:
        if c.execute("SELECT 1 FROM files WHERE id=?",(file_id,)).fetchone() is None: raise ValueError(f"No file found with ID {file_id}.")
        c.execute("DELETE FROM tag_assignments WHERE target_type='file' AND target_id=?",(file_id,)); c.execute("DELETE FROM files WHERE id=?",(file_id,)); c.commit()
    finally: c.close()


def delete_files(file_ids):
    ids=list(dict.fromkeys(file_ids))
    if not ids: return
    if any(not isinstance(i,int) for i in ids): raise ValueError("file_ids must contain only integers.")
    c=_connection()
    try:
        p=','.join('?'*len(ids)); found={r[0] for r in c.execute(f"SELECT id FROM files WHERE id IN ({p})",ids).fetchall()}; missing=[i for i in ids if i not in found]
        if missing: raise ValueError(f"No file found with ID {missing[0]}.")
        c.execute(f"DELETE FROM tag_assignments WHERE target_type='file' AND target_id IN ({p})",ids); c.execute(f"DELETE FROM files WHERE id IN ({p})",ids); c.commit()
    finally: c.close()


def create_tag(project_id,name):
    name=_require_name(name); c=_connection()
    try:
        _require_project(c,project_id); cur=c.execute("INSERT INTO tags(project_id,name) VALUES(?,?)",(project_id,name)); c.commit(); return cur.lastrowid
    finally: c.close()


def get_tags(project_id):
    c=_connection()
    try: return c.execute("SELECT id,project_id,name,created_at FROM tags WHERE project_id=? ORDER BY name,id",(project_id,)).fetchall()
    finally: c.close()


def _target_project_id(connection,target_type,target_id):
    if target_type not in TAG_TARGET_TYPES: raise ValueError(f"Unsupported tag target type: {target_type}.")
    queries={"project":("SELECT id FROM projects WHERE id=?",(target_id,)),"folder":("SELECT project_id FROM folders WHERE id=?",(target_id,)),"file":("SELECT project_id FROM files WHERE id=?",(target_id,)),"well":("SELECT project_id FROM wells WHERE id=?",(target_id,)),"design_case":("SELECT project_id FROM design_cases WHERE id=?",(target_id,)),"requirement":("SELECT project_id FROM requirements WHERE id=?",(target_id,)),"evidence":("SELECT requirements.project_id FROM evidence JOIN requirements ON requirements.id=evidence.requirement_id WHERE evidence.id=?",(target_id,))}
    row=connection.execute(*queries[target_type]).fetchone()
    if row is None: raise ValueError(f"No {target_type} found with ID {target_id}.")
    return row[0]


def assign_tag(tag_id,target_type,target_id):
    c=_connection()
    try:
        tag=c.execute("SELECT project_id FROM tags WHERE id=?",(tag_id,)).fetchone()
        if tag is None: raise ValueError(f"No tag found with ID {tag_id}.")
        if _target_project_id(c,target_type,target_id)!=tag[0]: raise ValueError("Tag and target must belong to the same project.")
        cur=c.execute("INSERT INTO tag_assignments(tag_id,target_type,target_id) VALUES(?,?,?)",(tag_id,target_type,target_id)); c.commit(); return cur.lastrowid
    finally: c.close()


def remove_tag(tag_id,target_type,target_id):
    c=_connection()
    try:
        cur=c.execute("DELETE FROM tag_assignments WHERE tag_id=? AND target_type=? AND target_id=?",(tag_id,target_type,target_id))
        if cur.rowcount==0: raise ValueError("Tag assignment not found.")
        c.commit()
    finally: c.close()


def get_tags_for_target(target_type,target_id):
    c=_connection()
    try:
        _target_project_id(c,target_type,target_id); return c.execute("SELECT tags.id,tags.project_id,tags.name,tags.created_at FROM tags JOIN tag_assignments ON tag_assignments.tag_id=tags.id WHERE tag_assignments.target_type=? AND tag_assignments.target_id=? ORDER BY tags.name,tags.id",(target_type,target_id)).fetchall()
    finally: c.close()


def attach_file(file_id,target_type,target_id):
    c=_connection()
    try:
        file_row=c.execute("SELECT project_id FROM files WHERE id=?",(file_id,)).fetchone()
        if file_row is None: raise ValueError(f"No file found with ID {file_id}.")
        if _target_project_id(c,target_type,target_id)!=file_row[0]: raise ValueError("File and attachment target must belong to the same project.")
        cur=c.execute("INSERT INTO attachments(file_id,target_type,target_id) VALUES(?,?,?)",(file_id,target_type,target_id)); c.commit(); return cur.lastrowid
    finally: c.close()


def detach_file(file_id,target_type,target_id):
    c=_connection()
    try:
        cur=c.execute("DELETE FROM attachments WHERE file_id=? AND target_type=? AND target_id=?",(file_id,target_type,target_id))
        if cur.rowcount==0: raise ValueError("Attachment not found.")
        c.commit()
    finally: c.close()


def get_file_attachments(file_id):
    c=_connection()
    try:
        if c.execute("SELECT 1 FROM files WHERE id=?",(file_id,)).fetchone() is None: raise ValueError(f"No file found with ID {file_id}.")
        return c.execute("SELECT id,file_id,target_type,target_id,created_at FROM attachments WHERE file_id=? ORDER BY id",(file_id,)).fetchall()
    finally: c.close()
