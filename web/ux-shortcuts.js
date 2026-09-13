(() => {
  const focusSearch = () => {
    const input = document.getElementById('global-search');
    if (!input) return;
    input.focus();
    input.select();
  };

  window.addEventListener('keydown', (event) => {
    const typing = event.target?.matches?.('textarea,input,[contenteditable="true"]');
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !typing) {
      event.preventDefault();
      event.stopImmediatePropagation();
      focusSearch();
    }
  }, true);

  document.addEventListener('click', (event) => {
    const promptButton = event.target?.closest?.('[data-prompt]');
    if (!promptButton) return;
    const input = document.getElementById('chat-input');
    if (!input) return;
    event.preventDefault();
    input.value = promptButton.dataset.prompt || '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  });
})();
