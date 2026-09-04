import sqlite3


def get_connection():
    connection = sqlite3.connect("notes.db")

    connection.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'user',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """)
    connection.commit()

    return connection


def add_note(content):
    connection = get_connection()

    connection.execute(
        "INSERT INTO notes (content) VALUES (?)",
        (content,)
    )
    connection.commit()
    connection.close()


def get_notes():
    connection = get_connection()

    notes = connection.execute(
        "SELECT id, content, source, created_at FROM notes ORDER BY id"
    ).fetchall()

    connection.close()

    return notes


def search_notes(query):
    connection = get_connection()

    notes = connection.execute(
        """
        SELECT id, content, source, created_at
        FROM notes
        WHERE content LIKE ?
        ORDER BY id
        """,
        (f"%{query}%",)
    ).fetchall()

    connection.close()

    return notes