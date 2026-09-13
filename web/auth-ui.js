(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const open = (kind) => {
    const signup = kind === 'signup';
    if (typeof modal !== 'function') return;
    modal(signup ? 'Create account' : 'Log in', `<form id="auth-ui-form" class="form-stack"><p class="muted">${signup ? 'Create an account to keep chats and personalization available across sessions.' : 'Login is optional; the local workspace can be used without an account.'}</p><label>Email<input name="email" type="email" autocomplete="email" required></label>${signup ? '<label>Display name<input name="display_name" autocomplete="name"></label>' : ''}<label>Password<input name="password" type="password" autocomplete="current-password" minlength="8" required></label><div class="form-actions"><button type="button" class="outline-button" id="auth-ui-cancel">Cancel</button><button class="primary-button">${signup ? 'Sign up' : 'Log in'}</button></div></form>`);
    $('auth-ui-cancel').onclick = closeModal;
    $('auth-ui-form').onsubmit = async (event) => {
      event.preventDefault();
      try {
        const values = Object.fromEntries(new FormData(event.target));
        const result = await send(signup ? '/api/auth/signup' : '/api/auth/login', values);
        state.user = result.user;
        closeModal();
        await refreshAuth();
      } catch (error) {
        $('auth-ui-form').insertAdjacentHTML('afterend', `<div class="error">${esc(error.message || error)}</div>`);
      }
    };
    $('auth-ui-form').querySelector('input')?.focus();
  };
  window.addEventListener('click', (event) => {
    const button = event.target.closest?.('#login-button,#signup-button');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    open(button.id === 'signup-button' ? 'signup' : 'login');
  }, true);
})();
