(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const calculationEndpoint = (key) => `/api/calculations/${encodeURIComponent(key)}`;
  const notify = (message) => {
    if (typeof showError === 'function') showError(new Error(String(message)));
    else window.alert(String(message));
  };

  const handleCalculation = async (event) => {
    const form = event.target;
    if (!form || form.id !== 'calc-form') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const key = form.dataset.calculationKey || state.calcKey;
    const resultNode = $('calc-result');
    if (!key || !resultNode) return;
    const inputs = Object.fromEntries([...new FormData(form)].filter(([, value]) => String(value).trim() !== '').map(([name, value]) => [name, Number(value)]));
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) button.disabled = true;
    try {
      await api(calculationEndpoint(key));
      const trace = await send('/api/calculations/run/save', { model_key: key, inputs });
      resultNode.innerHTML = `<div class="trace"><div class="trace-status">Saved as calculation record #${esc(trace.record_id)}</div><strong>${esc(trace.result)} ${esc(trace.result_unit)}</strong><ol>${(trace.steps || []).map((step) => `<li>${esc(step)}</li>`).join('')}</ol><h3>Assumptions</h3><ul>${(trace.assumptions || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul><h3>Limitations</h3><ul>${(trace.limitations || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul></div>`;
    } catch (error) {
      resultNode.innerHTML = `<div class="error">${esc(error?.message || error)}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  };

  const addPasteAction = () => {
    const panel = $('project-files-panel');
    if (!panel || panel.hidden || !state.clipboard?.length) {
      panel?.querySelector('#project-paste')?.remove();
      return;
    }
    if (panel.querySelector('#project-paste')) return;
    const actions = panel.querySelector('.file-actions');
    if (!actions) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'project-paste';
    button.className = 'quiet-button';
    button.textContent = `Paste ${state.clipboard.length}`;
    actions.appendChild(button);
    button.addEventListener('click', async () => {
      try {
        await send(`/api/projects/${state.projectId}/paste`, { target_folder_id: state.folderId, selection: state.clipboard });
        state.clipboard = [];
        await showProjectFiles();
      } catch (error) { notify(error?.message || error); }
    });
  };

  document.addEventListener('submit', handleCalculation, true);
  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-item-action="copy"]');
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const title = document.querySelector('#modal-title')?.textContent || '';
    const item = state.items?.find((entry) => entry.name === title);
    if (!item) return notify(`Could not identify ${title || 'the selected item'} to copy.`);
    state.clipboard = [{ kind: item.kind, id: item.id }];
    closeModal();
    addPasteAction();
  }, true);

  new MutationObserver(addPasteAction).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  window.addEventListener('load', addPasteAction, { once: true });
})();
