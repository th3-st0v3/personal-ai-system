"""Project metadata operations kept separate from filesystem concerns."""
from __future__ import annotations

import sqlite3


def get_project(connection: sqlite3.Connection, project_id: int) -> dict[str, object]:
    row = connection.execute("SELECT id, name, description, created_at FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"No project found with ID {project_id}.")
    return {"id": row[0], "name": row[1], "description": row[2] or "", "created_at": row[3]}


def update_project(connection: sqlite3.Connection, project_id: int, *, name: str | None = None, description: str | None = None) -> dict[str, object]:
    project = get_project(connection, project_id)
    values: list[object] = []
    updates: list[str] = []
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Project name is required.")
        updates.append("name=?")
        values.append(clean_name)
    if description is not None:
        updates.append("description=?")
        values.append(description.strip())
    if updates:
        try:
            connection.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id=?", (*values, project_id))
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("A project with that name already exists.") from exc
    return get_project(connection, project_id)


def delete_project(connection: sqlite3.Connection, project_id: int) -> None:
    get_project(connection, project_id)
    connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
    connection.commit()


__all__ = ["get_project", "update_project", "delete_project"]
