"""Stable application boundary for project workspace operations."""
import db
import engineering_schema
import file_storage
import workspace_browser
import workspace_clipboard
import workspace_file_service
import workspace_search
import workspace_storage


class WorkspaceApplication:
    """Coordinate workspace use cases without binding the UI to storage details."""

    def __init__(self, storage_root):
        self.storage_root = storage_root
        connection = db.get_connection()
        try:
            workspace_storage._initialize_schema(connection)
            engineering_schema.initialize(connection)
        finally:
            connection.close()

    @staticmethod
    def _project(record): return {"id": record[0], "name": record[1], "description": record[2], "created_at": record[3]}
    @staticmethod
    def _folder(record): return {"id": record[0], "project_id": record[1], "parent_folder_id": record[2], "name": record[3], "lifecycle_status": record[4], "created_at": record[5], "updated_at": record[6]}
    @staticmethod
    def _file(record): return {"id": record[0], "project_id": record[1], "folder_id": record[2], "name": record[3], "storage_key": record[4], "mime_type": record[5], "size_bytes": record[6], "sha256": record[7], "lifecycle_status": record[8], "created_at": record[9], "updated_at": record[10]}
    @staticmethod
    def _tag(record): return {"id": record[0], "project_id": record[1], "name": record[2], "created_at": record[3]}
    @staticmethod
    def _attachment(record): return {"id": record[0], "file_id": record[1], "target_type": record[2], "target_id": record[3], "created_at": record[4]}

    def create_project(self, name, description=None): return db.create_project(name, description)
    def list_projects(self): return [self._project(r) for r in db.get_projects()]
    def create_folder(self, project_id, name, parent_folder_id=None): return workspace_storage.create_folder(project_id, name, parent_folder_id)
    def get_folder(self, folder_id):
        r = workspace_storage.get_folder(folder_id); return None if r is None else self._folder(r)
    def list_folders(self, project_id, parent_folder_id=None): return [self._folder(r) for r in workspace_storage.get_folders(project_id, parent_folder_id)]
    def rename_folder(self, folder_id, name): workspace_storage.rename_folder(folder_id, name)
    def move_folder(self, folder_id, parent_folder_id=None): workspace_storage.move_folder(folder_id, parent_folder_id)
    def set_folder_lifecycle(self, folder_id, lifecycle_status): workspace_storage.update_folder_lifecycle_status(folder_id, lifecycle_status)
    def delete_folder(self, folder_id): workspace_storage.delete_folder(folder_id)
    def create_file(self, project_id, name, data, mime_type=None, folder_id=None): return workspace_file_service.create_file(self.storage_root, project_id, name, data, mime_type, folder_id)
    def get_file(self, file_id):
        r = workspace_storage.get_file(file_id); return None if r is None else self._file(r)
    def list_files(self, project_id, folder_id=None): return [self._file(r) for r in workspace_storage.get_files(project_id, folder_id)]
    def read_file(self, file_id):
        r = workspace_storage.get_file(file_id)
        if r is None: raise ValueError(f"No file found with ID {file_id}.")
        return file_storage.read_bytes(self.storage_root, r[4])
    def verify_file(self, file_id):
        r = workspace_storage.get_file(file_id)
        if r is None: raise ValueError(f"No file found with ID {file_id}.")
        return file_storage.verify_sha256(self.storage_root, r[4], r[7])
    def replace_file(self, file_id, data, mime_type=None): return self._file(workspace_file_service.replace_file(self.storage_root, file_id, data, mime_type))
    def rename_file(self, file_id, name): workspace_storage.rename_file(file_id, name)
    def move_file(self, file_id, folder_id=None): workspace_storage.move_file(file_id, folder_id)
    def set_file_lifecycle(self, file_id, lifecycle_status): workspace_storage.update_file_lifecycle_status(file_id, lifecycle_status)
    def delete_file(self, file_id): return workspace_file_service.delete_file(self.storage_root, file_id)
    def delete_files(self, file_ids): return workspace_file_service.delete_files(self.storage_root, file_ids)

    # Unified project-browser contract: folders + notes + files.
    def create_note(self, project_id, title, content="", folder_id=None, metadata=None): return workspace_browser.create_note(project_id, title, content, folder_id, metadata=metadata)
    def get_note(self, note_id): return workspace_browser.get_note(note_id)
    def update_note(self, note_id, **changes): return workspace_browser.update_note(note_id, **changes)
    def move_note(self, note_id, folder_id=None): return workspace_browser.move_note(note_id, folder_id)
    def delete_note(self, note_id): return workspace_browser.delete_note(note_id)
    def export_note(self, note_id):
        note = workspace_browser.get_note(note_id)
        if note is None: raise ValueError(f"No note found with ID {note_id}.")
        return note.content or ""
    def pin_note(self, note_id, pinned=True):
        note = workspace_browser.get_note(note_id)
        if note is None: raise ValueError(f"No note found with ID {note_id}.")
        metadata = dict(note.metadata); metadata["pinned"] = bool(pinned)
        return workspace_browser.update_note(note_id, metadata=metadata)
    def list_children(self, project_id, folder_id=None, sort="a_z"): return workspace_browser.list_children(project_id, folder_id, sort=sort)
    def list_project_items(self, project_id, recursive=True, sort="a_z"): return workspace_browser.list_project_items(project_id, recursive=recursive, sort=sort)
    def search_project(self, project_id, query, recursive=True): return workspace_search.search_project(project_id, query, recursive=recursive)
    def search_project_names(self, project_id, query): return workspace_search.search_project_names(project_id, query)
    def move_item(self, kind, item_id, target_folder_id=None): return workspace_browser.move_item(kind, item_id, target_folder_id)
    def rename_item(self, kind, item_id, name): return workspace_browser.rename_item(kind, item_id, name)
    def duplicate_item(self, project_id, kind, item_id): return workspace_clipboard.duplicate_item(self.storage_root, project_id, kind, item_id)
    def copy_selection(self, project_id, selection): return workspace_clipboard.copy_selection(self.storage_root, project_id, selection)
    def paste_selection(self, project_id, target_folder_id, clipboard): return workspace_clipboard.paste_selection(self.storage_root, project_id, target_folder_id, clipboard)
    def get_item_properties(self, kind, item_id):
        item = self._browser_item(kind, item_id)
        properties = {"kind": item.kind, "id": item.id, "project_id": item.project_id, "parent_id": item.parent_id, "name": item.name, "created_at": item.created_at, "updated_at": item.updated_at}
        if kind == "file": properties.update({"mime_type": item.mime_type, "size_bytes": item.size_bytes, "sha256": item.metadata.get("sha256"), "lifecycle_status": item.metadata.get("lifecycle_status")})
        elif kind == "note": properties.update({"content_length": len(item.content or ""), "metadata": dict(item.metadata)})
        else: properties["child_count"] = len(workspace_browser.list_children(item.project_id, item.id))
        return properties
    @staticmethod
    def _browser_item(kind, item_id):
        if kind == "folder":
            row = workspace_storage.get_folder(item_id)
            if row is None: raise ValueError(f"No folder found with ID {item_id}.")
            return workspace_browser.BrowserItem("folder", row[0], row[1], row[2], row[3], None, None, None, row[5], row[6], {"lifecycle_status": row[4]})
        item = workspace_browser.get_note(item_id) if kind == "note" else (lambda r: None if r is None else workspace_browser.BrowserItem("file", r[0], r[1], r[2], r[3], r[5], None, r[6], r[9], r[10], {"sha256": r[7], "lifecycle_status": r[8]}))(workspace_storage.get_file(item_id))
        if item is None: raise ValueError(f"No {kind} found with ID {item_id}.")
        return item
    def delete_selection(self, project_id, selection): return workspace_browser.delete_selection(self.storage_root, project_id, selection)
    def delete_all_files(self, project_id, folder_id=None): return workspace_browser.delete_all_files(self.storage_root, project_id, folder_id)
    def get_context_actions(self, kind, selection_count=1): return workspace_browser.get_context_actions(kind, selection_count=selection_count)
    def get_project_context_actions(self): return workspace_browser.project_context_actions()
    def get_breadcrumbs(self, kind, item_id): return workspace_browser.get_breadcrumbs(kind, item_id)

    def create_tag(self, project_id, name): return workspace_storage.create_tag(project_id, name)
    def list_tags(self, project_id): return [self._tag(r) for r in workspace_storage.get_tags(project_id)]
    def assign_tag(self, tag_id, target_type, target_id): return workspace_storage.assign_tag(tag_id, target_type, target_id)
    def remove_tag(self, tag_id, target_type, target_id): workspace_storage.remove_tag(tag_id, target_type, target_id)
    def get_tags_for_target(self, target_type, target_id): return [self._tag(r) for r in workspace_storage.get_tags_for_target(target_type, target_id)]
    def attach_file(self, file_id, target_type, target_id): return workspace_storage.attach_file(file_id, target_type, target_id)
    def detach_file(self, file_id, target_type, target_id): workspace_storage.detach_file(file_id, target_type, target_id)
    def get_file_attachments(self, file_id): return [self._attachment(r) for r in workspace_storage.get_file_attachments(file_id)]


__all__ = ["WorkspaceApplication"]
