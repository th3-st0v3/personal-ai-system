(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  const sourceTools = async () => {
    if (!state.projectId || !document.querySelector('.page .page-card h3') || document.querySelector('[data-engineering-source-tools]')) return;
    const cards = [...document.querySelectorAll('.page .page-card')];
    const sourceCard = cards.find((card) => card.querySelector('h3')?.textContent?.trim() === 'Sources');
    if (!sourceCard) return;
    sourceCard.dataset.engineeringSourceTools = '1';
    const tools = document.createElement('div');
    tools.dataset.engineeringSourceTools = '1';
    tools.className = 'engineering-source-tools';
    tools.innerHTML = `<div class="inline-actions"><button type="button" class="outline-button" data-github-source>Import GitHub file</button><button type="button" class="quiet-button" data-search-sources>Search sources</button></div>`;
    sourceCard.appendChild(tools);
    tools.querySelector('[data-github-source]').onclick = () => {
      modal('Import GitHub file', `<form id="github-source-form" class="form-stack"><p class="muted">Import a public GitHub file as project evidence. The content is stored as inert source data and can be searched later.</p><label>GitHub file URL<input name="url" type="url" required placeholder="https://github.com/owner/repo/blob/main/README.md"></label><div class="form-actions"><button type="button" class="outline-button" id="github-cancel">Cancel</button><button class="primary-button">Import</button></div></form>`);
      $('#github-cancel').onclick = closeModal;
      $('#github-source-form').onsubmit = async (event) => {
        event.preventDefault();
        try {
          const values = Object.fromEntries(new FormData(event.target));
          await send(`/api/engineering/projects/${state.projectId}/sources/github`, values);
          closeModal();
          await openProjectEngineering();
        } catch (error) { $('#github-source-form').insertAdjacentHTML('afterend', `<div class="error">${esc(error.message)}</div>`); }
      };
    };
    tools.querySelector('[data-search-sources]').onclick = async () => {
      modal('Search project sources', `<form id="source-search-form" class="form-stack"><label>Search<input name="q" required placeholder="pressure drop, material, requirement…"></label><div class="form-actions"><button type="button" class="outline-button" id="source-search-cancel">Cancel</button><button class="primary-button">Search</button></div><div id="source-search-results" class="source-search-results"></div></form>`);
      $('#source-search-cancel').onclick = closeModal;
      $('#source-search-form').onsubmit = async (event) => {
        event.preventDefault();
        const query = new FormData(event.target).get('q')?.toString().trim();
        if (!query) return;
        try {
          const results = await api(`/api/engineering/projects/${state.projectId}/sources/search?q=${encodeURIComponent(query)}&limit=20`);
          $('#source-search-results').innerHTML = results.length ? results.map((result) => `<article class="source-search-result"><strong>${esc(result.source)}</strong><span>${esc(result.location)}</span><p>${esc(result.content)}</p></article>`).join('') : '<div class="empty-state">No matching source chunks were found.</div>';
        } catch (error) { $('#source-search-results').innerHTML = `<div class="error">${esc(error.message)}</div>`; }
      };
    };
  };

  const evidenceTools = async () => {
    const workspace = $('#evidence-workspace');
    if (!workspace || workspace.dataset.finalized === '1') return;
    workspace.dataset.finalized = '1';
    const requirements = await api(`/api/engineering/projects/${state.projectId}/requirements`);
    workspace.innerHTML = '';
    for (const requirement of requirements) {
      const evidence = await api(`/api/engineering/projects/${state.projectId}/requirements/${requirement.id}/evidence`);
      const row = document.createElement('div');
      row.className = 'file-row evidence-requirement-row';
      row.innerHTML = `<span>⌁</span><span><span class="file-name">Requirement #${requirement.id}: ${esc(requirement.title || requirement.description)}</span><span class="file-meta">${evidence.length} evidence records · ${esc(requirement.status)}</span><span class="evidence-list">${evidence.map((item) => `<span class="evidence-chip">${esc(item.supports_status || 'Unverified')} · ${esc(item.description || item.result || '')}</span>`).join('')}</span></span><button class="quiet-button" data-add-evidence-final="${requirement.id}">Add evidence</button></div>`;
      workspace.appendChild(row);
      row.querySelector('[data-add-evidence-final]')?.addEventListener('click', () => engineeringForm('evidence', requirement.id));
      evidence.forEach((item) => {
        const chip = [...row.querySelectorAll('.evidence-chip')][evidence.indexOf(item)];
        if (!chip) return;
        const invalidate = document.createElement('button');
        invalidate.type = 'button';
        invalidate.className = 'quiet-button evidence-invalidate';
        invalidate.textContent = 'Invalidate';
        invalidate.onclick = async () => {
          const reason = prompt('Why is this evidence being invalidated?');
          if (!reason?.trim()) return;
          try {
            await send(`/api/engineering/projects/${state.projectId}/evidence/invalidate`, { id: item.id, reason: reason.trim() });
            await openProjectEngineering();
          } catch (error) { window.showError?.(error); }
        };
        chip.appendChild(invalidate);
      });
    }
  };

  const hydrate = async () => {
    if (!state.projectId) return;
    try {
      await sourceTools();
      await evidenceTools();
    } catch (error) {
      window.showError?.(error);
    }
  };

  new MutationObserver(() => hydrate()).observe(document.body, { childList: true, subtree: true });
  window.addEventListener('load', hydrate, { once: true });
})();
