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

async function showEngineering() {
  const projectId = engineeringProjectId();
  const catalog = engineeringCatalog();
  if (!projectId) return;
  try {
    const [requirements, sources, decisions] = await Promise.all([
      engineeringApi(`/api/engineering/projects/${projectId}/requirements`),
      engineeringApi(`/api/engineering/projects/${projectId}/sources`),
      engineeringApi(`/api/engineering/projects/${projectId}/decisions`)
    ]);
    catalog.innerHTML = `<div class="calc-detail"><div class="eyebrow">Engineering</div><h2>Project intelligence</h2><p>Requirements, source provenance, evidence, and decisions remain project-scoped.</p><div class="engineering-actions">${engineeringButton(`Requirements (${requirements.length})`, "requirements")}${engineeringButton(`Sources (${sources.length})`, "sources")}${engineeringButton(`Decisions (${decisions.length})`, "decisions")}</div><div id="engineering-list"></div></div>`;
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

document.addEventListener("click", event => {
  const action = event.target.closest?.("[data-engineering-action]");
  if (!action) return;
  loadEngineeringResource(action.dataset.engineeringAction).catch(error => {
    const target = document.getElementById("engineering-list");
    if (target) target.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  });
});

document.addEventListener("DOMContentLoaded", () => {
  const button = document.createElement("button");
  button.className = "nav-item";
  button.type = "button";
  button.textContent = "Engineering";
  button.addEventListener("click", showEngineering);
  document.querySelector(".sidebar .calculations-title")?.insertAdjacentElement("afterend", button);
});
