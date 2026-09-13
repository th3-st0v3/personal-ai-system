(() => {
  const toastStack = () => {
    let el = document.querySelector('.ux-toast-stack');
    if (!el) { el = document.createElement('div'); el.className = 'ux-toast-stack'; document.body.appendChild(el); }
    return el;
  };
  const notify = (message, type='error') => {
    const text = String(message || 'Something went wrong.');
    const stack = toastStack();
    const existing = [...stack.children].find(x => x.textContent === text);
    if (existing) return;
    const toast = document.createElement('div'); toast.className = `ux-toast ${type}`; toast.textContent = text; stack.appendChild(toast);
    setTimeout(() => toast.remove(), type === 'error' ? 5200 : 3200);
  };
  window.showError = e => notify(e?.message || e || 'Something went wrong.');
  window.addEventListener('error', e => notify(e.error?.message || e.message || 'Unexpected error.'));
  window.addEventListener('unhandledrejection', e => notify(e.reason?.message || String(e.reason || 'Unexpected error.')));
  new MutationObserver(() => {
    for (const container of document.querySelectorAll('#page-view,#chat-messages')) {
      const seen = new Set();
      for (const error of container.querySelectorAll('.error')) {
        const key = error.textContent.trim();
        if (seen.has(key)) error.remove(); else seen.add(key);
      }
    }
  }).observe(document.body, {subtree:true, childList:true});

  const draftChat = () => {
    state.chatId = null;
    setView('chat'); $('project-tools').hidden = !state.projectId;
    $('chat-title').textContent = 'New chat';
    $('chat-context').textContent = state.projectId ? `Project · ${state.project?.name || 'Project'}` : 'Personal AI';
    $('chat-messages').innerHTML = `<div class="welcome-card"><div class="welcome-mark">✦</div><h2>What are you working on?</h2><p>This chat is created when you send the first message.</p><div class="prompt-grid"><button type="button" data-prompt="Build a transparent engineering model for this problem and identify the assumptions.">Model an engineering problem</button><button type="button" data-prompt="Explain this like a tutor, then give me a few progressively harder practice problems.">Study something</button><button type="button" data-prompt="Digest the information I provide into claims, evidence, assumptions, and open questions.">Digest information</button></div></div>`;
    $('chat-input').focus();
  };

  const authForm = kind => {
    const signup = kind === 'signup';
    modal(signup ? 'Create account' : 'Log in', `<form id="auth-form" class="form-stack"><p class="ux-auth-copy">${signup ? 'Create an optional account to keep personalization and chats available across sessions.' : 'Login is optional; your local workspace remains usable without an account.'}</p><label>Email<input name="email" type="email" autocomplete="email" required></label>${signup ? '<label>Display name<input name="display_name" autocomplete="name"></label>' : ''}<label>Password<input name="password" type="password" autocomplete="current-password" minlength="8" required></label><div class="form-actions"><button type="button" class="outline-button" id="auth-cancel">Cancel</button><button class="primary-button">${signup ? 'Sign up' : 'Log in'}</button></div></form>`);
    $('auth-cancel').onclick = closeModal;
    $('auth-form').onsubmit = async event => { event.preventDefault(); const values = Object.fromEntries(new FormData(event.target)); try { const result = await send(signup ? '/api/auth/signup' : '/api/auth/login', values); state.user = result.user; closeModal(); await refreshAuth(); notify(signup ? 'Account created.' : 'Logged in.', 'ok'); } catch (error) { notify(error.message); } };
    $('auth-form').querySelector('input')?.focus();
  };

  const accountMenu = () => modal('Account', `<div class="form-stack"><div class="property"><span>Signed in as</span><strong>${esc(state.user?.email || '')}</strong></div><button id="logout-action" class="outline-button">Log out</button></div>`);

  const contextMenu = (x, y, kind, id, name) => {
    document.querySelector('.ux-context-menu')?.remove();
    const menu = document.createElement('div'); menu.className='ux-context-menu'; menu.setAttribute('role','menu'); menu.style.left=`${Math.max(4,Math.min(x,innerWidth-245))}px`; menu.style.top=`${Math.max(4,Math.min(y,innerHeight-360))}px`;
    const actions = kind === 'folder' ? [['Open','open'],['New note','new-note'],['New folder','new-folder'],['Rename','rename'],['Copy','copy'],['Duplicate','duplicate'],['Archive','archive'],['Invalidate','invalidate'],['Delete','delete']] : [['Open','open'],['Rename','rename'],['Copy','copy'],['Duplicate','duplicate'],['Archive','archive'],['Invalidate','invalidate'],['Delete','delete']];
    [actions.slice(0,3),actions.slice(3,6),actions.slice(6)].forEach(group => { if(!group.length)return; const section=document.createElement('div'); section.className='ux-context-group'; group.forEach(([label,action])=>{const b=document.createElement('button'); b.type='button'; b.setAttribute('role','menuitem'); b.textContent=label; b.className=action==='delete'?'danger':''; b.onclick=async()=>{menu.remove();try{if(action==='open')return openItem(kind,id);if(action==='new-note')return newItem('note');if(action==='new-folder')return newItem('folder');if(action==='rename')return renameItem(kind,id,name);if(action==='copy'){state.clipboard=[{kind,id}];notify('Copied.','ok');return}if(action==='duplicate')await send(`/api/projects/${state.projectId}/duplicate`,{kind,id});if(action==='archive'||action==='invalidate')await send(`/api/projects/${state.projectId}/lifecycle`,{kind,id,status:action==='archive'?'Archived':'Invalidated'});if(action==='delete')await send(`/api/projects/${state.projectId}/delete`,{selection:[{kind,id}]});await showProjectFiles();}catch(error){notify(error.message)}};section.appendChild(b)});menu.appendChild(section); });
    document.body.appendChild(menu); menu.querySelector('button')?.focus();
  };

  const stop = (selector, handler) => document.addEventListener('click', event => { const target=event.target.closest(selector); if(!target)return; event.preventDefault(); event.stopImmediatePropagation(); Promise.resolve().then(() => handler(target,event)).catch(error => notify(error.message)); }, true);
  stop('#new-chat', draftChat); stop('#new-chat-header', draftChat); stop('#login-button', ()=>authForm('login')); stop('#signup-button', ()=>authForm('signup')); stop('#account-button', accountMenu); stop('[data-view="chat"]', draftChat); stop('[data-view="projects"]', ()=>openProjects()); stop('[data-view="connections"]', ()=>openConnections());
  stop('.chat-row', row => openChat(Number(row.dataset.chatId)));
  stop('.project-row', row => openProject(Number(row.dataset.projectId)));
  stop('[data-open-project]', card => openProject(Number(card.dataset.openProject)));
  stop('#calculations-toggle', async () => { const nav=$('#calculation-categories'); if(!nav.hidden){nav.hidden=true;nav.innerHTML='';return;} try { const majors=await api('/api/calculations/majors'); nav.innerHTML=majors.map(m=>`<button type="button" data-major-page="${attr(m.name)}">${esc(m.name)}</button>`).join(''); nav.hidden=false; } catch(error){notify(error.message)} });
  stop('[data-view="simulations"]', ()=>window.openSimulations?.());
  stop('[data-view="education"]', ()=>{setView('education');$('page-view').innerHTML='<div class="page"><h1 class="page-title">Education</h1><p class="page-subtitle">Study plans, explanations, exercises, programming, and project-linked learning belong here.</p></div>'});
  stop('[data-view="settings"]', ()=>{setView('settings');$('page-view').innerHTML=`<div class="page"><div class="page-head"><div><h1 class="page-title">Settings</h1><p class="page-subtitle">Personalize the workspace.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="ux-settings-row"><span>Theme</span><select id="theme-setting"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div></div>`;const s=$('#theme-setting');s.value=localStorage.getItem('pas-theme')||'system';s.onchange=()=>{localStorage.setItem('pas-theme',s.value);applyTheme();};});

  document.addEventListener('contextmenu', event => { const row=event.target.closest('.file-row'); if(!row||!state.projectId)return; event.preventDefault(); event.stopImmediatePropagation(); state.selected.clear(); state.selected.add(token(row.dataset.kind,row.dataset.id)); updateSelectionCount(); contextMenu(event.clientX,event.clientY,row.dataset.kind,Number(row.dataset.id),row.dataset.name); }, true);
  document.addEventListener('click', event => { if(!event.target.closest('.ux-context-menu'))document.querySelector('.ux-context-menu')?.remove(); const back=event.target.closest('[data-back-chat]'); if(back){event.preventDefault();openChat(state.chatId)} const major=event.target.closest('[data-major-page]'); if(major){event.preventDefault();openCalculations(major.dataset.majorPage)} const projectChat=event.target.closest('#project-chat-button'); if(projectChat&&state.projectId){event.preventDefault();openChat(state.chatId)} const logout=event.target.closest('#logout-action'); if(logout){event.preventDefault();(async()=>{try{await send('/api/auth/logout',{});state.user=null;closeModal();await refreshAuth();notify('Logged out.','ok')}catch(error){notify(error.message)}})()} }, true);
  document.addEventListener('keydown', event => { if(event.key==='Escape')document.querySelector('.ux-context-menu')?.remove(); if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='n'&&!event.target.matches('input,textarea')){event.preventDefault();draftChat();} });
  window.addEventListener('load',()=>{try{state.projectId=null;state.project=null;state.folderId=null;state.chatId=null;setView('chat');$('project-tools').hidden=true;}catch{}},{once:true});
})();