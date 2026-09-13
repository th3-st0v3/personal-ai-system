(() => {
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const toast = (message, tone = 'error') => {
    let stack = document.querySelector('.ui-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'ui-toast-stack';
      document.body.appendChild(stack);
    }
    const item = document.createElement('div');
    item.className = `ui-toast ${tone}`;
    item.textContent = String(message || 'Something went wrong.');
    stack.appendChild(item);
    setTimeout(() => item.remove(), tone === 'error' ? 5200 : 3200);
  };

  const modelProfile = (value) => ({
    auto: 'profile:auto',
    claude: 'profile:claude-opus',
    gpt: 'profile:gpt-5.4',
    gemini: 'profile:gemini-3.1-pro',
    free: 'profile:free',
  }[value] || 'profile:auto');

  const addSources = (events) => {
    const sources = [];
    for (const event of events || []) {
      if (!Array.isArray(event?.sources)) continue;
      for (const source of event.sources) {
        const key = `${source?.source_id ?? ''}:${source?.chunk_id ?? ''}`;
        if (!sources.some((item) => item.key === key)) sources.push({ ...source, key });
      }
    }
    if (!sources.length) return;
    const assistant = [...document.querySelectorAll('#chat-messages .message.assistant')].at(-1);
    if (!assistant) return;
    const panel = document.createElement('div');
    panel.className = 'source-strip';
    panel.innerHTML = `<div class="source-heading"><span>Sources</span><span>${sources.length}</span></div><div class="source-list">${sources.slice(0, 8).map((source) => `<button type="button" class="source-card" title="${escapeHtml(source.location || '')}"><span class="source-name">${escapeHtml(source.title || 'Project source')}</span><span class="source-location">${escapeHtml(source.location || 'Retrieved project evidence')}</span></button>`).join('')}</div>`;
    assistant.appendChild(panel);
  };

  const renderPending = (content) => {
    const box = $('chat-messages');
    if (!box) return;
    const welcome = box.querySelector('.welcome-card');
    if (welcome) welcome.remove();
    box.insertAdjacentHTML('beforeend', `<article class="message user pending-message"><div class="user-bubble">${escapeHtml(content)}</div></article><article class="message assistant thinking-message"><div class="thinking-indicator"><span></span><span></span><span></span><em>Thinking…</em></div></article>`);
    requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
  };

  const removePending = () => {
    document.querySelectorAll('.pending-message, .thinking-message').forEach((node) => node.remove());
  };

  const sendCurrentMessage = async () => {
    const input = $('chat-input');
    if (!input) return;
    const content = input.value.trim();
    if (!content || input.disabled) return;
    try {
      if (!state.chatId) {
        const created = await send('/api/chats', { project_id: state.projectId });
        state.chatId = created.id;
      }
      const mode = $('ai-mode')?.value || localStorage.getItem('pas-model') || 'auto';
      localStorage.setItem('pas-model', mode);
      input.value = '';
      input.style.height = '';
      input.disabled = true;
      $('send-chat')?.classList.add('is-loading');
      renderPending(content);
      const controller = new AbortController();
      window.__pasActiveChatRequest = controller;
      const result = await api(`/api/chats/${state.chatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, mode: 'auto', model: modelProfile(mode) }),
        signal: controller.signal,
      });
      removePending();
      if (typeof window.__pasRenderMessages === 'function') window.__pasRenderMessages(result.messages || [], result.tool_events || []);
      addSources(result.tool_events || []);
      if (result.title && $('chat-title')) $('chat-title').textContent = result.title;
      if (typeof loadChats === 'function') await loadChats();
    } catch (error) {
      removePending();
      if (error?.name === 'AbortError') toast('Generation stopped.', 'ok');
      else toast(error?.message || 'Unable to send message.');
      input.value = content;
    } finally {
      if (window.__pasActiveChatRequest) window.__pasActiveChatRequest = null;
      input.disabled = false;
      $('send-chat')?.classList.remove('is-loading');
      input.focus();
    }
  };

  const configureComposer = () => {
    const input = $('chat-input');
    const select = $('ai-mode');
    if (!input || !select || input.dataset.stable === '1') return;
    input.dataset.stable = '1';
    select.value = localStorage.getItem('pas-model') || select.value || 'auto';
    select.addEventListener('change', () => localStorage.setItem('pas-model', select.value));
    const resize = () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 240)}px`;
    };
    input.addEventListener('input', resize);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        $('chat-form')?.requestSubmit();
      }
    });
    resize();
  };

  document.addEventListener('submit', (event) => {
    if (event.target?.id !== 'chat-form') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    sendCurrentMessage();
  }, true);

  document.addEventListener('click', (event) => {
    const stopButton = event.target.closest('#send-chat.is-loading');
    if (stopButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.__pasActiveChatRequest?.abort();
    }
  }, true);

  document.addEventListener('change', (event) => {
    if (event.target?.id === 'ai-mode') localStorage.setItem('pas-model', event.target.value);
  });

  new MutationObserver(configureComposer).observe(document.body, { childList: true, subtree: true });
  window.addEventListener('load', configureComposer, { once: true });
})();
