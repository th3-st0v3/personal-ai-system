(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const attr = (value) => esc(value).replace(/'/g, '&#39;');
  const modelProfile = (value) => ({ auto: 'profile:auto', claude: 'profile:claude-opus', gpt: 'profile:gpt-5.4', gemini: 'profile:gemini-3.1-pro', free: 'profile:free' }[value] || 'profile:auto');
  const toast = (message, ok = false) => {
    if (!ok && typeof window.showError === 'function') return window.showError(new Error(String(message)));
    const node = document.createElement('div');
    node.className = `ui-toast ${ok ? 'ok' : 'error'}`;
    node.textContent = String(message);
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 3200);
  };
  const safe = async (work) => { try { return await work(); } catch (error) { toast(error?.message || error); return null; } };

  const renderSimulationPage = async () => {
    setView('simulations');
    const simulations = await api('/api/simulations');
    $('page-view').innerHTML = `<div class="page"><div class="page-head"><div><h1 class="page-title">Simulations</h1><p class="page-subtitle">Deterministic engineering models with explicit inputs, steps, assumptions, and limitations.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid compact-grid">${simulations.map((sim) => `<article class="page-card simulation-card" data-simulation-key="${attr(sim.key)}"><div class="eyebrow">${esc(sim.discipline)}</div><h3>${esc(sim.name)}</h3><p>${esc(sim.description)}</p><div class="simulation-parameters">${(sim.parameters || []).map((name) => `<label>${esc(name)}<input data-sim-input="${attr(name)}" type="number" step="any" placeholder="value"></label>`).join('')}</div><button type="button" class="primary-button" data-run-simulation>Run simulation</button><div class="simulation-result" data-sim-result></div></article>`).join('')}</div></div>`;
    document.querySelectorAll('[data-run-simulation]').forEach((button) => button.addEventListener('click', async () => {
      const card = button.closest('[data-simulation-key]');
      const inputs = Object.fromEntries([...card.querySelectorAll('[data-sim-input]')].filter((input) => input.value.trim() !== '').map((input) => [input.dataset.simInput, Number(input.value)]));
      const result = await safe(() => send('/api/simulations/run', { simulation_key: card.dataset.simulationKey, inputs }));
      if (!result) return;
      card.querySelector('[data-sim-result]').innerHTML = `<div class="trace"><strong>${esc(result.result ?? result.value ?? '')}</strong><h4>Outputs</h4><pre class="text-preview">${esc(JSON.stringify(result, null, 2))}</pre></div>`;
    }));
  };

  const renderConnectionsPage = async () => {
    setView('connections');
    const [connections, plugins] = await Promise.all([api('/api/connections'), api('/api/plugins')]);
    $('page-view').innerHTML = `<div class="page"><div class="page-head"><div><h1 class="page-title">Connections & plugins</h1><p class="page-subtitle">External capabilities remain explicit, inspectable, and user-controlled.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid"><article class="page-card"><h3>Information digestion</h3><p>Turn supplied text into qualified claims and verification questions.</p><button type="button" class="outline-button" id="bridge-digest">Digest text</button></article><article class="page-card"><div class="page-card-head"><h3>Connections</h3><button type="button" class="quiet-button" id="bridge-add-connection">Add</button></div><div class="properties">${connections.length ? connections.map((item) => `<div class="property"><span>${esc(item.name)} · ${esc(item.provider)}</span><strong>${esc(item.status)}</strong><small>${esc((item.capabilities || []).join(', '))}</small></div>`).join('') : '<div class="empty-state">No connections registered.</div>'}</div></article><article class="page-card"><div class="page-card-head"><h3>Plugins</h3><button type="button" class="quiet-button" id="bridge-add-plugin">Register</button></div><div class="properties">${plugins.length ? plugins.map((item) => `<div class="property"><span>${esc(item.name)} · ${esc(item.version)}</span><strong>${item.enabled ? 'Enabled' : 'Disabled'} <button type="button" class="quiet-button" data-toggle-plugin="${item.id}">${item.enabled ? 'Disable' : 'Enable'}</button></strong><small>${esc((item.capabilities || []).join(', '))}</small></div>`).join('') : '<div class="empty-state">No plugins registered.</div>'}</div></article></div></div>`;
    $('bridge-digest').onclick = typeof openDigest === 'function' ? openDigest : null;
    $('bridge-add-connection').onclick = () => modal('Add connection', `<form id="bridge-connection-form" class="form-stack"><label>Name<input name="name" required></label><label>Provider<input name="provider" required placeholder="openrouter"></label><label>Capabilities<input name="capabilities" placeholder="chat, embeddings"></label><div class="form-actions"><button type="button" class="outline-button" onclick="closeModal()">Cancel</button><button class="primary-button">Save</button></div></form>`);
    $('bridge-add-plugin').onclick = () => modal('Register plugin', `<form id="bridge-plugin-form" class="form-stack"><label>Name<input name="name" required></label><label>Version<input name="version" value="0.1.0"></label><label>Description<input name="description"></label><label>Entrypoint<input name="entrypoint" required placeholder="package.module:main"></label><label>Capabilities<input name="capabilities" placeholder="tool, search"></label><div class="form-actions"><button type="button" class="outline-button" onclick="closeModal()">Cancel</button><button class="primary-button">Register</button></div></form>`);
    $('bridge-connection-form')?.addEventListener('submit', async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.target)); values.capabilities = values.capabilities ? String(values.capabilities).split(',').map((x) => x.trim()).filter(Boolean) : []; await safe(async () => { await send('/api/connections', values); closeModal(); await renderConnectionsPage(); }); });
    $('bridge-plugin-form')?.addEventListener('submit', async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.target)); values.capabilities = values.capabilities ? String(values.capabilities).split(',').map((x) => x.trim()).filter(Boolean) : []; await safe(async () => { await send('/api/plugins', values); closeModal(); await renderConnectionsPage(); }); });
    document.querySelectorAll('[data-toggle-plugin]').forEach((button) => button.addEventListener('click', async () => { await safe(async () => { await send(`/api/plugins/${button.dataset.togglePlugin}/enabled`, { enabled: button.textContent === 'Enable' }); await renderConnectionsPage(); }); }));
  };

  const enhanceSources = () => {
    document.querySelectorAll('.tool-fetch').forEach((button) => {
      if (button.dataset.bridgeBound === '1') return;
      button.dataset.bridgeBound = '1';
      button.textContent = 'fetch source';
      button.addEventListener('click', async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const raw = button.dataset.toolFetch;
        let sources = [];
        try { sources = JSON.parse(raw); } catch { return; }
        const projectId = state.projectId;
        const source = sources[0];
        if (!projectId || !source?.chunk_id) return modal('Source', `<div class="empty-state">Source location is available, but no project chunk ID was returned.</div>`);
        const chunk = await safe(() => api(`/api/engineering/projects/${projectId}/sources/chunks/${source.chunk_id}`));
        if (!chunk) return;
        modal(chunk.source || 'Source', `<div class="source-detail"><div class="property"><span>Location</span><strong>${esc(chunk.location)}</strong></div><div class="property"><span>Version</span><strong>${esc(chunk.version || 'Unversioned')}</strong></div><div class="property"><span>Checksum</span><code>${esc(chunk.checksum)}</code></div><pre class="text-preview">${esc(chunk.content)}</pre></div>`);
      });
    });
    document.querySelectorAll('.message.assistant').forEach((article) => {
      if (article.querySelector('.source-rail')) return;
      const buttons = [...article.querySelectorAll('.tool-fetch')];
      if (!buttons.length) return;
      const rail = document.createElement('div');
      rail.className = 'source-rail';
      rail.innerHTML = `<span class="source-label">Sources</span>`;
      buttons.forEach((button) => {
        let sources = [];
        try { sources = JSON.parse(button.dataset.toolFetch || '[]'); } catch { return; }
        sources.forEach((source) => { const sourceButton = document.createElement('button'); sourceButton.type = 'button'; sourceButton.className = 'source-card'; sourceButton.textContent = `${source.title || 'Source'} · ${source.location || 'location unavailable'}`; sourceButton.addEventListener('click', () => button.click()); rail.appendChild(sourceButton); });
      });
      article.appendChild(rail);
    });
  };

  const enhanceSearch = () => {
    const input = $('global-search');
    if (!input || input.dataset.bridgeBound === '1') return;
    input.dataset.bridgeBound = '1';
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && input.value.trim()) { event.preventDefault(); renderGlobalSearch(input.value.trim()); }
    });
  };

  const renderGlobalSearch = async (query) => {
    const result = await safe(() => api(`/api/search?q=${encodeURIComponent(query)}`));
    if (!result) return;
    document.querySelector('.bridge-search-results')?.remove();
    const hits = [
      ...(result.chats || []).map((item) => ({ kind: 'chat', id: item.id, title: item.title, meta: item.pinned ? 'Pinned chat' : '' })),
      ...(result.projects || []).map((item) => ({ kind: 'project', id: item.id, title: item.name, meta: item.description })),
      ...(result.notes || []).map((item) => ({ kind: 'note', id: item.id, projectId: item.project_id, title: item.title, meta: String(item.content || '').slice(0, 140) })),
      ...(result.calculations || []).map((item) => ({ kind: 'calculation', id: item.key, title: item.name, meta: item.domain })),
    ];
    const panel = document.createElement('div');
    panel.className = 'bridge-search-results global-search-results';
    panel.innerHTML = hits.length ? hits.slice(0, 24).map((item) => `<button type="button" data-bridge-kind="${attr(item.kind)}" data-bridge-id="${attr(item.id)}" data-bridge-project="${attr(item.projectId || '')}"><span>${esc(item.kind)}</span><strong>${esc(item.title)}</strong><small>${esc(item.meta || '')}</small></button>`).join('') : '<div class="empty-state">No matches.</div>';
    input?.parentElement?.appendChild(panel);
    panel.querySelectorAll('[data-bridge-id]').forEach((button) => button.addEventListener('click', async () => {
      panel.remove();
      const kind = button.dataset.bridgeKind;
      const id = button.dataset.bridgeId;
      if (kind === 'chat') return openChat(Number(id));
      if (kind === 'project') return openProject(Number(id));
      if (kind === 'calculation') return openCalculation(id);
      if (kind === 'note') {
        if (button.dataset.bridgeProject) await openProject(Number(button.dataset.bridgeProject));
        const note = await api(`/api/projects/${state.projectId}/notes?id=${Number(id)}`);
        modal(note.name || note.title || 'Note', `<pre class="text-preview">${esc(note.content || '')}</pre>`);
      }
    }));
  };

  const wireNavigation = () => {
    document.querySelectorAll('[data-view="simulations"]').forEach((button) => { if (button.dataset.bridgeBound !== '1') { button.dataset.bridgeBound = '1'; button.addEventListener('click', (event) => { event.preventDefault(); event.stopImmediatePropagation(); renderSimulationPage().catch((error) => toast(error)); }, true); } });
    document.querySelectorAll('[data-view="connections"]').forEach((button) => { if (button.dataset.bridgeBound !== '1') { button.dataset.bridgeBound = '1'; button.addEventListener('click', (event) => { event.preventDefault(); event.stopImmediatePropagation(); renderConnectionsPage().catch((error) => toast(error)); }, true); } });
  };

  const hydrate = () => { wireNavigation(); enhanceSearch(); enhanceSources(); };
  new MutationObserver(hydrate).observe(document.body, { childList: true, subtree: true });
  window.addEventListener('load', hydrate, { once: true });
})();
