(() => {
  const toastStack = () => {
    let el = document.querySelector('.ux-toast-stack');
    if (!el) { el = document.createElement('div'); el.className = 'ux-toast-stack'; document.body.appendChild(el); }
    return el;
  };
  const notify = (message, type='error') => {
    const stack = toastStack();
    const existing = [...stack.children].find(x => x.textContent === message);
    if (existing) return;
    const toast = document.createElement('div'); toast.className = `ux-toast ${type}`; toast.textContent = message; stack.appendChild(toast);
    setTimeout(() => toast.remove(), type === 'error' ? 5200 : 3200);
  };
  window.showError = e => notify(String(e?.message || e || 'Something went wrong.'));
  window.addEventListener('error', e => notify(e.error?.message || e.message || 'Unexpected error.'));
  window.addEventListener('unhandledrejection', e => notify(e.reason?.message || String(e.reason || 'Unexpected error.')));

  const draftChat = () => {
    state.chatId = null;
    setView('chat');
    $('project-tools').hidden = !state.projectId;
    $('chat-title').textContent = 'New chat';
    $('chat-context').textContent = state.projectId ? `Project · ${state.project?.name || 'Project'}` : 'Personal AI';
    $('chat-messages').innerHTML = `<div class="welcome-card"><div class="welcome-mark">✦</div><h2>What are you working on?</h2><p>This chat is created when you send the first message.</p><div class="prompt-grid"><button type="button" data-prompt="Build a transparent engineering model for this problem and identify the assumptions.">Model an engineering problem</button><button type="button" data-prompt="Explain this like a tutor, then give me progressively harder practice problems.">Study something</button></div></div>`;
    $('chat-input').focus();
  };

  const authForm = kind => {
    const signup = kind === 'signup';
    modal(signup ? 'Create account' : 'Log in', `<form id="auth-form" class="form-stack"><p class="ux-auth-copy">${signup ? 'Create an optional account to keep personalization and chats available across sessions.' : 'Login is optional; your local workspace remains usable without an account.'}</p><label>Email<input name="email" type="email" autocomplete="email" required></label>${signup ? '<label>Display name<input name="display_name" autocomplete="name"></label>' : ''}<label>Password<input name="password" type="password" autocomplete="current-password" minlength="8" required></label><div class="form-actions"><button type="button" class="outline-button" id="auth-cancel">Cancel</button><button class="primary-button">${signup ? 'Sign up' : 'Log in'}</button></div></form>`);
    $('auth-cancel').onclick = closeModal;
    $('auth-form').onsubmit = async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target));
      try {
        const result = await send(signup ? '/api/auth/signup' : '/api/auth/login', values);
        state.user = result.user; closeModal(); await refreshAuth(); notify(signup ? 'Account created.' : 'Logged in.', 'ok');
      } catch (error) { notify(error.message); }
    };
    $('auth-form').querySelector('input')?.focus();
  };

  const accountMenu = () => modal('Account', `<div class="form-stack"><div class="property"><span>Signed in as</span><strong>${esc(state.user?.email || '')}</strong></div><button id="logout-action" class="outline-button">Log out</button></div>`);

  const contextMenu = (x, y, kind, id, name) => {
    document.querySelector('.ux-context-menu')?.remove();
    const menu = document.createElement('div'); menu.className='ux-context-menu'; menu.setAttribute('role','menu'); menu.style.left=`${Math.min(x, innerWidth-245)}px`; menu.style.top=`${Math.min(y, innerHeight-360)}px`;
    const actions = kind === 'folder'
      ? [['Open','open'],['New note','new-note'],['New folder','new-folder'],['Rename','rename'],['Copy','copy'],['Duplicate','duplicate'],['Archive','archive'],['Invalidate','invalidate'],['Delete','delete']]
      : kind === 'note'
      ? [['Open','open'],['Rename','rename'],['Copy','copy'],['Duplicate','duplicate'],['Archive','archive'],['Invalidate','invalidate'],['Delete','delete']]
      : [['Open','open'],['Rename','rename'],['Copy','copy'],['Duplicate','duplicate'],['Archive','archive'],['Invalidate','invalidate'],['Delete','delete']];
    const groups=[actions.slice(0,3),actions.slice(3,6),actions.slice(6)];
    groups.forEach(group=>{const section=document.createElement('div');section.className='ux-context-group';group.forEach(([label,action])=>{const b=document.createElement('button');b.type='button';b.setAttribute('role','menuitem');b.textContent=label;b.className=action==='delete'?'danger':'';b.onclick=async()=>{menu.remove();try{if(action==='open')return openItem(kind,id);if(action==='new-note')return newItem('note');if(action==='new-folder')return newItem('folder');if(action==='rename')return renameItem(kind,id,name);if(action==='copy'){state.clipboard=[{kind,id}];notify('Copied.','ok');return}if(action==='duplicate')await send(`/api/projects/${state.projectId}/duplicate`,{kind,id});if(action==='archive'||action==='invalidate')await send(`/api/projects/${state.projectId}/lifecycle`,{kind,id,status:action==='archive'?'Archived':'Invalidated'});if(action==='delete')await send(`/api/projects/${state.projectId}/delete`,{selection:[{kind,id}]});await showProjectFiles();}catch(error){notify(error.message)}};section.appendChild(b)});menu.appendChild(section)});
    document.body.appendChild(menu); menu.querySelector('button')?.focus();
  };

  const bind = () => {
    document.head.insertAdjacentHTML('beforeend','<link rel="stylesheet" href="/ux-hardening.css">');
    const stop = (selector, handler) => document.addEventListener('click', event => { const target=event.target.closest(selector); if(!target)return; event.preventDefault(); event.stopImmediatePropagation(); handler(target,event); }, true);

    stop('#new-chat', () => draftChat());
    stop('#new-chat-header', () => draftChat());
    stop('#login-button', () => authForm('login'));
    stop('#signup-button', () => authForm('signup'));
    stop('#account-button', () => accountMenu());
    stop('[data-view="chat"]', () => draftChat());
    stop('[data-view="projects"]', () => openProjects());
    stop('[data-view="connections"]', () => openConnections());
    stop('#calculations-toggle', button => { const nav=$('#calculation-categories'); nav.hidden=!nav.hidden; nav.innerHTML = nav.hidden ? '' : (state.manifest?.calculation_majors || []).map(m=>`<button type="button" data-major-page="${attr(m)}">${esc(m)}</button>`).join('') || `<button type="button" data-major-page="Petroleum Engineering">Petroleum Engineering</button>`; });
    stop('[data-view="simulations"]', () => openSimulations?.());
    stop('[data-view="education"]', () => { setView('education'); $('page-view').innerHTML='<div class="page"><h1 class="page-title">Education</h1><p class="page-subtitle">Study plans, explanations, exercises, programming, and project-linked learning belong here.</p></div>'; });
    stop('[data-view="settings"]', () => { setView('settings'); $('page-view').innerHTML=`<div class="page"><div class="page-head"><div><h1 class="page-title">Settings</h1><p class="page-subtitle">Personalize the workspace without changing engineering project data.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="ux-settings-row"><span>Theme</span><select id="theme-setting"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div></div>`;const s=$('#theme-setting');s.value=localStorage.getItem('pas-theme')||'system';s.onchange=()=>{localStorage.setItem('pas-theme',s.value);applyTheme();}; });
    document.addEventListener('contextmenu', event => { const row=event.target.closest('.file-row'); if(!row || !state.projectId)return; event.preventDefault(); event.stopImmediatePropagation(); state.selected.clear(); state.selected.add(token(row.dataset.kind,row.dataset.id)); updateSelectionCount(); contextMenu(event.clientX,event.clientY,row.dataset.kind,Number(row.dataset.id),row.dataset.name); }, true);
    document.addEventListener('click', event => { if(!event.target.closest('.ux-context-menu')) document.querySelector('.ux-context-menu')?.remove(); const back=event.target.closest('[data-back-chat]'); if(back){event.preventDefault();openChat(state.chatId)} }, true);
    document.addEventListener('keydown', event => { if(event.key==='Escape')document.querySelector('.ux-context-menu')?.remove(); if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='n'&&!event.target.matches('input,textarea')){event.preventDefault();draftChat();} }, true);
  };

  window.addEventListener('load', () => {
    try { state.projectId=null; state.project=null; state.folderId=null; state.chatId=null; setView('chat'); $('project-tools').hidden=true; } catch {}
  }, {once:true});
  bind();
})();
