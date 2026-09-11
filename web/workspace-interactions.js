"use strict";

const interactionProjectId = () => document.querySelector("#projects .nav-item.active")?.dataset.project;
const interactionFolderId = () => {
  const crumb = document.querySelector("#breadcrumbs .crumb.current[data-breadcrumb-kind='folder']");
  return crumb ? Number(crumb.dataset.breadcrumbId) : null;
};
const interactionError = error => {
  const target = document.getElementById("catalog") || document.getElementById("items");
  if (target) target.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
};
const interactionApi = async (path, options = {}) => {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
};

async function editNote(noteId) {
  const projectId = interactionProjectId();
  if (!projectId) throw new Error("Select a project first.");
  const note = await interactionApi(`/api/projects/${projectId}/notes?id=${noteId}`);
  const catalog = document.getElementById("catalog");
  catalog.innerHTML = `<div class="calc-detail"><div class="eyebrow">Note</div><form id="note-form"><label>Title<input name="title" value="${escapeAttr(note.name)}" required></label><label>Content<textarea name="content" rows="16">${escapeHtml(note.content || "")}</textarea></label><button class="button" type="submit">Save note</button></form></div>`;
  document.getElementById("note-form").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const form = new FormData(event.target);
      const saved = await interactionApi(`/api/projects/${projectId}/notes`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: Number(noteId), title: form.get("title"), content: form.get("content") }) });
      catalog.innerHTML = `<div class="property-card"><div class="eyebrow">Note</div><h2>${escapeHtml(saved.name)}</h2><pre>${escapeHtml(saved.content || "")}</pre></div>`;
    } catch (error) { interactionError(error); }
  });
}

async function downloadFile(fileId) {
  const projectId = interactionProjectId();
  if (!projectId) throw new Error("Select a project first.");
  const file = await interactionApi(`/api/projects/${projectId}/files?id=${fileId}`);
  const binary = atob(file.data_base64);
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: file.mime_type || "application/octet-stream" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

document.addEventListener("dblclick", event => {
  const item = event.target.closest?.("#items .item");
  if (!item || item.dataset.kind === "folder") return;
  event.preventDefault();
  event.stopImmediatePropagation();
  const action = item.dataset.kind === "note" ? editNote : downloadFile;
  action(Number(item.dataset.id)).catch(interactionError);
}, true);
