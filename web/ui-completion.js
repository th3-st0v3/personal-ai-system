(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const attr = (value) => esc(value).replace(/'/g, '&#39;');
  const api = async (path) => {
    const response = await fetch(path, { credentials: 'same-origin' });
    const data = await response.json().catch(() => ({ error: 'Invalid server response' }));
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  };

  let catalog = [];
  let categories = [];
  let initialized = false;
  let allowNextNewChatClick = false;

  const itemsForCategory = (category) => catalog.filter((item) => (item.categories || []).includes(category));
  const groupsForCategory = (category) => [...new Set(itemsForCategory(category).flatMap((item) => item.subcategories || []))];
  const itemsForGroup = (category, group) => itemsForCategory(category).filter((item) => (item.subcategories || []).includes(group));

  const closeCalculationMenu = () => {
    const menu = $('calculation-categories');
    const toggle = $('calculations-toggle');
    if (!menu) return;
    menu.hidden = true;
    menu.querySelectorAll('.calc-nav-subnav').forEach((subnav) => { subnav.hidden = true; });
    menu.querySelectorAll('.calc-nav-item[data-calculation-category]').forEach((button) => button.setAttribute('aria-expanded', 'false'));
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.classList.remove('expanded');
  };

  const triggerExistingNewChat = (button) => {
    if (!button) return;
    allowNextNewChatClick = true;
    button.click();
  };

  const openNewChat = () => {
    closeCalculationMenu();
    triggerExistingNewChat($('new-chat'));
    requestAnimationFrame(() => $('chat-input')?.focus());
  };

  const renderCalculationMenu = () => {
    const menu = $('calculation-categories');
    if (!menu) return;
    menu.innerHTML = categories.map((category, index) => {
      const groups = groupsForCategory(category);
      const safeId = `calc-category-${index}`;
      return `<div class="calc-nav-section"><button class="calc-nav-item" type="button" data-calculation-category="${attr(category)}" aria-expanded="false" aria-controls="${safeId}"><span class="calc-nav-icon">Σ</span><span class="calc-nav-label">${esc(category)}</span><span class="calc-nav-count">${itemsForCategory(category).length}</span><span class="calc-nav-arrow">›</span></button><div id="${safeId}" class="calc-nav-subnav" hidden>${groups.map((group) => `<button class="calc-nav-group" type="button" data-calculation-group="${attr(category)}" data-calculation-subgroup="${attr(group)}"><span>${esc(group)}</span><span>${itemsForGroup(category, group).length}</span></button>`).join('')}<button class="calc-nav-all" type="button" data-open-calculation-group="${attr(category)}">View all in ${esc(category)} <span>→</span></button></div></div>`;
    }).join('');
  };

  const calculationCard = (item) => `<button type="button" class="calculation-card" data-open-calculation="${attr(item.key)}"><span class="calculation-card-top"><span class="calculation-card-icon">Σ</span><span class="calculation-card-domain">${esc(item.domain || 'Engineering')}</span></span><strong>${esc(item.name)}</strong><span class="calculation-card-equation">${esc(item.equation || 'Deterministic model')}</span><span class="calculation-card-meta">${esc((item.subcategories || [])[0] || 'Calculation')} · ${esc(item.result_unit || 'Result')}</span></button>`;

  const calculationGroupCard = (category, group) => {
    const items = itemsForGroup(category, group);
    return `<button type="button" class="calculation-group-card" data-open-calculation-subgroup="${attr(category)}" data-calculation-subgroup="${attr(group)}"><span class="calculation-group-card-icon">Σ</span><span><strong>${esc(group)}</strong><small>${items.length} calculator${items.length === 1 ? '' : 's'}</small></span><span class="calculation-group-card-arrow">→</span></button>`;
  };

  const calculationMatches = (items, query) => {
    const normalized = String(query || '').trim().toLowerCase();
    if (!normalized) return items;
    return items.filter((item) => `${item.name} ${item.key} ${item.domain} ${(item.subcategories || []).join(' ')} ${(item.use_cases || []).join(' ')}`.toLowerCase().includes(normalized));
  };

  const openCalculations = async () => {
    closeCalculationMenu();
    if (typeof window.setView === 'function') window.setView('calculations');
    const page = $('page-view');
    if (!page) return;
    page.hidden = false;
    $('home-view').hidden = true;
    $('project-tools').hidden = true;
    page.innerHTML = `<div class="page calculation-page"><div class="page-head calculation-page-head"><div><div class="eyebrow">Engineering tools</div><h1 class="page-title">Calculations</h1><p class="page-subtitle">A structured library of deterministic engineering models. Start with a discipline, narrow to a group, then run the exact calculator you need.</p></div><div class="calculation-page-actions"><label class="calculation-search"><span aria-hidden="true">⌕</span><input id="calculation-search-input" type="search" placeholder="Search calculations…" autocomplete="off"></label></div></div><div id="calculation-catalog-content" class="calculation-catalog-content"><div class="loading-state">Loading calculation library…</div></div></div>`;
    try {
      if (!catalog.length) {
        catalog = await api('/api/calculations/catalog');
        categories = [...new Set(catalog.flatMap((item) => item.categories || []))];
        renderCalculationMenu();
      }
      renderCalculationGroups('');
      $('calculation-search-input')?.addEventListener('input', (event) => renderCalculationGroups(event.target.value));
      $('calculation-search-input')?.focus();
    } catch (error) {
      const content = page.querySelector('#calculation-catalog-content');
      if (content) content.innerHTML = `<div class="error-state"><strong>Calculations could not be loaded.</strong><span>${esc(error.message || error)}</span><button type="button" class="outline-button" id="retry-calculations">Retry</button></div>`;
      $('retry-calculations')?.addEventListener('click', openCalculations);
    }
  };

  const renderCalculationGroups = (query) => {
    const content = $('calculation-catalog-content');
    if (!content) return;
    const normalized = String(query || '').trim().toLowerCase();
    if (normalized) {
      const matches = calculationMatches(catalog, normalized);
      content.innerHTML = matches.length ? `<section class="calculation-search-results"><div class="calculation-group-heading"><div><h2>Search results</h2><p>${matches.length} calculator${matches.length === 1 ? '' : 's'} matched</p></div></div><div class="calculation-card-grid">${matches.map(calculationCard).join('')}</div></section>` : `<div class="empty-state calculation-empty"><div class="empty-state-icon">⌕</div><h2>No calculations found</h2><p>Try a calculator name, engineering discipline, group, or use case.</p></div>`;
      return;
    }
    content.innerHTML = categories.map((category) => `<section class="calculation-category-section"><div class="calculation-group-heading"><div><span class="eyebrow">Discipline</span><h2>${esc(category)}</h2><p>${itemsForCategory(category).length} calculators · ${groupsForCategory(category).length} groups</p></div><button type="button" class="calculation-group-link" data-open-calculation-group="${attr(category)}">Open discipline <span>→</span></button></div><div class="calculation-group-card-grid">${groupsForCategory(category).map((group) => calculationGroupCard(category, group)).join('')}</div></section>`).join('');
  };

  const openCalculationGroup = (category) => {
    const items = itemsForCategory(category);
    if (!items.length) return;
    const groups = groupsForCategory(category);
    const page = $('page-view');
    if (!page) return;
    if (typeof window.setView === 'function') window.setView('calculations');
    $('home-view').hidden = true;
    page.hidden = false;
    $('project-tools').hidden = true;
    page.innerHTML = `<div class="page calculation-page"><div class="calculation-breadcrumb"><button type="button" class="breadcrumb-button" id="back-to-calculations">Calculations</button><span>›</span><strong>${esc(category)}</strong></div><div class="page-head calculation-page-head"><div><div class="eyebrow">Calculation discipline</div><h1 class="page-title">${esc(category)}</h1><p class="page-subtitle">Choose a calculation group to see its deterministic models.</p></div><label class="calculation-search"><span aria-hidden="true">⌕</span><input id="calculation-group-search" type="search" placeholder="Search this discipline…" autocomplete="off"></label></div><div id="calculation-group-content" class="calculation-group-detail"><div class="calculation-group-card-grid">${groups.map((group) => calculationGroupCard(category, group)).join('')}</div></div></div>`;
    $('back-to-calculations')?.addEventListener('click', openCalculations);
    $('calculation-group-search')?.addEventListener('input', (event) => {
      const q = String(event.target.value || '').toLowerCase().trim();
      const matchingGroups = groups.filter((group) => `${group} ${itemsForGroup(category, group).map((item) => `${item.name} ${item.key} ${item.use_cases?.join(' ') || ''}`).join(' ')}`.toLowerCase().includes(q));
      $('calculation-group-content').innerHTML = matchingGroups.length ? `<div class="calculation-group-card-grid">${matchingGroups.map((group) => calculationGroupCard(category, group)).join('')}</div>` : `<div class="empty-state calculation-empty"><div class="empty-state-icon">⌕</div><h2>No matching groups</h2><p>Try another term.</p></div>`;
    });
    $('calculation-group-search')?.focus();
  };

  const openCalculationSubgroup = (category, group) => {
    const items = itemsForGroup(category, group);
    if (!items.length) return;
    const page = $('page-view');
    if (!page) return;
    closeCalculationMenu();
    if (typeof window.setView === 'function') window.setView('calculations');
    $('home-view').hidden = true;
    page.hidden = false;
    $('project-tools').hidden = true;
    page.innerHTML = `<div class="page calculation-page"><div class="calculation-breadcrumb"><button type="button" class="breadcrumb-button" id="back-to-calculation-discipline">${esc(category)}</button><span>›</span><strong>${esc(group)}</strong></div><div class="page-head calculation-page-head"><div><div class="eyebrow">Calculation group</div><h1 class="page-title">${esc(group)}</h1><p class="page-subtitle">${items.length} deterministic calculator${items.length === 1 ? '' : 's'} in ${esc(category)}.</p></div><label class="calculation-search"><span aria-hidden="true">⌕</span><input id="calculation-subgroup-search" type="search" placeholder="Search this group…" autocomplete="off"></label></div><div id="calculation-subgroup-content"><div class="calculation-card-grid">${items.map(calculationCard).join('')}</div></div></div>`;
    $('back-to-calculation-discipline')?.addEventListener('click', () => openCalculationGroup(category));
    $('calculation-subgroup-search')?.addEventListener('input', (event) => {
      const matches = calculationMatches(items, event.target.value);
      $('calculation-subgroup-content').innerHTML = matches.length ? `<div class="calculation-card-grid">${matches.map(calculationCard).join('')}</div>` : `<div class="empty-state calculation-empty"><div class="empty-state-icon">⌕</div><h2>No matching calculators</h2><p>Try another term.</p></div>`;
    });
    $('calculation-subgroup-search')?.focus();
  };

  const interceptClicks = (event) => {
    const target = event.target?.closest?.('#new-chat, #new-chat-header, #calculations-toggle, [data-calculation-category], [data-calculation-group], [data-open-calculation-group], [data-open-calculation-subgroup], [data-open-calculation]');
    if (!target) return;

    if (target.matches('#new-chat, #new-chat-header')) {
      if (allowNextNewChatClick) { allowNextNewChatClick = false; return; }
      event.preventDefault();
      event.stopImmediatePropagation();
      openNewChat();
      return;
    }

    if (target.id === 'calculations-toggle') {
      event.preventDefault();
      event.stopImmediatePropagation();
      const menu = $('calculation-categories');
      if (!menu) return;
      const willOpen = menu.hidden;
      if (!willOpen) closeCalculationMenu();
      else {
        menu.hidden = false;
        target.setAttribute('aria-expanded', 'true');
        target.classList.add('expanded');
      }
      return;
    }

    if (target.matches('[data-calculation-category]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const section = target.closest('.calc-nav-section');
      const subnav = section?.querySelector('.calc-nav-subnav');
      const willOpen = !!subnav?.hidden;
      $('calculation-categories')?.querySelectorAll('.calc-nav-subnav').forEach((node) => { if (node !== subnav) node.hidden = true; });
      $('calculation-categories')?.querySelectorAll('.calc-nav-item[data-calculation-category]').forEach((button) => button.setAttribute('aria-expanded', 'false'));
      if (subnav) subnav.hidden = !willOpen;
      target.setAttribute('aria-expanded', String(willOpen));
      return;
    }

    if (target.matches('[data-calculation-group]') && target.matches('[data-calculation-subgroup]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openCalculationSubgroup(target.dataset.calculationGroup, target.dataset.calculationSubgroup);
      return;
    }

    if (target.matches('[data-open-calculation-subgroup]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openCalculationSubgroup(target.dataset.openCalculationSubgroup, target.dataset.calculationSubgroup);
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
      openNewChat();
      return;
    }
    if (event.key === 'Escape') {
      closeCalculationMenu();
      document.body.classList.remove('nav-open');
    }
  };

  const enhanceComposer = () => {
    const input = $('chat-input');
    if (!input || input.dataset.uiEnhanced) return;
    input.dataset.uiEnhanced = 'true';
    const resize = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 180)}px`; };
    input.addEventListener('input', resize);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        $('chat-form')?.requestSubmit();
      }
    });
    resize();
  };

  const enhanceMobileNavigation = () => {
    const toggle = $('menu-toggle');
    if (!toggle || toggle.dataset.uiEnhanced) return;
    toggle.dataset.uiEnhanced = 'true';
    toggle.setAttribute('aria-controls', 'sidebar');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.addEventListener('click', () => {
      const open = document.body.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', (event) => {
      if (!document.body.classList.contains('nav-open')) return;
      if (event.target?.closest?.('#sidebar, #menu-toggle')) return;
      document.body.classList.remove('nav-open');
      toggle.setAttribute('aria-expanded', 'false');
    });
  };

  const init = async () => {
    if (initialized) return;
    initialized = true;
    const toggle = $('calculations-toggle');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-controls', 'calculation-categories');
    document.addEventListener('click', interceptClicks, true);
    window.addEventListener('keydown', interceptKeys, true);
    enhanceComposer();
    enhanceMobileNavigation();
    document.addEventListener('click', (event) => {
      const menu = $('calculation-categories');
      if (!menu || menu.hidden) return;
      if (!event.target?.closest?.('#calculations-toggle, #calculation-categories')) closeCalculationMenu();
    });
    try {
      catalog = await api('/api/calculations/catalog');
      categories = [...new Set(catalog.flatMap((item) => item.categories || []))];
      renderCalculationMenu();
    } catch (error) {
      console.warn('Calculation catalog unavailable during UI initialization', error);
    }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else void init();
})();
