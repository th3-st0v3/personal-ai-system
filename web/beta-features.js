(() => {
  window.openConnections = async function openConnectionsFixed() {
    setView("connections");
    try {
      const [connections, plugins] = await Promise.all([api("/api/connections"), api("/api/plugins")]);
      $("page-view").innerHTML = `<div class="page"><div class="page-head"><div><h1 class="page-title">Connections & plugins</h1><p class="page-subtitle">Explicit provider connections and tool plugins live behind a capability boundary.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid"><div class="page-card"><h3>Information digestion</h3><p>Turn supplied text into key points, claims, qualified statements, and verification questions.</p><button id="open-digest" class="outline-button">Digest text</button></div><div class="page-card"><h3>Connections</h3><p>${connections.length ? connections.map(connection => `${esc(connection.name)} · ${esc(connection.status)}`).join("<br>") : "No provider connections registered."}</p></div><div class="page-card"><h3>Plugins</h3><p>${plugins.length ? plugins.map(plugin => `${esc(plugin.name)} ${esc(plugin.version)} · ${plugin.enabled ? "enabled" : "disabled"}`).join("<br>") : "No plugins registered."}</p></div></div></div>`;
      $("open-digest").onclick = openDigest;
    } catch (error) { showError(error); }
  };

  async function openDigest() {
    modal("Digest information", `<form id="digest-form" class="form-stack"><label>Text<textarea id="digest-input" placeholder="Paste an article, notes, specifications, or source excerpt…" required></textarea></label><div class="form-actions"><button class="primary-button">Digest</button></div></form>`);
    $("digest-form").onsubmit = async event => {
      event.preventDefault();
      try {
        const result = await send("/api/digest", { text: $("digest-input").value });
        $("modal-body").innerHTML = `<div class="properties"><div class="property"><span>Summary</span><strong>${esc(result.summary)}</strong></div><div class="property"><span>Key points</span><strong>${result.key_points.map(esc).join(" ")}</strong></div><div class="property"><span>Claims</span><strong>${result.claims.map(esc).join(" ") || "None extracted."}</strong></div><div class="property"><span>Uncertain or qualified</span><strong>${result.uncertain_or_qualified.map(esc).join(" ") || "None extracted."}</strong></div><div class="property"><span>Open questions</span><strong>${result.open_questions.map(esc).join(" ") || "None identified."}</strong></div><div class="muted">${esc(result.method)}</div></div>`;
      } catch (error) { $("modal-body").insertAdjacentHTML("beforeend", `<div class="error">${esc(error.message)}</div>`); }
    };
  }
})();
