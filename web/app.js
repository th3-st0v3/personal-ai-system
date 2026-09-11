const state = { projectId: null, folderId: null, category: null, items: [], drag: null };
const $ = (id) => document.getElementById(id);
const api = async (path, options = {}) => { const response = await fetch(path, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || "Request failed"); return data; };

async function loadProjects() {
  const projects = await api("/api/projects");
  $("projects").innerHTML = projects.map(p => `<button class="nav-item ${p.id === state.projectId ? "active" : ""}" data-project="${p.id}">${escapeHtml(p.name)}</button>`).join("") || `<div class="muted">No projects yet.</div>`;
  if (state.projectId === null && projects.length) selectProject(projects[0].id);
}
async function selectProject(id) { state.projectId = Number(id); state.folderId = null; $("project-name").textContent = "Project"; await refreshWorkspace(); await loadProjects(); }
async function refreshWorkspace() {
  if (!state.projectId) return;
  const params = new URLSearchParams({ sort: $("sort").value }); if (state.folderId) params.set("folder_id", state.folderId);
  state.items = await api(`/api/projects/${state.projectId}/items?${params}`);
  $("location").textContent = state.folderId ? (state.items[0]?.parent_id ? "Folder" : "Folder") : "Workspace";
  renderItems(state.items); renderBreadcrumbs();
}
function renderItems(items) {
  $("items").innerHTML = items.length ? items.map(item => `<article class="item ${item.kind}" draggable="true" data-kind="${item.kind}" data-id="${item.id}"><span class="item-icon" aria-hidden="true">${item.kind === "folder" ? "▰" : item.kind === "note" ? "▤" : "□"}</span><span class="item-name">${escapeHtml(item.name)}</span><span class="item-meta">${item.kind}</span></article>`).join("") : `<div class="empty"><strong>This workspace is empty</strong><span>Create a folder, note, or upload a file to begin.</span></div>`;
}
function renderBreadcrumbs() { $("breadcrumbs").innerHTML = `<button data-root class="crumb">Project</button>` + (state.folderId ? `<span>›</span><span class="crumb current">Folder</span>` : ""); }
async function loadCategories() {
  const groups = await api("/api/calculations/categories");
  $("categories").innerHTML = Object.keys(groups).map(name => `<button class="nav-item ${state.category === name ? "active" : ""}" data-category="${escapeAttr(name)}">${escapeHtml(name)}<span>${groups[name].length}</span></button>`).join("");
}
async function loadCatalog(category) {
  state.category = category; const items = await api(`/api/calculations/catalog?category=${encodeURIComponent(category)}`); $("categories").querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.category === category));
  $("catalog").innerHTML = items.map(item => `<button class="calc-card" data-calculation="${item.key}"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.subcategories.join(" · "))}</span><code>${escapeHtml(item.equation)}</code></button>`).join("") || `<div class="muted">No calculations match this category.</div>`;
}
async function searchProject(query) {
  if (!state.projectId) return;
  if (!query.trim()) return refreshWorkspace();
  const items = await api(`/api/projects/${state.projectId}/search?q=${encodeURIComponent(query)}`); renderItems(items);
}
function showMenu(item, x, y) {
  const actions = item.kind === "folder" ? ["Open", "New note", "New folder", "Rename", "Copy", "Move", "Delete"] : item.kind === "note" ? ["Open", "Edit", "Rename", "Copy", "Move", "Export", "Delete"] : ["Preview", "Download", "Rename", "Copy", "Move", "Replace", "Delete"];
  $("menu").innerHTML = actions.map(action => `<button data-action="${action.toLowerCase()}" data-kind="${item.kind}" data-id="${item.id}">${action}</button>`).join("");
  $("menu").style.left = `${Math.min(x, innerWidth - 190)}px`; $("menu").style.top = `${Math.min(y, innerHeight - actions.length * 42)}px`; $("menu").hidden = false;
}
function escapeHtml(value) { return String(value).replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function escapeAttr(value) { return escapeHtml(value).replace(/'/g, "&#39;"); }

document.addEventListener("click", async (event) => {
  const project = event.target.closest("[data-project]"); if (project) return selectProject(project.dataset.project);
  const category = event.target.closest("[data-category]"); if (category) return loadCatalog(category.dataset.category);
  if (event.target.closest("[data-root]")) { state.folderId = null; return refreshWorkspace(); }
  const calc = event.target.closest("[data-calculation]"); if (calc) return openCalculation(calc.dataset.calculation);
  const item = event.target.closest(".item"); if (item) return showMenu({ kind: item.dataset.kind, id: item.dataset.id }, event.clientX, event.clientY);
  if (!event.target.closest("#menu")) $("menu").hidden = true;
});
$("sort").addEventListener("change", refreshWorkspace);
$("global-search").addEventListener("input", event => searchProject(event.target.value));
$("items").addEventListener("dragstart", event => { const item = event.target.closest(".item"); if (item) { state.drag = { kind: item.dataset.kind, id: Number(item.dataset.id) }; event.dataTransfer.effectAllowed = "move"; } });
$("items").addEventListener("dblclick", event => { const item = event.target.closest(".folder"); if (item) { state.folderId = Number(item.dataset.id); refreshWorkspace(); } });
async function openCalculation(key) {
  const catalog = await api(`/api/calculations/catalog`); const item = catalog.find(entry => entry.key === key); if (!item) return;
  const inputs = {}; for (const parameter of item.parameters || []) inputs[parameter.name] = 0;
  $("catalog").innerHTML = `<div class="calc-detail"><div class="eyebrow">${escapeHtml(item.domain)}</div><h2>${escapeHtml(item.name)}</h2><code>${escapeHtml(item.equation)}</code><p>Select this calculation in the full runner to supply its validated inputs.</p></div>`;
}
(async function init() { try { await Promise.all([loadProjects(), loadCategories()]); } catch (error) { $("items").innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; } })();
