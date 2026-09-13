(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const attr = (value) => esc(value).replace(/'/g, '&#39;');
  const inject = () => {
    if (!state.projectId || document.querySelector('[data-pdf-source-tool]')) return;
    const sourceCard = [...document.querySelectorAll('.page .page-card')].find((card) => card.querySelector('h3')?.textContent?.trim() === 'Sources');
    if (!sourceCard) return;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'quiet-button'; button.dataset.pdfSourceTool = '1'; button.textContent = 'Import PDF';
    sourceCard.querySelector('.inline-actions')?.appendChild(button) || sourceCard.appendChild(button);
    button.onclick = () => {
      modal('Import PDF source', `<form id="pdf-source-form" class="form-stack"><p class="muted">Upload a text-based PDF. The extracted text is stored as inert, searchable source data with page markers. Scanned PDFs are not OCR'd yet.</p><label>Title<input name="title" required placeholder="design-report.pdf"></label><label>Version<input name="version" placeholder="1.0"></label><input id="pdf-source-file" type="file" accept="application/pdf" required><div class="form-actions"><button type="button" class="outline-button" id="pdf-cancel">Cancel</button><button class="primary-button">Ingest PDF</button></div></form>`);
      $('#pdf-cancel').onclick = closeModal;
      $('#pdf-source-form').onsubmit = async (event) => {
        event.preventDefault();
        const form = event.target; const file = $('#pdf-source-file').files?.[0];
        if (!file) return;
        if (file.size > 4 * 1024 * 1024) { form.insertAdjacentHTML('afterend','<div class="error">PDF must be 4 MB or smaller.</div>'); return; }
        try {
          const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(new Error('Could not read the PDF.')); reader.onload = () => resolve(String(reader.result).split(',',2)[1]); reader.readAsDataURL(file); });
          const values = Object.fromEntries(new FormData(form));
          await send(`/api/engineering/projects/${state.projectId}/sources/pdf`, { title: values.title || file.name, version: values.version || '', data_base64: data });
          closeModal(); await openProjectEngineering();
        } catch (error) { form.insertAdjacentHTML('afterend', `<div class="error">${esc(error.message || error)}</div>`); }
      };
    };
  };
  new MutationObserver(inject).observe(document.body, {childList:true,subtree:true});
  window.addEventListener('load', inject, {once:true});
})();
