(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const notify = (message) => {
    if (typeof window.showError === 'function') window.showError(new Error(String(message)));
    else window.alert(String(message));
  };

  const handleCalculation = async (event) => {
    const form = event.target;
    if (!form || form.id !== 'calc-form') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const key = form.dataset.calculationKey || window.state?.calcKey;
    const resultNode = $('calc-result');
    if (!key || !resultNode) return;
    const inputs = Object.fromEntries([...new FormData(form)].filter(([, value]) => String(value).trim() !== '').map(([name, value]) => [name, Number(value)]));
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) button.disabled = true;
    try {
      const trace = await window.send('/api/calculations/run/save', { model_key: key, inputs });
      resultNode.innerHTML = `<div class="trace"><div class="trace-status">Saved as calculation record #${esc(trace.record_id)}</div><strong>${esc(trace.result)} ${esc(trace.result_unit)}</strong><ol>${(trace.steps || []).map((step) => `<li>${esc(step)}</li>`).join('')}</ol><h3>Assumptions</h3><ul>${(trace.assumptions || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul><h3>Limitations</h3><ul>${(trace.limitations || []).map((item) => `<li>${esc(item)}</li>`).join('')}</ul></div>`;
    } catch (error) {
      resultNode.innerHTML = `<div class="error">${esc(error?.message || error)}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  };

  const addPasteAction = () => {
    const panel = $('project-files-panel');
    if (!panel || panel.hidden || !window.state?.clipboard?.length) {
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
    button.textContent = `Paste ${window.state.clipboard.length}`;
    actions.appendChild(button);
    button.addEventListener('click', async () => {
      try {
        await window.send(`/api/projects/${window.state.projectId}/paste`, { target_folder_id: window.state.folderId, selection: window.state.clipboard });
        window.state.clipboard = [];
        await window.showProjectFiles();
      } catch (error) { notify(error?.message || error); }
    });
  };

  document.addEventListener('submit', handleCalculation, true);
  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-item-action="copy"]');
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const title = document.querySelector('#modal-title')?.textContent || 'item';
    const name = document.querySelector('.file-row.dragging .file-name')?.textContent || title;
    const item = window.state?.items?.find((entry) => entry.name === name || entry.name === title);
    if (item && window.state) {
      window.state.clipboard = [{ kind: item.kind, id: item.id }];
      if (typeof window.closeModal === 'function') window.closeModal();
    }
  }, true);

  new MutationObserver(addPasteAction).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] });
  window.addEventListener('load', addPasteAction, { once: true });
})();
