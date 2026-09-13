/* Shared accessibility behavior for the application shell. */
(() => {
  'use strict';

  const sidebar = document.getElementById('sidebar');
  const menuToggle = document.getElementById('menu-toggle');
  const modal = document.getElementById('modal');
  const modalCard = modal?.querySelector('.modal-card');
  let lastFocused = null;

  const isVisible = (element) => !!element && !element.hidden && element.getClientRects().length > 0;
  const focusable = (root) => [...root.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter(isVisible);

  const syncSidebarA11y = () => {
    if (!sidebar || !menuToggle) return;
    const open = document.body.classList.contains('nav-open');
    sidebar.setAttribute('aria-hidden', String(!open && window.matchMedia('(max-width: 900px)').matches));
    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-controls', 'sidebar');
  };

  const closeSidebar = () => {
    document.body.classList.remove('nav-open');
    syncSidebarA11y();
  };

  menuToggle?.addEventListener('click', () => {
    document.body.classList.toggle('nav-open');
    syncSidebarA11y();
    if (document.body.classList.contains('nav-open')) {
      requestAnimationFrame(() => sidebar?.querySelector('button:not([disabled])')?.focus());
    }
  }, true);

  sidebar?.addEventListener('click', (event) => {
    if (window.matchMedia('(max-width: 900px)').matches && event.target.closest('button[data-view], [data-calculation-category], [data-calculation-group]')) {
      requestAnimationFrame(closeSidebar);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSidebar();
    if (event.key !== 'Tab' || !modal || modal.hidden || !modalCard) return;
    const items = focusable(modalCard);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }, true);

  const modalObserver = modal ? new MutationObserver(() => {
    if (!modal.hidden && !lastFocused) {
      lastFocused = document.activeElement;
      requestAnimationFrame(() => focusable(modalCard)[0]?.focus());
    } else if (modal.hidden && lastFocused) {
      const target = lastFocused;
      lastFocused = null;
      requestAnimationFrame(() => target?.isConnected && target.focus());
    }
  }) : null;
  modalObserver?.observe(modal, { attributes: true, attributeFilter: ['hidden'] });

  const announce = (message) => {
    let live = document.getElementById('a11y-live-region');
    if (!live) {
      live = document.createElement('div');
      live.id = 'a11y-live-region';
      live.setAttribute('role', 'status');
      live.setAttribute('aria-live', 'polite');
      live.setAttribute('aria-atomic', 'true');
      Object.assign(live.style, { position: 'fixed', width: '1px', height: '1px', padding: '0', margin: '-1px', overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: '0' });
      document.body.appendChild(live);
    }
    live.textContent = String(message || '');
  };

  window.PASAccessibility = Object.freeze({ announce, closeSidebar, syncSidebarA11y });
  syncSidebarA11y();
})();
