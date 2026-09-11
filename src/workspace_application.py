"""Application boundary for workspace operations.

The web UI and future API should depend on this module instead of directly
coupling themselves to SQLite rows or physical storage details.
"""

import db
import engineering_schema
import file_storage
import workspace_file_service
import workspace_storage


class WorkspaceApplication:
    """Coordinate workspace use cases behind a stable application interface."""

    def __init__(self, storage_root):
        self.storage_root = storage_root
        connection = db.get_connection()
        try:
            engineering_schema.initialize(connection)
        finally:
            connection.close()

    @staticmethod
    def _project(record):
        return {
            "id": record[0],
            "name": record[1],
            "description": record[2],
            "created_at": record[3],
        }

    @staticmethod
    def _folder(record):
        return {
            "id": record[0],
            "project_id": record[1],
            "parent_folder_id": record[2],
            "name": record[3],
            "lifecycle_status": record[4],
            "created_at": record[5],
            "updated_at": record[6],
        }

    @staticmethod
    def _file(record):
        return {
            "id": record[0],
            "project_id": record[1],
            "folder_id": record[2],
            "name": record[3],
            "storage_key": record[4],
            "mime_type": record[5],
            "size_bytes": record[6],
            "sha256": record[7],
            "lifecycle_status": record[8],
            "created_at": record[9],
            "updated_at": record[10],
        }

    def create_project(self, name, description=None):
        return db.create_project(name, description)

    def list_projects(self):
        return [self._project(record) for record in db.get_projects()]

    def create_folder(self, project_id, name, parent_folder_id=None):
        return workspace_storage.create_folder(project_id, name, parent_folder_id)

    def get_folder(self, folder_id):
        record = workspace_storage.get_folder(folder_id)
        return None if record is None else self._folder(record)

    def list_folders(self, project_id, parent_folder_id=None):
        return [
            self._folder(record)
            for record in workspace_storage.get_folders(project_id, parent_folder_id)
        ]

    def rename_folder(self, folder_id, name):
        workspace_storage.rename_folder(folder_id, name)

    def move_folder(self, folder_id, parent_folder_id=None):
        workspace_storage.move_folder(folder_id, parent_folder_id)

    def set_folder_lifecycle(self, folder_id, lifecycle_status):
        workspace_storage.update_folder_lifecycle_status(folder_id, lifecycle_status)

    def delete_folder(self, folder_id):
        workspace_storage.delete_folder(folder_id)

    def create_file(self, project_id, name, data, mime_type=None, folder_id=None):
        return workspace_file_service.create_file(
            self.storage_root,
            project_id,
            name,
            data,
            mime_type,
            folder_id,
        )

    def get_file(self, file_id):
        record = workspace_storage.get_file(file_id)
        return None if record is None else self._file(record)

    def list_files(self, project_id, folder_id=None):
        return [
            self._file(record)
            for record in workspace_storage.get_files(project_id, folder_id)
        ]

    def read_file(self, file_id):
        record = workspace_storage.get_file(file_id)
        if record is None:
            raise ValueError(f"No file found with ID {file_id}.")
        return file_storage.read_bytes(self.storage_root, record[4])

    def verify_file(self, file_id):
        record = workspace_storage.get_file(file_id)
        if record is None:
            raise ValueError(f"No file found with ID {file_id}.")
        return file_storage.verify_sha256(
            self.storage_root,
            record[4],
            record[7],
        )

    def rename_file(self, file_id, name):
        workspace_storage.rename_file(file_id, name)

    def move_file(self, file_id, folder_id=None):
        workspace_storage.move_file(file_id, folder_id)

    def set_file_lifecycle(self, file_id, lifecycle_status):
        workspace_storage.update_file_lifecycle_status(file_id, lifecycle_status)

    def delete_file(self, file_id):
        return workspace_file_service.delete_file(self.storage_root, file_id)


__all__ = ["WorkspaceApplication"]
