"use strict";

const engineeringProjectId = () => document.querySelector("#projects .nav-item.active")?.dataset.project;
const engineeringCatalog = () => document.getElementById("catalog");
const engineeringApi = async (path, options = {}) => {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
};
const engineeringButton = (label, action) => `<button class="calc-card" data-engineering-action="${action}">${escapeHtml(label)}</button>`;
const engineeringPost = (path, payload) => engineeringApi(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

async function showEngineering() {
  const projectId = engineeringProjectId();
  const catalog = engineeringCatalog();
  if (!projectId) throw new Error("Select a project first.");
  try {
    const [requirements, sources, decisions] = await Promise.all([
      engineeringApi(`/api/engineering/projects/${projectId}/requirements`),
      engineeringApi(`/api/engineering/projects/${projectId}/sources`),
      engineeringApi(`/api/engineering/projects/${projectId}/decisions`)
    ]);
    catalog.innerHTML = `<div class="calc-detail"><div class="eyebrow">Engineering</div><h2>Project intelligence</h2><p>Requirements, source provenance, evidence, and decisions remain project-scoped.</p><div class="engineering-actions">${engineeringButton(`New requirement`, "new-requirement")}${engineeringButton(`New source`, "new-source")}${engineeringButton(`New decision`, "new-decision")}${engineeringButton(`Requirements (${requirements.length})`, "requirements")}${engineeringButton(`Sources (${sources.length})`, "sources")}${engineeringButton(`Decisions (${decisions.length})`, "decisions")}</div><div id="engineering-list"></div></div>`;
    renderEngineeringList("requirements", requirements);
  } catch (error) { catalog.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }
}

function renderEngineeringList(kind, items) {
  const target = document.getElementById("engineering-list");
  if (!target) return;
  if (!items.length) { target.innerHTML = `<div class="empty">No ${escapeHtml(kind)} yet.</div>`; return; }
  target.innerHTML = items.map(item => `<article class="property-card"><div><strong>${escapeHtml(item.title || item.name || item.identifier || `${kind} #${item.id}`)}</strong><span>${escapeHtml(item.status || item.source_type || item.decision || "")}</span></div><pre>${escapeHtml(item.description || item.rationale || item.result || "")}</pre></article>`).join("");
}

async function loadEngineeringResource(kind) {
  const projectId = engineeringProjectId();
  if (!projectId) throw new Error("Select a project first.");
  const paths = { requirements: "requirements", sources: "sources", decisions: "decisions" };
  const items = await engineeringApi(`/api/engineering/projects/${projectId}/${paths[kind]}`);
  renderEngineeringList(kind, items);
}

async function createEngineeringResource(kind) {
  const projectId = engineeringProjectId();
  if (!projectId) throw new Error("Select a project first.");
  if (kind === "new-requirement") {
    const description = prompt("Requirement description");
    if (description?.trim()) await engineeringPost(`/api/engineering/projects/${projectId}/requirements`, { description: description.trim() });
  } else if (kind === "new-source") {
    const title = prompt("Source title");
    const sourceType = title && prompt("Source type (paper, datasheet, standard, etc.)");
    if (title?.trim() && sourceType?.trim()) await engineeringPost(`/api/engineering/projects/${projectId}/sources`, { title: title.trim(), source_type: sourceType.trim() });
  } else if (kind === "new-decision") {
    const title = prompt("Decision title");
    const decision = title && prompt("Decision");
    if (title?.trim() && decision?.trim()) await engineeringPost(`/api/engineering/projects/${projectId}/decisions`, { title: title.trim(), decision: decision.trim() });
  }
  return showEngineering();
}

document.addEventListener("click", event => {
  const action = event.target.closest?.("[data-engineering-action]");
  if (!action) return;
  const name = action.dataset.engineeringAction;
  const task = name.startsWith("new-") ? createEngineeringResource(name) : loadEngineeringResource(name);
  task.catch(error => {
    const target = document.getElementById("engineering-list") || engineeringCatalog();
    if (target) target.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  });
});

document.getElementById("engineering-nav")?.addEventListener("click", () => showEngineering().catch(error => { engineeringCatalog().innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`; }));
