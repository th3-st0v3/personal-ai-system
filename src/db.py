import sqlite3
from pathlib import Path


DATABASE_PATH = str(Path(__file__).resolve().parent.parent / "notes.db")


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    return connection


def initialize_database(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(notes)")
    }

    if "project_id" not in columns:
        connection.execute(
            "ALTER TABLE notes ADD COLUMN project_id INTEGER"
        )

    connection.execute("""
        CREATE TABLE IF NOT EXISTS requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Unverified'
                CHECK (status IN ('Verified', 'Failed', 'Unverified', 'At risk')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            location TEXT,
            result TEXT NOT NULL,
            supports_status TEXT NOT NULL
                CHECK (supports_status IN ('Verified', 'Failed', 'Unverified', 'At risk')),
            lifecycle_status TEXT NOT NULL DEFAULT 'Active'
                CHECK (lifecycle_status IN ('Active', 'Invalidated')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (requirement_id) REFERENCES requirements(id)
        )
    """)

    connection.commit()


def add_note(content, project_id=None, source="user"):
    connection = get_connection()

    connection.execute(
        """
        INSERT INTO notes (content, source, project_id)
        VALUES (?, ?, ?)
        """,
        (content, source, project_id),
    )

    connection.commit()
    connection.close()


def get_notes(project_id=None):
    connection = get_connection()

    if project_id is None:
        notes = connection.execute(
            """
            SELECT id, content, source, created_at, project_id
            FROM notes
            ORDER BY id
            """
        ).fetchall()
    else:
        notes = connection.execute(
            """
            SELECT id, content, source, created_at, project_id
            FROM notes
            WHERE project_id = ?
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()

    connection.close()
    return notes


def search_notes(query, project_id=None):
    connection = get_connection()

    if project_id is None:
        notes = connection.execute(
            """
            SELECT id, content, source, created_at, project_id
            FROM notes
            WHERE content LIKE ?
            ORDER BY id
            """,
            (f"%{query}%",),
        ).fetchall()
    else:
        notes = connection.execute(
            """
            SELECT id, content, source, created_at, project_id
            FROM notes
            WHERE content LIKE ?
              AND project_id = ?
            ORDER BY id
            """,
            (f"%{query}%", project_id),
        ).fetchall()

    connection.close()
    return notes


def create_project(name, description=None):
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO projects (name, description)
        VALUES (?, ?)
        """,
        (name, description),
    )

    connection.commit()
    project_id = cursor.lastrowid
    connection.close()

    return project_id


def get_projects():
    connection = get_connection()

    projects = connection.execute(
        """
        SELECT id, name, description, created_at
        FROM projects
        ORDER BY id
        """
    ).fetchall()

    connection.close()
    return projects


def create_requirement(project_id, description):
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO requirements (project_id, description)
        VALUES (?, ?)
        """,
        (project_id, description),
    )

    connection.commit()
    requirement_id = cursor.lastrowid
    connection.close()

    return requirement_id


def get_requirement(requirement_id):
    connection = get_connection()

    requirement = connection.execute(
        """
        SELECT
            requirements.id,
            requirements.project_id,
            projects.name,
            requirements.description,
            requirements.status,
            requirements.created_at
        FROM requirements
        JOIN projects
            ON requirements.project_id = projects.id
        WHERE requirements.id = ?
        """,
        (requirement_id,),
    ).fetchone()

    connection.close()
    return requirement


def update_requirement_status(requirement_id, status):
    valid_statuses = {
        "Verified",
        "Failed",
        "Unverified",
        "At risk",
    }

    if status not in valid_statuses:
        raise ValueError(
            "Invalid status. Choose Verified, Failed, Unverified, or At risk."
        )

    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE requirements
        SET status = ?
        WHERE id = ?
        """,
        (status, requirement_id),
    )

    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        raise ValueError(
            f"No requirement found with ID {requirement_id}."
        )


def add_evidence(
    requirement_id,
    source,
    result,
    supports_status,
    location=None,
):
    valid_statuses = {
        "Verified",
        "Failed",
        "Unverified",
        "At risk",
    }

    if supports_status not in valid_statuses:
        raise ValueError(
            "Invalid status. Choose Verified, Failed, Unverified, or At risk."
        )

    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO evidence (
            requirement_id,
            source,
            location,
            result,
            supports_status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            requirement_id,
            source,
            location,
            result,
            supports_status,
        ),
    )

    connection.commit()
    evidence_id = cursor.lastrowid
    connection.close()

    return evidence_id


def invalidate_evidence(evidence_id):
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE evidence
        SET lifecycle_status = 'Invalidated'
        WHERE id = ?
          AND lifecycle_status = 'Active'
        """,
        (evidence_id,),
    )

    connection.commit()
    connection.close()

    if cursor.rowcount == 0:
        raise ValueError(
            f"No active evidence found with ID {evidence_id}."
        )


def find_matching_evidence(
    requirement_id,
    source,
    result,
    supports_status,
    location=None,
):
    connection = get_connection()

    matches = connection.execute(
        """
        SELECT
            id,
            requirement_id,
            source,
            location,
            result,
            supports_status,
            created_at
        FROM evidence
        WHERE requirement_id = ?
          AND source = ?
          AND result = ?
          AND supports_status = ?
          AND location IS ?
        ORDER BY id
        """,
        (
            requirement_id,
            source,
            result,
            supports_status,
            location,
        ),
    ).fetchall()

    connection.close()
    return matches


def get_evidence_for_requirement(requirement_id):
    connection = get_connection()

    evidence = connection.execute(
        """
        SELECT
            id,
            requirement_id,
            source,
            location,
            result,
            supports_status,
            created_at
        FROM evidence
        WHERE requirement_id = ?
          AND lifecycle_status = 'Active'
        ORDER BY id
        """,
        (requirement_id,),
    ).fetchall()

    connection.close()
    return evidence


def get_evidence_history_for_requirement(requirement_id):
    connection = get_connection()

    evidence = connection.execute(
        """
        SELECT
            id,
            requirement_id,
            source,
            location,
            result,
            supports_status,
            lifecycle_status,
            created_at
        FROM evidence
        WHERE requirement_id = ?
        ORDER BY id
        """,
        (requirement_id,),
    ).fetchall()

    connection.close()
    return evidence


def evaluate_requirement_evidence(requirement_id):
    evidence = get_evidence_for_requirement(requirement_id)

    if not evidence:
        return {
            "recommendation": "Unverified",
            "signals": [],
            "conflict": False,
        }

    statuses = {item[5] for item in evidence}

    if "Verified" in statuses and "Failed" in statuses:
        return {
            "recommendation": "At risk",
            "signals": sorted(statuses),
            "conflict": True,
        }

    if "Failed" in statuses:
        recommendation = "Failed"
    elif "Verified" in statuses:
        recommendation = "Verified"
    elif "At risk" in statuses:
        recommendation = "At risk"
    else:
        recommendation = "Unverified"

    return {
        "recommendation": recommendation,
        "signals": sorted(statuses),
        "conflict": False,
    }