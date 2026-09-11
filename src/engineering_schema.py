"""Additive engineering-domain schema extensions.

This module keeps the existing database model backward compatible while adding
stable entities needed by the next application layers. It is intentionally
additive: existing projects, requirements, evidence, and calculation records
remain valid while new relationships can be populated incrementally.
"""

SCHEMA_VERSION = 1


def initialize(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS engineering_schema_version (version INTEGER NOT NULL)"
    )
    row = connection.execute(
        "SELECT version FROM engineering_schema_version LIMIT 1"
    ).fetchone()
    if row is not None and row[0] > SCHEMA_VERSION:
        raise RuntimeError(
            "Engineering schema is newer than this application supports."
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'Active'
                CHECK (status IN ('Active', 'Archived')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'Active'
                CHECK (status IN ('Active', 'Inactive')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (workspace_id, user_id),
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    _add_column_if_missing(
        connection, "projects", "workspace_id", "INTEGER REFERENCES workspaces(id)"
    )
    _add_column_if_missing(
        connection, "projects", "owner_id", "INTEGER REFERENCES users(id)"
    )
    _add_column_if_missing(
        connection, "projects", "status", "TEXT NOT NULL DEFAULT 'Active'"
    )
    # SQLite does not allow a non-constant expression as the default of an
    # ALTER TABLE ... ADD COLUMN migration, so this remains nullable until
    # project writes are migrated to populate it explicitly.
    _add_column_if_missing(
        connection, "projects", "updated_at", "TEXT"
    )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)"
    )

    _add_column_if_missing(connection, "requirements", "identifier", "TEXT")
    _add_column_if_missing(connection, "requirements", "title", "TEXT")
    _add_column_if_missing(
        connection, "requirements", "acceptance_criteria", "TEXT"
    )
    _add_column_if_missing(connection, "requirements", "priority", "TEXT")
    _add_column_if_missing(connection, "requirements", "updated_at", "TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_requirements_project_identifier "
        "ON requirements(project_id, identifier) WHERE identifier IS NOT NULL"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            author TEXT,
            publisher TEXT,
            source_type TEXT NOT NULL,
            version TEXT,
            url TEXT,
            file_id INTEGER,
            checksum TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE SET NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            page TEXT,
            section TEXT,
            figure TEXT,
            table_name TEXT,
            sheet TEXT,
            cell_range TEXT,
            line_reference TEXT,
            location_text TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_locations_source ON evidence_locations(source_id)"
    )

    _add_column_if_missing(
        connection, "evidence", "source_id", "INTEGER REFERENCES sources(id)"
    )
    _add_column_if_missing(connection, "evidence", "classification", "TEXT")
    _add_column_if_missing(connection, "evidence", "description", "TEXT")
    _add_column_if_missing(connection, "evidence", "invalidated_at", "TEXT")
    _add_column_if_missing(
        connection, "evidence", "invalidation_reason", "TEXT"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id)"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            requirement_id INTEGER,
            design_case_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            decision TEXT NOT NULL,
            rationale TEXT,
            status TEXT NOT NULL DEFAULT 'Active'
                CHECK (status IN ('Active', 'Superseded', 'Archived')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (requirement_id) REFERENCES requirements(id),
            FOREIGN KEY (design_case_id) REFERENCES design_cases(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_decisions_requirement ON decisions(requirement_id)"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            reviewer_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Needs Revision')),
            comments TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (reviewer_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_entity ON reviews(entity_type, entity_id)"
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER,
            user_id INTEGER,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_workspace ON audit_events(workspace_id, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, created_at)"
    )

    if row is None or row[0] < SCHEMA_VERSION:
        connection.execute("DELETE FROM engineering_schema_version")
        connection.execute(
            "INSERT INTO engineering_schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
    connection.commit()


def _add_column_if_missing(connection, table_name, column_name, definition):
    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )
