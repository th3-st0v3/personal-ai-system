"use strict";

const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;
const rootProjectId = () => document.querySelector("#projects .nav-item.active")?.dataset.project;
const currentFolderId = () => { const crumb = document.querySelector("#breadcrumbs .crumb.current[data-breadcrumb-kind='folder']"); return crumb ? Number(crumb.dataset.breadcrumbId) : null; };
const showWorkspaceError = (error) => { const target = document.getElementById("items"); if (target) target.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; };
const postWorkspaceRoot = async (path, payload) => {
  const projectId = rootProjectId();
  if (!projectId) throw new Error("Select a project first.");
  const response = await fetch(`/api/projects/${projectId}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
};

["new-root-folder", "new-root-note"].forEach(id => document.getElementById(id)?.addEventListener("click", async () => {
  try {
    const name = prompt(id === "new-root-folder" ? "Folder name" : "Note title");
    if (!name?.trim()) return;
    await postWorkspaceRoot(id === "new-root-folder" ? "folders" : "notes", id === "new-root-folder" ? { name: name.trim(), parent_folder_id: currentFolderId() } : { title: name.trim(), folder_id: currentFolderId() });
    document.getElementById("global-search")?.dispatchEvent(new Event("input", { bubbles: true }));
  } catch (error) { showWorkspaceError(error); }
}));

document.getElementById("upload-file")?.addEventListener("click", () => document.getElementById("file-upload-input")?.click());
document.getElementById("file-upload-input")?.addEventListener("change", async event => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  try {
    const projectId = rootProjectId();
    if (!projectId) throw new Error("Select a project first.");
    if (file.size > MAX_UPLOAD_BYTES) throw new Error("Files must be 4 MB or smaller in the draft beta.");
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    const response = await fetch(`/api/projects/${projectId}/files`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: file.name, mime_type: file.type || "application/octet-stream", folder_id: currentFolderId(), data_base64: btoa(binary) }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Upload failed");
    document.getElementById("global-search")?.dispatchEvent(new Event("input", { bubbles: true }));
  } catch (error) { showWorkspaceError(error); }
});
