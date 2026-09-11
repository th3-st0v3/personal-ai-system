import json
import sqlite3
from pathlib import Path

from calculation_definitions import CALCULATION_DEFINITIONS
from calculation_records import CalculationRecord
from evaluation import evaluate_evidence

DATABASE_PATH = str(Path(__file__).resolve().parent.parent / "notes.db")
SCHEMA_VERSION = 6
LIFECYCLE_STATUSES = {"Active", "Archived", "Invalidated", "Superseded"}


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    return connection


def _table_columns(connection, table_name):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _add_column_if_missing(connection, table_name, column_name, definition):
    if column_name not in _table_columns(connection, table_name):
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _initialize_calculation_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS calculation_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            description TEXT NOT NULL,
            model_type TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS method_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calculation_model_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            equation TEXT NOT NULL,
            description TEXT NOT NULL,
            applicability TEXT NOT NULL,
            assumptions TEXT NOT NULL,
            limitations TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(calculation_model_id, version),
            FOREIGN KEY (calculation_model_id) REFERENCES calculation_models(id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS calculation_parameters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calculation_model_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            data_type TEXT NOT NULL,
            required INTEGER NOT NULL CHECK (required IN (0, 1)),
            dimension TEXT NOT NULL,
            minimum REAL,
            maximum REAL,
            default_unit TEXT,
            UNIQUE(calculation_model_id, name),
            FOREIGN KEY (calculation_model_id) REFERENCES calculation_models(id)
        )
    """)

    _add_column_if_missing(connection, "calculation_records", "calculation_model_id", "INTEGER REFERENCES calculation_models(id)")
    _add_column_if_missing(connection, "calculation_records", "method_version_id", "INTEGER REFERENCES method_versions(id)")
    _add_column_if_missing(connection, "calculation_records", "method_version", "TEXT")

    for model, method, parameters in CALCULATION_DEFINITIONS:
        connection.execute("""
            INSERT INTO calculation_models (key, name, domain, description, model_type)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                domain = excluded.domain,
                description = excluded.description,
                model_type = excluded.model_type
        """, (model.key, model.name, model.domain, model.description, model.model_type))
        model_id = connection.execute(
            "SELECT id FROM calculation_models WHERE key = ?", (model.key,)
        ).fetchone()[0]

        connection.execute("""
            INSERT INTO method_versions (
                calculation_model_id, version, equation, description,
                applicability, assumptions, limitations
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(calculation_model_id, version) DO UPDATE SET
                equation = excluded.equation,
                description = excluded.description,
                applicability = excluded.applicability,
                assumptions = excluded.assumptions,
                limitations = excluded.limitations
        """, (
            model_id, method.version, method.equation, method.description,
            method.applicability, json.dumps(list(method.assumptions)),
            json.dumps(list(method.limitations)),
        ))
        method_id = connection.execute("""
            SELECT id FROM method_versions
            WHERE calculation_model_id = ? AND version = ?
        """, (model_id, method.version)).fetchone()[0]

        for parameter in parameters:
            connection.execute("""
                INSERT INTO calculation_parameters (
                    calculation_model_id, name, description, data_type,
                    required, dimension, minimum, maximum, default_unit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(calculation_model_id, name) DO UPDATE SET
                    description = excluded.description,
                    data_type = excluded.data_type,
                    required = excluded.required,
                    dimension = excluded.dimension,
                    minimum = excluded.minimum,
                    maximum = excluded.maximum,
                    default_unit = excluded.default_unit
            """, (
                model_id, parameter.name, parameter.description,
                parameter.data_type, int(parameter.required), parameter.dimension,
                parameter.minimum, parameter.maximum, parameter.default_unit,
            ))

        connection.execute("""
            UPDATE calculation_records
            SET calculation_model_id = ?, method_version_id = ?, method_version = ?
            WHERE calculation_type = ? AND calculation_model_id IS NULL
        """, (model_id, method_id, method.version, model.key))


def _initialize_engineering_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS wells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            identifier TEXT,
            description TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'Active'
                CHECK (lifecycle_status IN ('Active', 'Archived', 'Invalidated', 'Superseded')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_id, name),
            UNIQUE(id, project_id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wells_project_identifier
        ON wells(project_id, identifier)
        WHERE identifier IS NOT NULL
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_wells_project
        ON wells(project_id)
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS design_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            well_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'Active'
                CHECK (lifecycle_status IN ('Active', 'Archived', 'Invalidated', 'Superseded')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(project_id, name),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (well_id, project_id) REFERENCES wells(id, project_id)
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_design_cases_project
        ON design_cases(project_id)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_design_cases_well
        ON design_cases(well_id)
    """)


def initialize_database(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    version_row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    version = None if version_row is None else version_row[0]
    if version is not None and version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than supported version {SCHEMA_VERSION}."
        )

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
    _add_column_if_missing(connection, "notes", "project_id", "INTEGER")
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
        CREATE TABLE IF NOT EXISTS calculation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calculation_type TEXT NOT NULL,
            inputs TEXT NOT NULL,
            units TEXT NOT NULL,
            assumptions TEXT NOT NULL,
            method TEXT NOT NULL,
            result REAL NOT NULL,
            result_unit TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
            calculation_record_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (requirement_id) REFERENCES requirements(id),
            FOREIGN KEY (calculation_record_id) REFERENCES calculation_records(id)
        )
    """)
    _add_column_if_missing(
        connection, "evidence", "lifecycle_status",
        "TEXT NOT NULL DEFAULT 'Active' CHECK (lifecycle_status IN ('Active', 'Invalidated'))",
    )
    _add_column_if_missing(connection, "evidence", "calculation_record_id", "INTEGER REFERENCES calculation_records(id)")
    _initialize_calculation_schema(connection)
    _initialize_engineering_schema(connection)

    if version is None or version < SCHEMA_VERSION:
        connection.execute("DELETE FROM schema_version")
        connection.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    connection.commit()


def _write(sql, parameters=()):
    connection = get_connection()
    try:
        cursor = connection.execute(sql, parameters)
        connection.commit()
        return cursor.lastrowid, cursor.rowcount
    finally:
        connection.close()


def add_note(content, project_id=None, source="user"):
    _write("INSERT INTO notes (content, source, project_id) VALUES (?, ?, ?)", (content, source, project_id))


def get_notes(project_id=None):
    connection = get_connection()
    try:
        if project_id is None:
            return connection.execute("SELECT id, content, source, created_at, project_id FROM notes ORDER BY id").fetchall()
        return connection.execute("SELECT id, content, source, created_at, project_id FROM notes WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    finally:
        connection.close()


def search_notes(query, project_id=None):
    connection = get_connection()
    try:
        if project_id is None:
            return connection.execute("SELECT id, content, source, created_at, project_id FROM notes WHERE content LIKE ? ORDER BY id", (f"%{query}%",)).fetchall()
        return connection.execute("SELECT id, content, source, created_at, project_id FROM notes WHERE content LIKE ? AND project_id = ? ORDER BY id", (f"%{query}%", project_id)).fetchall()
    finally:
        connection.close()


def create_project(name, description=None):
    return _write("INSERT INTO projects (name, description) VALUES (?, ?)", (name, description))[0]


def get_projects():
    connection = get_connection()
    try:
        return connection.execute("SELECT id, name, description, created_at FROM projects ORDER BY id").fetchall()
    finally:
        connection.close()


def create_requirement(project_id, description):
    return _write("INSERT INTO requirements (project_id, description) VALUES (?, ?)", (project_id, description))[0]


def get_requirement(requirement_id):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT requirements.id, requirements.project_id, projects.name,
                   requirements.description, requirements.status, requirements.created_at
            FROM requirements JOIN projects ON requirements.project_id = projects.id
            WHERE requirements.id = ?
        """, (requirement_id,)).fetchone()
    finally:
        connection.close()


def update_requirement_status(requirement_id, status):
    if status not in {"Verified", "Failed", "Unverified", "At risk"}:
        raise ValueError("Invalid status. Choose Verified, Failed, Unverified, or At risk.")
    _, rowcount = _write("UPDATE requirements SET status = ? WHERE id = ?", (status, requirement_id))
    if rowcount == 0:
        raise ValueError(f"No requirement found with ID {requirement_id}.")


def add_evidence(requirement_id, source, result, supports_status, location=None, calculation_record_id=None):
    if supports_status not in {"Verified", "Failed", "Unverified", "At risk"}:
        raise ValueError("Invalid status. Choose Verified, Failed, Unverified, or At risk.")
    return _write("""
        INSERT INTO evidence (requirement_id, source, location, result, supports_status, calculation_record_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (requirement_id, source, location, result, supports_status, calculation_record_id))[0]


def link_evidence_to_calculation(evidence_id, calculation_id):
    connection = get_connection()
    try:
        if connection.execute("SELECT id FROM calculation_records WHERE id = ?", (calculation_id,)).fetchone() is None:
            raise ValueError(f"No calculation record found with ID {calculation_id}.")
        cursor = connection.execute("UPDATE evidence SET calculation_record_id = ? WHERE id = ?", (calculation_id, evidence_id))
        if cursor.rowcount == 0:
            raise ValueError(f"No evidence found with ID {evidence_id}.")
        connection.commit()
    finally:
        connection.close()


def get_calculation_record_id_for_evidence(evidence_id):
    connection = get_connection()
    try:
        row = connection.execute("SELECT calculation_record_id FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise ValueError(f"No evidence found with ID {evidence_id}.")
        return row[0]
    finally:
        connection.close()


def invalidate_evidence(evidence_id):
    _, rowcount = _write("UPDATE evidence SET lifecycle_status = 'Invalidated' WHERE id = ? AND lifecycle_status = 'Active'", (evidence_id,))
    if rowcount == 0:
        raise ValueError(f"No active evidence found with ID {evidence_id}.")


def find_matching_evidence(requirement_id, source, result, supports_status, location=None):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT id, requirement_id, source, location, result, supports_status,
                   created_at, calculation_record_id
            FROM evidence
            WHERE requirement_id = ? AND source = ? AND result = ?
              AND supports_status = ? AND location IS ? AND lifecycle_status = 'Active'
            ORDER BY id
        """, (requirement_id, source, result, supports_status, location)).fetchall()
    finally:
        connection.close()


def get_evidence_for_requirement(requirement_id):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT id, requirement_id, source, location, result, supports_status,
                   created_at, calculation_record_id
            FROM evidence WHERE requirement_id = ? AND lifecycle_status = 'Active'
            ORDER BY id
        """, (requirement_id,)).fetchall()
    finally:
        connection.close()


def get_evidence_history_for_requirement(requirement_id):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT id, requirement_id, source, location, result, supports_status,
                   lifecycle_status, created_at, calculation_record_id
            FROM evidence WHERE requirement_id = ? ORDER BY id
        """, (requirement_id,)).fetchall()
    finally:
        connection.close()


def evaluate_requirement_evidence(requirement_id):
    return evaluate_evidence(get_evidence_for_requirement(requirement_id))


def _calculation_record_from_row(row):
    return CalculationRecord(
        calculation_type=row[1], inputs=json.loads(row[2]), units=json.loads(row[3]),
        assumptions=json.loads(row[4]), method=row[5], result=row[6],
        result_unit=row[7], source=row[8], method_version=row[9],
    )


def _calculation_rows(connection, where_clause="", parameters=(), order="id"):
    return connection.execute(f"""
        SELECT id, calculation_type, inputs, units, assumptions, method,
               result, result_unit, source, method_version
        FROM calculation_records {where_clause} ORDER BY {order}
    """, parameters).fetchall()


def save_calculation_record(record):
    connection = get_connection()
    try:
        model_row = connection.execute("SELECT id FROM calculation_models WHERE key = ?", (record.calculation_type,)).fetchone()
        model_id = None
        method_id = None
        if model_row is not None:
            model_id = model_row[0]
            version = record.method_version
            if version is None:
                version = connection.execute("""
                    SELECT version FROM method_versions
                    WHERE calculation_model_id = ? ORDER BY id DESC LIMIT 1
                """, (model_id,)).fetchone()[0]
            method_row = connection.execute("""
                SELECT id FROM method_versions
                WHERE calculation_model_id = ? AND version = ?
            """, (model_id, version)).fetchone()
            method_id = None if method_row is None else method_row[0]

        cursor = connection.execute("""
            INSERT INTO calculation_records (
                calculation_type, inputs, units, assumptions, method,
                result, result_unit, source, calculation_model_id,
                method_version_id, method_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.calculation_type, json.dumps(dict(record.inputs)),
            json.dumps(dict(record.units)), json.dumps(list(record.assumptions)),
            record.method, record.result, record.result_unit, record.source,
            model_id, method_id, record.method_version,
        ))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def get_calculation_record(calculation_id):
    connection = get_connection()
    try:
        row = connection.execute("""
            SELECT id, calculation_type, inputs, units, assumptions, method,
                   result, result_unit, source, method_version
            FROM calculation_records WHERE id = ?
        """, (calculation_id,)).fetchone()
        return None if row is None else _calculation_record_from_row(row)
    finally:
        connection.close()


def get_calculation_records():
    connection = get_connection()
    try:
        return [_calculation_record_from_row(row) for row in _calculation_rows(connection)]
    finally:
        connection.close()


def get_calculation_records_by_type(calculation_type):
    connection = get_connection()
    try:
        rows = _calculation_rows(connection, "WHERE calculation_type = ?", (calculation_type,))
        return [_calculation_record_from_row(row) for row in rows]
    finally:
        connection.close()


def get_recent_calculation_records(limit):
    if limit <= 0:
        raise ValueError("limit must be positive")
    connection = get_connection()
    try:
        rows = _calculation_rows(connection, order="id DESC")[:limit]
        return [_calculation_record_from_row(row) for row in rows]
    finally:
        connection.close()


def create_well(project_id, name, identifier=None, description=None):
    return _write(
        "INSERT INTO wells (project_id, name, identifier, description) VALUES (?, ?, ?, ?)",
        (project_id, name, identifier, description),
    )[0]


def get_well(well_id):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT id, project_id, name, identifier, description,
                   lifecycle_status, created_at, updated_at
            FROM wells
            WHERE id = ?
        """, (well_id,)).fetchone()
    finally:
        connection.close()


def get_wells(project_id=None):
    connection = get_connection()
    try:
        if project_id is None:
            return connection.execute("""
                SELECT id, project_id, name, identifier, description,
                       lifecycle_status, created_at, updated_at
                FROM wells ORDER BY id
            """).fetchall()
        return connection.execute("""
            SELECT id, project_id, name, identifier, description,
                   lifecycle_status, created_at, updated_at
            FROM wells WHERE project_id = ? ORDER BY id
        """, (project_id,)).fetchall()
    finally:
        connection.close()


def update_well_lifecycle_status(well_id, lifecycle_status):
    if lifecycle_status not in LIFECYCLE_STATUSES:
        raise ValueError(
            "Invalid lifecycle status. Choose Active, Archived, Invalidated, or Superseded."
        )
    _, rowcount = _write(
        "UPDATE wells SET lifecycle_status = ?, updated_at = datetime('now') WHERE id = ?",
        (lifecycle_status, well_id),
    )
    if rowcount == 0:
        raise ValueError(f"No well found with ID {well_id}.")


def create_design_case(project_id, name, well_id=None, description=None):
    return _write(
        """
        INSERT INTO design_cases (project_id, well_id, name, description)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, well_id, name, description),
    )[0]


def get_design_case(design_case_id):
    connection = get_connection()
    try:
        return connection.execute("""
            SELECT id, project_id, well_id, name, description,
                   lifecycle_status, created_at, updated_at
            FROM design_cases
            WHERE id = ?
        """, (design_case_id,)).fetchone()
    finally:
        connection.close()


def get_design_cases(project_id=None, well_id=None):
    connection = get_connection()
    try:
        if project_id is None and well_id is None:
            return connection.execute("""
                SELECT id, project_id, well_id, name, description,
                       lifecycle_status, created_at, updated_at
                FROM design_cases ORDER BY id
            """).fetchall()
        if project_id is not None and well_id is not None:
            return connection.execute("""
                SELECT id, project_id, well_id, name, description,
                       lifecycle_status, created_at, updated_at
                FROM design_cases
                WHERE project_id = ? AND well_id = ? ORDER BY id
            """, (project_id, well_id)).fetchall()
        if project_id is not None:
            return connection.execute("""
                SELECT id, project_id, well_id, name, description,
                       lifecycle_status, created_at, updated_at
                FROM design_cases
                WHERE project_id = ? ORDER BY id
            """, (project_id,)).fetchall()
        return connection.execute("""
            SELECT id, project_id, well_id, name, description,
                   lifecycle_status, created_at, updated_at
            FROM design_cases
            WHERE well_id = ? ORDER BY id
        """, (well_id,)).fetchall()
    finally:
        connection.close()


def update_design_case_lifecycle_status(design_case_id, lifecycle_status):
    if lifecycle_status not in LIFECYCLE_STATUSES:
        raise ValueError(
            "Invalid lifecycle status. Choose Active, Archived, Invalidated, or Superseded."
        )
    _, rowcount = _write(
        "UPDATE design_cases SET lifecycle_status = ?, updated_at = datetime('now') WHERE id = ?",
        (lifecycle_status, design_case_id),
    )
    if rowcount == 0:
        raise ValueError(f"No design case found with ID {design_case_id}.")
