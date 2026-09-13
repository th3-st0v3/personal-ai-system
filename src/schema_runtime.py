"""Single application-level schema bootstrap boundary.

Core relational schema remains owned by ``db.initialize_database``. All
feature schemas outside that core are initialized exactly once from this
module during application startup. Service methods do not call schema setup
as a hidden side effect.
"""
from __future__ import annotations

import sqlite3

import auth_service
import chat_service
import engineering_schema
import policy
import workspace_storage


def initialize_application_schema(connection: sqlite3.Connection) -> None:
    """Initialize all non-core application schemas in dependency order."""
    auth_service.initialize(connection)
    # Engineering schema intentionally extends the shared users/projects
    # tables, so it follows authentication's base user shape.
    engineering_schema.initialize(connection)
    workspace_storage._initialize_schema(connection)
    chat_service.initialize(connection)
    policy.initialize(connection)
    connection.commit()


__all__ = ["initialize_application_schema"]
