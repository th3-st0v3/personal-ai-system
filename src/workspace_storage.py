


def _target_project_id(connection, target_type, target_id):
    if target_type not in TAG_TARGET_TYPES:
        raise ValueError(f"Unsupported tag target type: {target_type}.")
    queries = {
        "project": ("SELECT id FROM projects WHERE id = ?", (target_id,)),
        "folder": ("SELECT project_id FROM folders WHERE id = ?", (target_id,)),
        "file": ("SELECT project_id FROM files WHERE id = ?", (target_id,)),
        "well": ("SELECT project_id FROM wells WHERE id = ?", (target_id,)),
        "design_case": ("SELECT project_id FROM design_cases WHERE id = ?", (target_id,)),
        "requirement": ("SELECT project_id FROM requirements WHERE id = ?", (target_id,)),
        "evidence": ("SELECT requirements.project_id FROM evidence JOIN requirements ON requirements.id = evidence.requirement_id WHERE evidence.id = ?", (target_id,)),
    }
    row = connection.execute(*queries[target_type]).fetchone()
    if row is None:
        raise ValueError(f"No {target_type} found with ID {target_id}.")
    return row[0]


def assign_tag(tag_id, target_type, target_id):
    connection = _connection()
    try:
        tag = connection.execute("SELECT project_id FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if tag is None: raise ValueError(f"No tag found with ID {tag_id}.")
        if _target_project_id(connection, target_type, target_id) != tag[0]: raise ValueError("Tag and target must belong to the same project.")
        cursor = connection.execute("INSERT INTO tag_assignments (tag_id, target_type, target_id) VALUES (?, ?, ?)", (tag_id, target_type, target_id)); connection.commit(); return cursor.lastrowid
    finally: connection.close()


def remove_tag(tag_id, target_type, target_id):
    connection = _connection()
    try:
        cursor = connection.execute("DELETE FROM tag_assignments WHERE tag_id = ? AND target_type = ? AND target_id = ?", (tag_id, target_type, target_id))
        if cursor.rowcount == 0: raise ValueError("Tag assignment not found.")
        connection.commit()
    finally: connection.close()


def get_tags_for_target(target_type, target_id):
    connection = _connection()
    try:
        _target_project_id(connection, target_type, target_id)
        return connection.execute("SELECT tags.id, tags.project_id, tags.name, tags.created_at FROM tags JOIN tag_assignments ON tag_assignments.tag_id = tags.id WHERE tag_assignments.target_type = ? AND tag_assignments.target_id = ? ORDER BY tags.name, tags.id", (target_type, target_id)).fetchall()
    finally: connection.close()


def attach_file(file_id, target_type, target_id):
    connection = _connection()
    try:
        file_row = connection.execute("SELECT project_id FROM files WHERE id = ?", (file_id,)).fetchone()
        if file_row is None: raise ValueError(f"No file found with ID {file_id}.")
        if _target_project_id(connection, target_type, target_id) != file_row[0]: raise ValueError("File and attachment target must belong to the same project.")
        cursor = connection.execute("INSERT INTO attachments (file_id, target_type, target_id) VALUES (?, ?, ?)", (file_id, target_type, target_id)); connection.commit(); return cursor.lastrowid
    finally: connection.close()


def detach_file(file_id, target_type, target_id):
    connection = _connection()
    try:
        cursor = connection.execute("DELETE FROM attachments WHERE file_id = ? AND target_type = ? AND target_id = ?", (file_id, target_type, target_id))
        if cursor.rowcount == 0: raise ValueError("Attachment not found.")
        connection.commit()
    finally: connection.close()


def get_file_attachments(file_id):
    connection = _connection()
    try:
        if connection.execute("SELECT id FROM files WHERE id = ?", (file_id,)).fetchone() is None: raise ValueError(f"No file found with ID {file_id}.")
        return connection.execute("SELECT id, file_id, target_type, target_id, created_at FROM attachments WHERE file_id = ? ORDER BY id", (file_id,)).fetchall()
    finally: connection.close()
