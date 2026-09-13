(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let searchTimer = null;

  const storageKey = (label) => `pas-setting-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  const hydrateSettings = () => {
    const page = document.querySelector('.settings-page');
    if (!page || page.dataset.finalized === '1') return;
    page.dataset.finalized = '1';
    page.querySelectorAll('.settings-card label').forEach((label) => {
      const control = label.querySelector('select,input');
      const title = label.childNodes[0]?.textContent?.trim();
      if (!control || !title) return;
      const key = storageKey(title);
      const saved = localStorage.getItem(key);
      if (saved !== null) control.value = saved;
      control.addEventListener('change', () => localStorage.setItem(key, control.value));
    });
    const customize = document.createElement('section');
    customize.className = 'settings-card customize-card';
    customize.innerHTML = `<div class="page-head compact"><div><h2>Customize</h2><p class="muted">Control the capabilities and personalization layers available in this workspace.</p></div></div><div class="customize-tabs" role="tablist"><button type="button" class="active" data-customize="skills">Skills</button><button type="button" data-customize="connectors">Connectors</button><button type="button" data-customize="plugins">Plugins</button><button type="button" data-customize="you">You</button><button type="button" data-customize="discover">Discover</button></div><div id="customize-content" class="customize-content"></div>`;
    page.appendChild(customize);
    const render = async (tab) => {
      const content = $('customize-content');
      if (!content) return;
      document.querySelectorAll('[data-customize]').forEach((button) => button.classList.toggle('active', button.dataset.customize === tab));
      if (tab === 'skills') {
        content.innerHTML = `<div class="card-grid compact-grid"><div class="page-card"><strong>Engineering reasoning</strong><span>Active · requirements, evidence, calculations</span></div><div class="page-card"><strong>Programming</strong><span>Active · implementation, debugging, testing</span></div><div class="page-card"><strong>Research</strong><span>Active · source-grounded analysis</span></div><div class="page-card"><strong>Tutoring</strong><span>Active · explanations and practice</span></div></div>`;
        return;
      }
      if (tab === 'connectors') {
        const connections = await api('/api/connections');
        content.innerHTML = `<div class="properties">${connections.length ? connections.map((item) => `<div class="property"><span>${esc(item.name)}</span><strong>${esc(item.status)}</strong></div>`).join('') : '<div class="empty-state">No provider connections are registered.</div>'}</div>`;
        return;
      }
      if (tab === 'plugins') {
        const plugins = await api('/api/plugins');
        content.innerHTML = `<div class="properties">${plugins.length ? plugins.map((item) => `<div class="property"><span>${esc(item.name)} · ${esc(item.version)}</span><strong>${item.enabled ? 'Enabled' : 'Disabled'}</strong><small>${esc((item.capabilities || []).join(', '))}</small></div>`).join('') : '<div class="empty-state">No plugins are registered yet.</div>'}</div>`;
        return;
      }
      if (tab === 'you') {
        const user = state.user;
        content.innerHTML = `<div class="properties"><div class="property"><span>Display name</span><strong>${esc(user?.display_name || 'Not signed in')}</strong></div><div class="property"><span>Email</span><strong>${esc(user?.email || 'Local-only session')}</strong></div><div class="property"><span>Model preference</span><strong>${esc(localStorage.getItem('pas-model') || 'auto')}</strong></div><div class="property"><span>Theme</span><strong>${esc(localStorage.getItem('pas-theme') || 'system')}</strong></div></div>`;
        return;
      }
      const [catalog, simulations] = await Promise.all([api('/api/calculations/catalog'), api('/api/simulations')]);
      content.innerHTML = `<div class="card-grid compact-grid"><div class="page-card"><strong>${catalog.length} calculators</strong><span>Deterministic engineering calculation library</span></div><div class="page-card"><strong>${simulations.length} simulations</strong><span>Deterministic models with explicit assumptions and limitations</span></div><div class="page-card"><strong>6 engineering groups</strong><span>Cross-major calculator navigation</span></div></div>`;
    };
    customize.querySelectorAll('[data-customize]').forEach((button) => button.addEventListener('click', () => render(button.dataset.customize)));
    render('skills').catch(() => {});
  };

  const renderSearchResults = (query, groups) => {
    document.querySelector('.global-search-results')?.remove();
    const results = groups.flatMap((group) => group.items.map((item) => ({ ...item, group: group.label })));
    if (!query || !results.length) return;
    const panel = document.createElement('div');
    panel.className = 'global-search-results';
    panel.innerHTML = results.slice(0, 14).map((item) => `<button type="button" data-search-kind="${esc(item.kind)}" data-search-id="${esc(item.id)}"><span class="search-kind">${esc(item.group)}</span><strong>${esc(item.title)}</strong>${item.meta ? `<small>${esc(item.meta)}</small>` : ''}</button>`).join('');
    const input = $('global-search');
    input?.parentElement?.appendChild(panel);
    panel.querySelectorAll('[data-search-id]').forEach((button) => button.addEventListener('click', async () => {
      panel.remove();
      const kind = button.dataset.searchKind;
      const id = button.dataset.searchId;
      if (kind === 'chat') return openChat(Number(id));
      if (kind === 'project') return openProject(Number(id));
      if (kind === 'calculation') return openCalculation(id);
    }));
  };

  const runSearch = async () => {
    const input = $('global-search');
    const query = input?.value.trim().toLowerCase() || '';
    if (!query) { document.querySelector('.global-search-results')?.remove(); return; }
    try {
      const [chats, projects, catalog] = await Promise.all([api('/api/chats'), api('/api/projects'), api('/api/calculations/catalog')]);
      const groups = [
        { label: 'Chats', items: chats.filter((item) => item.title.toLowerCase().includes(query)).map((item) => ({ kind: 'chat', id: item.id, title: item.title, meta: item.pinned ? 'Pinned' : '' })) },
        { label: 'Projects', items: projects.filter((item) => item.name.toLowerCase().includes(query)).map((item) => ({ kind: 'project', id: item.id, title: item.name, meta: item.description || '' })) },
        { label: 'Calculations', items: catalog.filter((item) => `${item.name} ${item.key} ${item.domain}`.toLowerCase().includes(query)).map((item) => ({ kind: 'calculation', id: item.key, title: item.name, meta: item.domain || '' })) },
      ];
      renderSearchResults(query, groups);
    } catch (error) { window.showError?.(error); }
  };

  document.addEventListener('input', (event) => { if (event.target?.id === 'global-search') { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 140); } });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') document.querySelector('.global-search-results')?.remove();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('global-search')?.focus(); $('global-search')?.select(); }
  });
  document.addEventListener('click', (event) => {
    const input = $('global-search'); const results = document.querySelector('.global-search-results');
    if (results && event.target !== input && !results.contains(event.target)) results.remove();
  });
  new MutationObserver(hydrateSettings).observe(document.body, { childList: true, subtree: true });
})();
