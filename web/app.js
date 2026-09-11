const state = { projectId: null, folderId: null, category: null, drag: null, selected: new Set(), manifest: null };
const $ = (id) => document.getElementById(id);
const api = async (path, options = {}) => { const response = await fetch(path, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Request failed"); return data; };
const send = (path, payload) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
const selectedItems = () => [...state.selected].map(token => { const [kind, id] = token.split(":"); return { kind, id: Number(id) }; });

function applyManifest() {
  const sort = $("sort");
  sort.innerHTML = state.manifest.workspace.sort_options.map(value => `<option value="${value}">${sortLabel(value)}</option>`).join("");
}
function sortLabel(value) { return ({ a_z: "A–Z", z_a: "Z–A", recent_old: "Recent → old", old_recent: "Old → recent", last_modified_new_old: "Modified → old", last_modified_old_new: "Old → modified" })[value] || value; }
async function loadProjects() {
  const projects = await api("/api/projects");
  $("projects").innerHTML = projects.map(p => `<button class="nav-item ${p.id === state.projectId ? "active" : ""}" data-project="${p.id}">${escapeHtml(p.name)}</button>`).join("") || `<div class="muted">No projects yet.</div>`;
  if (state.projectId === null && projects.length) await selectProject(projects[0].id);
}
async function selectProject(id) { state.projectId = Number(id); state.folderId = null; state.selected.clear(); $("project-name").textContent = "Project"; await refreshWorkspace(); await loadProjects(); }
async function refreshWorkspace() {
  if (!state.projectId) return;
  const params = new URLSearchParams({ sort: $("sort").value }); if (state.folderId) params.set("folder_id", state.folderId);
  state.items = await api(`/api/projects/${state.projectId}/items?${params}`); $("location").textContent = state.folderId ? "Folder" : "Workspace"; renderItems(state.items); renderBreadcrumbs();
}
function renderItems(items) {
  $("items").innerHTML = items.length ? items.map(item => `<article class="item ${item.kind} ${state.selected.has(`${item.kind}:${item.id}`) ? "selected" : ""}" draggable="true" data-kind="${item.kind}" data-id="${item.id}"><span class="item-icon" aria-hidden="true">${item.kind === "folder" ? "▰" : item.kind === "note" ? "▤" : "□"}</span><span class="item-name">${escapeHtml(item.name)}</span><span class="item-meta">${item.kind}</span></article>`).join("") : `<div class="empty"><strong>This workspace is empty</strong><span>Create a folder or note to begin.</span></div>`;
}
function renderBreadcrumbs() { $("breadcrumbs").innerHTML = `<button data-root class="crumb">Project</button>` + (state.folderId ? `<span>›</span><span class="crumb current">Folder</span>` : ""); }
async function loadCategories() {
  const groups = await api("/api/calculations/categories"); $("categories").innerHTML = Object.keys(groups).map(name => `<button class="nav-item ${state.category === name ? "active" : ""}" data-category="${escapeAttr(name)}">${escapeHtml(name)}<span>${groups[name].length}</span></button>`).join("");
}
async function loadCatalog(category) {
  state.category = category; const items = await api(`/api/calculations/catalog?category=${encodeURIComponent(category)}`); $("categories").querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.category === category)); $("catalog").innerHTML = items.map(item => `<button class="calc-card" data-calculation="${item.key}"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.subcategories.join(" · "))}</span><code>${escapeHtml(item.equation)}</code></button>`).join("") || `<div class="muted">No calculations match this category.</div>`;
}
async function searchProject(query) { if (!state.projectId) return; if (!query.trim()) return refreshWorkspace(); renderItems(await api(`/api/projects/${state.projectId}/search?q=${encodeURIComponent(query)}`)); }
async function showMenu(item, x, y) {
  const multi = state.selected.size > 1 && state.selected.has(`${item.kind}:${item.id}`);
  const advertised = multi ? state.manifest.workspace.multi_selection_actions : state.manifest.workspace.context_actions[item.kind];
  const labels = { open: "Open", new_note: "New note", new_folder: "New folder", rename: "Rename", properties: "Properties", delete: "Delete", copy: "Copy", move: "Move", duplicate: "Duplicate", export: "Export", pin: "Pin", preview: "Preview", download: "Download", replace: "Replace", upload_file: "Upload file", paste: "Paste", sort: "Sort", delete_all_files: "Delete all files", edit: "Edit" };
  const actions = advertised.filter(action => ["open","new_note","new_folder","rename","properties","delete"].includes(action));
  $("menu").innerHTML = actions.map(action => `<button data-action="${action}" data-kind="${item.kind}" data-id="${item.id}">${labels[action] || action}${multi && action === "delete" ? ` (${state.selected.size})` : ""}</button>`).join("");
  $("menu").style.left = `${Math.min(x, innerWidth - 200)}px`; $("menu").style.top = `${Math.min(y, innerHeight - Math.max(actions.length,1) * 42)}px`; $("menu").hidden = false;
}
async function openItem(kind, id) {
  if (kind === "folder") { state.folderId = Number(id); state.selected.clear(); return refreshWorkspace(); }
  if (kind === "note") { const note = await api(`/api/projects/${state.projectId}/notes?id=${id}`); $("catalog").innerHTML = `<div class="property-card"><div class="eyebrow">Note</div><h2>${escapeHtml(note.name)}</h2><pre>${escapeHtml(note.content || "")}</pre></div>`; }
  if (kind === "file") { const props = await api(`/api/projects/${state.projectId}/properties?kind=file&id=${id}`); $("catalog").innerHTML = `<div class="property-card"><div class="eyebrow">File</div><h2>${escapeHtml(props.name)}</h2><div><span>Size</span><strong>${props.size_bytes} bytes</strong></div><div><span>Type</span><strong>${escapeHtml(props.mime_type || "unknown")}</strong></div></div>`; }
}
async function handleAction(action, kind, id) {
  if (action === "open") return openItem(kind, id);
  if (action === "new_note") { const title = prompt("Note title"); if (title) await send(`/api/projects/${state.projectId}/notes`, { title, folder_id: Number(id) }); return refreshWorkspace(); }
  if (action === "new_folder") { const name = prompt("Folder name"); if (name) await send(`/api/projects/${state.projectId}/folders`, { name, parent_folder_id: Number(id) }); return refreshWorkspace(); }
  if (action === "rename") { const name = prompt("New name"); if (name) await send(`/api/projects/${state.projectId}/rename`, { kind, id: Number(id), name }); return refreshWorkspace(); }
  if (action === "delete") { const selection = state.selected.size > 1 && state.selected.has(`${kind}:${id}`) ? selectedItems() : [{ kind, id: Number(id) }]; if (confirm(`Delete ${selection.length} item${selection.length === 1 ? "" : "s"}?`)) { await send(`/api/projects/${state.projectId}/delete`, { selection }); state.selected.clear(); } return refreshWorkspace(); }
  if (action === "properties") { const props = await api(`/api/projects/${state.projectId}/properties?kind=${kind}&id=${id}`); $("catalog").innerHTML = `<div class="property-card"><div class="eyebrow">${escapeHtml(props.kind)}</div><h2>${escapeHtml(props.name)}</h2>${Object.entries(props).filter(([key]) => !["kind","name"].includes(key)).map(([key,value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : value)}</strong></div>`).join("")}</div>`; }
}
async function openCalculation(key) {
  const detail = await api(`/api/calculations/${key}`); const { model, method, parameters } = detail;
  $("catalog").innerHTML = `<div class="calc-detail"><div class="eyebrow">${escapeHtml(model.domain)}</div><h2>${escapeHtml(model.name)}</h2><code>${escapeHtml(method.equation)}</code><p>${escapeHtml(model.description)}</p><form id="calc-form">${parameters.map(p => `<label>${escapeHtml(p.name)}<input name="${escapeAttr(p.name)}" type="number" step="any" required placeholder="${escapeAttr(p.default_unit || "value")}"><span>${escapeHtml(p.description)}</span></label>`).join("")}<button class="button" type="submit">Calculate</button></form><div id="calc-result"></div></div>`;
  $("calc-form").addEventListener("submit", async event => { event.preventDefault(); try { const inputs = Object.fromEntries([...new FormData(event.target)].map(([name, value]) => [name, Number(value)])); const trace = await send("/api/calculations/run", { model_key: key, inputs }); $("calc-result").innerHTML = `<div class="result"><strong>${trace.result} ${escapeHtml(trace.result_unit)}</strong><ol>${trace.steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ol>${trace.assumptions.length ? `<h3>Assumptions</h3><ul>${trace.assumptions.map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}${trace.limitations.length ? `<h3>Limitations</h3><ul>${trace.limitations.map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}</div>`; } catch (error) { $("calc-result").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; } });
}
function escapeHtml(value) { return String(value).replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function escapeAttr(value) { return escapeHtml(value).replace(/'/g, "&#39;"); }

document.addEventListener("click", async event => {
  try {
    const project = event.target.closest("[data-project]"); if (project) return selectProject(project.dataset.project);
    const category = event.target.closest("[data-category]"); if (category) return loadCatalog(category.dataset.category);
    if (event.target.closest("[data-root]")) { state.folderId = null; state.selected.clear(); return refreshWorkspace(); }
    const calc = event.target.closest("[data-calculation]"); if (calc) return openCalculation(calc.dataset.calculation);
    const menuAction = event.target.closest("#menu [data-action]"); if (menuAction) { $("menu").hidden = true; return handleAction(menuAction.dataset.action, menuAction.dataset.kind, menuAction.dataset.id); }
    const item = event.target.closest(".item"); if (item) { const token = `${item.dataset.kind}:${item.dataset.id}`; if (event.ctrlKey || event.metaKey) { state.selected.has(token) ? state.selected.delete(token) : state.selected.add(token); } else { state.selected.clear(); state.selected.add(token); } renderItems(state.items); }
  } catch (error) { $("items").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
  if (!event.target.closest("#menu") && !event.target.closest(".item")) $("menu").hidden = true;
});
$("new-project").addEventListener("click", async () => { try { const name = prompt("Project name"); if (!name) return; await send("/api/projects", { name }); await loadProjects(); } catch (error) { $("items").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; } });
$("sort").addEventListener("change", refreshWorkspace);
$("global-search").addEventListener("input", event => searchProject(event.target.value));
$("items").addEventListener("contextmenu", event => { const item = event.target.closest(".item"); if (item) { event.preventDefault(); showMenu({ kind: item.dataset.kind, id: item.dataset.id }, event.clientX, event.clientY); } });
$("items").addEventListener("dragstart", event => { const item = event.target.closest(".item"); if (item) { state.drag = { kind: item.dataset.kind, id: Number(item.dataset.id) }; event.dataTransfer.effectAllowed = "move"; item.classList.add("dragging"); } });
$("items").addEventListener("dragend", event => event.target.closest(".item")?.classList.remove("dragging"));
$("items").addEventListener("dragover", event => { const folder = event.target.closest(".folder"); if (folder) { event.preventDefault(); folder.classList.add("drop-target"); } });
$("items").addEventListener("dragleave", event => event.target.closest(".folder")?.classList.remove("drop-target"));
$("items").addEventListener("drop", async event => { const folder = event.target.closest(".folder"); if (!folder || !state.drag) return; event.preventDefault(); folder.classList.remove("drop-target"); await send(`/api/projects/${state.projectId}/move`, { ...state.drag, target_folder_id: Number(folder.dataset.id) }); state.drag = null; state.selected.clear(); await refreshWorkspace(); });
$("items").addEventListener("dblclick", async event => { const item = event.target.closest(".item"); if (item) await openItem(item.dataset.kind, item.dataset.id); });
(async function init() { try { state.manifest = await api("/api/manifest"); applyManifest(); await Promise.all([loadProjects(), loadCategories()]); } catch (error) { $("items").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; } })();
