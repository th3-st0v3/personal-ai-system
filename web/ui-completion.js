(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const attr = (value) => esc(value).replace(/'/g, '&#39;');

  let catalog = [];
  let categories = [];
  let initialized = false;

  const categorySlug = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  const closeCalculationMenu = () => {
    const menu = $('calculation-categories');
    const toggle = $('calculations-toggle');
    if (!menu) return;
    menu.hidden = true;
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.classList.remove('expanded');
  };

  const openNewChat = async () => {
    if (typeof window.createChat !== 'function') return;
    closeCalculationMenu();
    try {
      const button = $('new-chat') || $('new-chat-header');
      if (button) button.disabled = true;
      await window.createChat(window.state?.projectId ?? null);
      if (typeof window.setView === 'function') window.setView('chat');
      const input = $('chat-input');
      input?.focus();
    } catch (error) {
      window.showError?.(error);
    } finally {
      const button = $('new-chat') || $('new-chat-header');
      if (button) button.disabled = false;
    }
  };

  const groupItems = (category) => catalog.filter((item) => (item.categories || []).includes(category));

  const renderCalculationMenu = () => {
    const menu = $('calculation-categories');
    if (!menu) return;
    menu.innerHTML = categories.map((category) => {
      const count = groupItems(category).length;
      return `<button class="calc-nav-item" type="button" data-calculation-category="${attr(category)}" title="Open ${attr(category)} calculators"><span class="calc-nav-icon">Σ</span><span class="calc-nav-label">${esc(category)}</span><span class="calc-nav-count">${count}</span><span class="calc-nav-arrow">›</span></button>`;
    }).join('');
  };

  const openCalculations = async () => {
    closeCalculationMenu();
    if (typeof window.setView === 'function') window.setView('calculations');
    const page = $('page-view');
    if (!page) return;
    page.hidden = false;
    $('home-view').hidden = true;
    $('project-tools').hidden = true;
    page.innerHTML = `<div class="page calculation-page"><div class="page-head calculation-page-head"><div><div class="eyebrow">Engineering tools</div><h1 class="page-title">Calculations</h1><p class="page-subtitle">Deterministic calculators organized by engineering discipline and workflow.</p></div><div class="calculation-page-actions"><label class="calculation-search"><span aria-hidden="true">⌕</span><input id="calculation-search-input" type="search" placeholder="Search calculations…" autocomplete="off"></label></div></div><div id="calculation-catalog-content" class="calculation-catalog-content"><div class="loading-state">Loading calculation library…</div></div></div>`;
    try {
      if (!catalog.length) {
        catalog = await window.api('/api/calculations/catalog');
        categories = [...new Set(catalog.flatMap((item) => item.categories || []))];
        renderCalculationMenu();
      }
      renderCalculationGroups('');
      $('calculation-search-input')?.addEventListener('input', (event) => renderCalculationGroups(event.target.value));
      $('calculation-search-input')?.focus();
    } catch (error) {
      page.querySelector('#calculation-catalog-content').innerHTML = `<div class="error-state"><strong>Calculations could not be loaded.</strong><span>${esc(error.message || error)}</span><button type="button" class="outline-button" id="retry-calculations">Retry</button></div>`;
      $('retry-calculations')?.addEventListener('click', openCalculations);
    }
  };

  const renderCalculationGroups = (query) => {
    const content = $('calculation-catalog-content');
    if (!content) return;
    const normalized = String(query || '').trim().toLowerCase();
    const groups = categories.map((category) => {
      const items = groupItems(category).filter((item) => !normalized || `${item.name} ${item.key} ${item.domain} ${(item.subcategories || []).join(' ')} ${(item.use_cases || []).join(' ')}`.toLowerCase().includes(normalized));
      return { category, items };
    }).filter((group) => group.items.length);

    if (!groups.length) {
      content.innerHTML = `<div class="empty-state calculation-empty"><div class="empty-state-icon">⌕</div><h2>No calculations found</h2><p>Try a different name, engineering group, or use case.</p></div>`;
      return;
    }

    content.innerHTML = groups.map((group) => `<section class="calculation-group-section" data-calculation-group="${attr(group.category)}"><div class="calculation-group-heading"><div><h2>${esc(group.category)}</h2><p>${group.items.length} calculator${group.items.length === 1 ? '' : 's'}</p></div><button type="button" class="calculation-group-link" data-open-calculation-group="${attr(group.category)}">View group <span>→</span></button></div><div class="calculation-card-grid">${group.items.map(calculationCard).join('')}</div></section>`).join('');
  };

  const calculationCard = (item) => `<button type="button" class="calculation-card" data-open-calculation="${attr(item.key)}"><span class="calculation-card-top"><span class="calculation-card-icon">Σ</span><span class="calculation-card-domain">${esc(item.domain || 'Engineering')}</span></span><strong>${esc(item.name)}</strong><span class="calculation-card-equation">${esc(item.equation || 'Deterministic model')}</span><span class="calculation-card-meta">${esc((item.subcategories || [])[0] || 'Calculation')} · ${esc(item.result_unit || 'Result')}</span></button>`;

  const openCalculationGroup = (category) => {
    const items = groupItems(category);
    if (!items.length) return;
    const page = $('page-view');
    if (!page) return;
    if (typeof window.setView === 'function') window.setView('calculations');
    $('home-view').hidden = true;
    page.hidden = false;
    $('project-tools').hidden = true;
    page.innerHTML = `<div class="page calculation-page"><div class="calculation-breadcrumb"><button type="button" class="breadcrumb-button" id="back-to-calculations">Calculations</button><span>›</span><strong>${esc(category)}</strong></div><div class="page-head calculation-page-head"><div><div class="eyebrow">Calculation group</div><h1 class="page-title">${esc(category)}</h1><p class="page-subtitle">${items.length} deterministic calculator${items.length === 1 ? '' : 's'} in this group.</p></div><label class="calculation-search"><span aria-hidden="true">⌕</span><input id="calculation-group-search" type="search" placeholder="Search this group…" autocomplete="off"></label></div><div id="calculation-group-content" class="calculation-group-detail"><div class="calculation-card-grid">${items.map(calculationCard).join('')}</div></div></div>`;
    $('back-to-calculations')?.addEventListener('click', openCalculations);
    $('calculation-group-search')?.addEventListener('input', (event) => {
      const q = event.target.value.toLowerCase().trim();
      const filtered = items.filter((item) => `${item.name} ${item.key} ${item.domain} ${(item.subcategories || []).join(' ')} ${(item.use_cases || []).join(' ')}`.toLowerCase().includes(q));
      $('calculation-group-content').innerHTML = filtered.length ? `<div class="calculation-card-grid">${filtered.map(calculationCard).join('')}</div>` : `<div class="empty-state calculation-empty"><div class="empty-state-icon">⌕</div><h2>No matching calculators</h2><p>Try another term.</p></div>`;
    });
    $('calculation-group-search')?.focus();
  };

  const interceptClicks = (event) => {
    const target = event.target?.closest?.('#new-chat, #new-chat-header, #calculations-toggle, [data-calculation-category], [data-open-calculation-group], [data-open-calculation]');
    if (!target) return;
    if (target.matches('#new-chat, #new-chat-header')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void openNewChat();
      return;
    }
    if (target.id === 'calculations-toggle') {
      event.preventDefault();
      event.stopImmediatePropagation();
      const menu = $('calculation-categories');
      if (!menu) return;
      const willOpen = menu.hidden;
      if (!catalog.length) void openCalculations();
      menu.hidden = !willOpen;
      target.setAttribute('aria-expanded', String(willOpen));
      target.classList.toggle('expanded', willOpen);
      return;
    }
    if (target.matches('[data-calculation-category]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openCalculationGroup(target.dataset.calculationCategory);
      return;
    }
    if (target.matches('[data-open-calculation-group]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openCalculationGroup(target.dataset.openCalculationGroup);
      return;
    }
    if (target.matches('[data-open-calculation]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (typeof window.openCalculation === 'function') void window.openCalculation(target.dataset.openCalculation);
    }
  };

  const interceptKeys = (event) => {
    const key = event.key.toLowerCase();
    const typing = event.target?.matches?.('input, textarea, select, [contenteditable="true"]');
    if ((event.ctrlKey || event.metaKey) && key === 'o' && !typing) {
      event.preventDefault();
      event.stopImmediatePropagation();
      void openNewChat();
      return;
    }
    if (event.key === 'Escape') closeCalculationMenu();
  };

  const init = async () => {
    if (initialized) return;
    initialized = true;
    const toggle = $('calculations-toggle');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-controls', 'calculation-categories');
    document.addEventListener('click', interceptClicks, true);
    window.addEventListener('keydown', interceptKeys, true);
    document.addEventListener('click', (event) => {
      const menu = $('calculation-categories');
      if (!menu || menu.hidden) return;
      if (!event.target?.closest?.('#calculations-toggle, #calculation-categories')) closeCalculationMenu();
    });
    document.addEventListener('click', (event) => {
      const calculation = event.target?.closest?.('[data-open-calculation]');
      if (calculation && $('page-view')?.hidden === false) {
        event.preventDefault();
        if (typeof window.openCalculation === 'function') void window.openCalculation(calculation.dataset.openCalculation);
      }
    });
    try {
      catalog = await window.api('/api/calculations/catalog');
      categories = [...new Set(catalog.flatMap((item) => item.categories || []))];
      renderCalculationMenu();
    } catch (error) {
      // Keep navigation usable even when the catalog API is temporarily unavailable.
      console.warn('Calculation catalog unavailable during UI initialization', error);
    }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else void init();
})();
