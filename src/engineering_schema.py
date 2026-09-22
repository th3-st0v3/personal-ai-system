"""Additive engineering-domain schema extensions.

The engineering schema is deliberately additive: existing projects, evidence,
calculations, and users remain compatible while traceability and ingestion
metadata grow around them.
"""

SCHEMA_VERSION = 3
EVIDENCE_TYPES = {"document", "test_result", "calculation", "simulation_run", "manual_entry"}


def _add_column_if_missing(connection, table_name, column_name, definition):
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def initialize(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS engineering_schema_version (version INTEGER NOT NULL)")
    row = connection.execute("SELECT version FROM engineering_schema_version LIMIT 1").fetchone()
    if row is not None and row[0] > SCHEMA_VERSION:
        raise RuntimeError("Engineering schema is newer than this application supports.")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Archived')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            workspace_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (workspace_id, user_id),
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    _add_column_if_missing(connection, "projects", "workspace_id", "INTEGER REFERENCES workspaces(id)")
    _add_column_if_missing(connection, "projects", "owner_id", "INTEGER REFERENCES users(id)")
    _add_column_if_missing(connection, "projects", "status", "TEXT NOT NULL DEFAULT 'Active'")
    _add_column_if_missing(connection, "projects", "updated_at", "TEXT")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")

    for column, definition in (
        ("identifier", "TEXT"),
        ("title", "TEXT"),
        ("acceptance_criteria", "TEXT"),
        ("priority", "TEXT"),
        ("updated_at", "TEXT"),
    ):
        _add_column_if_missing(connection, "requirements", column, definition)
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_requirements_project_identifier ON requirements(project_id, identifier) WHERE identifier IS NOT NULL")

    connection.execute("""
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
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)")

    connection.execute("""
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
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_locations_source ON evidence_locations(source_id)")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS source_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            location_text TEXT,
            checksum TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_id, chunk_index),
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_source_chunks_source ON source_chunks(source_id, chunk_index)")

    _add_column_if_missing(connection, "evidence", "source_id", "INTEGER REFERENCES sources(id)")
    _add_column_if_missing(connection, "evidence", "classification", "TEXT")
    _add_column_if_missing(connection, "evidence", "description", "TEXT")
    _add_column_if_missing(connection, "evidence", "invalidated_at", "TEXT")
    _add_column_if_missing(connection, "evidence", "invalidation_reason", "TEXT")
    _add_column_if_missing(connection, "evidence", "evidence_type", "TEXT NOT NULL DEFAULT 'manual_entry'")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type)")
    connection.execute("""
        UPDATE evidence SET evidence_type = CASE
            WHEN calculation_record_id IS NOT NULL THEN 'calculation'
            ELSE 'manual_entry'
        END
        WHERE evidence_type IS NULL OR evidence_type NOT IN ('document','test_result','calculation','simulation_run','manual_entry')
    """)
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_evidence_calculation_type_insert
        AFTER INSERT ON evidence
        WHEN NEW.calculation_record_id IS NOT NULL
        BEGIN
            UPDATE evidence SET evidence_type = 'calculation' WHERE id = NEW.id;
        END
    """)
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_evidence_calculation_type_update
        AFTER UPDATE OF calculation_record_id ON evidence
        BEGIN
            UPDATE evidence SET evidence_type = CASE
                WHEN NEW.calculation_record_id IS NOT NULL THEN 'calculation'
                WHEN OLD.evidence_type = 'calculation' THEN 'manual_entry'
                ELSE NEW.evidence_type
            END WHERE id = NEW.id;
        END
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            requirement_id INTEGER,
            design_case_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            decision TEXT NOT NULL,
            rationale TEXT,
            status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Superseded', 'Archived')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (requirement_id) REFERENCES requirements(id),
            FOREIGN KEY (design_case_id) REFERENCES design_cases(id)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_decisions_requirement ON decisions(requirement_id)")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            reviewer_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Needs Revision')),
            comments TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (reviewer_id) REFERENCES users(id)
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_reviews_entity ON reviews(entity_type, entity_id)")

    connection.execute("""
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
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_workspace ON audit_events(workspace_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id, created_at)")

    # Requirement history is event-backed at the database boundary so direct
    # SQLite writes and application-service writes cannot silently bypass it.
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_requirement_audit_created
        AFTER INSERT ON requirements
        BEGIN
            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            VALUES (
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_created',
                json_object('description', NEW.description, 'status', NEW.status)
            );
        END
    """)
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_requirement_audit_field_changes
        AFTER UPDATE ON requirements
        BEGIN
            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'project_id', 'old', OLD.project_id, 'new', NEW.project_id)
            WHERE OLD.project_id IS NOT NEW.project_id;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'description', 'old', OLD.description, 'new', NEW.description)
            WHERE OLD.description IS NOT NEW.description;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'status', 'old', OLD.status, 'new', NEW.status)
            WHERE OLD.status IS NOT NEW.status;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'identifier', 'old', OLD.identifier, 'new', NEW.identifier)
            WHERE OLD.identifier IS NOT NEW.identifier;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'title', 'old', OLD.title, 'new', NEW.title)
            WHERE OLD.title IS NOT NEW.title;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'acceptance_criteria', 'old', OLD.acceptance_criteria, 'new', NEW.acceptance_criteria)
            WHERE OLD.acceptance_criteria IS NOT NEW.acceptance_criteria;

            INSERT INTO audit_events (
                workspace_id, entity_type, entity_id, action, metadata
            )
            SELECT
                (SELECT workspace_id FROM projects WHERE id = NEW.project_id),
                'requirement', NEW.id, 'requirement_field_changed',
                json_object('field', 'priority', 'old', OLD.priority, 'new', NEW.priority)
            WHERE OLD.priority IS NOT NEW.priority;
        END
    """)
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_immutable_update
        BEFORE UPDATE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'Audit events are immutable.');
        END
    """)
    connection.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_audit_events_immutable_delete
        BEFORE DELETE ON audit_events
        BEGIN
            SELECT RAISE(ABORT, 'Audit events are immutable.');
        END
    """)

    if row is None or row[0] < SCHEMA_VERSION:
        connection.execute("DELETE FROM engineering_schema_version")
        connection.execute("INSERT INTO engineering_schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    connection.commit()
