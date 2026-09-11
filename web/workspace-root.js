"use strict";

const rootProjectId = () => document.querySelector("#projects .nav-item.active")?.dataset.project;
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
    await postWorkspaceRoot(id === "new-root-folder" ? "folders" : "notes", id === "new-root-folder" ? { name: name.trim() } : { title: name.trim() });
    document.getElementById("global-search")?.dispatchEvent(new Event("input", { bubbles: true }));
  } catch (error) { showWorkspaceError(error); }
}));
