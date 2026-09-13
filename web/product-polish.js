(() => {
  const $ = (id) => document.getElementById(id);
  const escHtml = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const markdown = (raw) => {
    const safe = escHtml(raw);
    const blocks = safe.split(/```/g);
    return blocks.map((block, index) => index % 2 ? `<pre class="chat-code"><code>${block}</code></pre>` : block.split('\n').map((line) => {
      if (/^### /.test(line)) return `<h3>${line.slice(4)}</h3>`;
      if (/^## /.test(line)) return `<h2>${line.slice(3)}</h2>`;
      if (/^# /.test(line)) return `<h1>${line.slice(2)}</h1>`;
      if (/^\s*[-*] /.test(line)) return `<li>${line.replace(/^\s*[-*] /,'')}</li>`;
      return line ? `<p>${line.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\!\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g,'<img class="chat-image" alt="$1" src="$2">').replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')}</p>` : '';
    }).join('')).join('');
  };
  const renderMessages = (messages, toolEvents = []) => {
    const box = $('chat-messages'); if (!box) return;
    box.innerHTML = messages.map((m) => {
      if (m.role === 'user') return `<article class="message user"><div class="user-bubble">${escHtml(m.content)}</div><div class="message-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="edit">Edit</button></div></article>`;
      if (m.role !== 'assistant') return '';
      return `<article class="message assistant"><div class="content">${markdown(m.content)}</div><div class="assistant-tools">${toolEvents.length ? `<button class="tool-accordion" data-tools-toggle>Used ${toolEvents.length} tool${toolEvents.length===1?'':'s'}: ${toolEvents.slice(0,2).map((x)=>escHtml(x.label)).join(', ')}${toolEvents.length>2 ? `, and ${toolEvents.length-2} more` : ''}<span>⌄</span></button><div class="tool-log" hidden>${toolEvents.map((x)=>`<div class="tool-event ${escHtml(x.status)}"><span>${x.status==='success'?'✓':x.status==='error'?'!':'•'}</span><strong>${escHtml(x.label)}</strong><span>${escHtml(x.details||'')}</span>${x.tool==='search_project_sources'?'<span class="tool-chip">fetch</span>':''}</div>`).join('')}</div>` : ''}<div class="assistant-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="retry">Retry</button><button data-msg-action="branch">Branch</button><button data-msg-action="rate-up">↑</button><button data-msg-action="rate-down">↓</button></div></div></article>`;
    }).join('') || `<div class="welcome-card"><h2>What are you working on?</h2><p>Start a conversation, attach project material, or ask the assistant to use a calculator or simulator.</p></div>`;
    requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
  };
  const modelFor = () => ({auto:'profile:auto',claude:'profile:claude-opus',gpt:'profile:gpt-5.4',gemini:'profile:gemini-3.1-pro',free:'profile:free'}[$('ai-mode')?.value||'auto'] || 'profile:auto');
  const draft = () => {
    state.chatId = null; setView('chat');
    if ($('project-tools')) $('project-tools').hidden=!state.projectId;
    if ($('chat-title')) $('chat-title').textContent='New chat';
    if ($('chat-context')) $('chat-context').textContent='';
    if ($('chat-messages')) $('chat-messages').innerHTML='<div class="welcome-card"><h2>What are you working on?</h2><p>Start a new conversation or open a project.</p></div>';
    $('chat-input')?.focus();
  };
  const saveTitle = async () => {
    if (!state.chatId) return;
    const value = prompt('Chat name', $('chat-title')?.textContent || 'New chat'); if (value == null) return;
    await patch(`/api/chats/${state.chatId}`, { title: value });
    $('chat-title').textContent=value.trim(); await loadChats();
  };
  const chatMenu = (x, y) => {
    document.querySelector('.chat-menu')?.remove(); const menu=document.createElement('div'); menu.className='chat-menu';
    menu.style.left=`${Math.max(8,Math.min(x,innerWidth-250))}px`; menu.style.top=`${Math.max(8,Math.min(y,innerHeight-280))}px`;
    [['Rename','rename'],['Pin','pin'],['Move to project','move'],['Share chat','share'],['Delete','delete']].forEach(([label,action])=>{const b=document.createElement('button');b.textContent=label;b.dataset.chatAction=action;menu.appendChild(b)});
    document.body.appendChild(menu); menu.querySelector('button')?.focus();
  };
  const doChatAction = async (action) => {
    if (!state.chatId) return;
    if (action==='rename') return saveTitle();
    if (action==='pin'){const chat=await api(`/api/chats/${state.chatId}`);await patch(`/api/chats/${state.chatId}`,{pinned:!chat.pinned});await loadChats();return;}
    if (action==='move'){const projects=await api('/api/projects');const choice=prompt(`Project ID (blank = personal)\n${projects.map((p)=>`${p.id}: ${p.name}`).join('\n')}`);const projectId=choice?.trim()?Number(choice):null;await patch(`/api/chats/${state.chatId}`,{project_id:projectId});await loadChats();return;}
    if (action==='share'){const url=location.href;if(navigator.share)await navigator.share({title:$('chat-title')?.textContent||'Chat',url});else await navigator.clipboard.writeText(url);return;}
    if (action==='delete'){if(!confirm('Delete this chat?'))return;await del(`/api/chats/${state.chatId}`);draft();await loadChats();}
  };
  const openProjectsPage = async () => {
    setView('projects'); const projects=await api('/api/projects');
    $('page-view').innerHTML=`<div class="page project-home"><h1 class="page-title">Projects</h1><h2>Looking to start a project?</h2><p>Upload materials, set custom instructions, and organize conversations in one space.</p><button id="create-project-page" class="primary-button">Create project</button>${projects.length?`<div class="project-grid">${projects.map((p)=>`<button class="page-card" data-open-project="${p.id}"><strong>${escHtml(p.name)}</strong><span>${escHtml(p.description||'')}</span></button>`).join('')}</div>`:''}</div>`;
    $('create-project-page').onclick=async()=>{const name=prompt('Project name');if(!name?.trim())return;const r=await send('/api/projects',{name:name.trim()});await openProject(r.id)};
  };
  const openSettingsPage = () => {
    setView('settings');
    $('page-view').innerHTML=`<div class="page settings-page"><h1 class="page-title">Preferences</h1><section class="settings-card"><h2>Web & Desktop Interface</h2><label>Appearance<select id="pref-theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label>Memory<select><option>On</option><option>Off</option><option>Project-only</option></select></label><label>Tool connectors<select><option>Allowed</option><option>Ask first</option><option>Disabled</option></select></label><label>Model selection<select id="pref-model"><option value="auto">Auto</option><option value="claude">Claude Opus 5</option><option value="gpt">GPT-5.4</option><option value="gemini">Gemini 3.1 Pro</option><option value="free">Free routing</option></select></label><label>Thinking / effort<select><option>Adaptive</option><option>Low</option><option>Medium</option><option>High</option></select></label><label>Notifications & privacy<select><option>Default</option><option>Private</option></select></label></section><section class="settings-card"><h2>Claude Code / CLI</h2><label>Always thinking<select><option>Default</option><option>On</option><option>Off</option></select></label><label>Auto mode<select><option>On</option><option>Off</option></select></label><label>Auto memory<select><option>On</option><option>Off</option></select></label><label>Auto compact<select><option>On</option><option>Off</option></select></label><label>Auto scroll<select><option>On</option><option>Off</option></select></label><label>Managed permission rules<select><option>Enforced</option><option>Relaxed</option></select></label><label>Allowed managed hooks<select><option>Only managed</option><option>All</option></select></label></section></div>`;
    const theme=$('pref-theme');theme.value=localStorage.getItem('pas-theme')||'system';theme.onchange=()=>{localStorage.setItem('pas-theme',theme.value);applyTheme()};
    const model=$('pref-model');model.value=localStorage.getItem('pas-model')||'auto';model.onchange=()=>{localStorage.setItem('pas-model',model.value);if($('ai-mode'))$('ai-mode').value=model.value};
  };
  const decorate = () => {
    $('brand-home')?.remove(); $('format-toggle')?.remove(); $('format-toolbar')?.remove(); if($('chat-context'))$('chat-context').textContent='';
    const title=$('chat-title'); if(title&&!title.dataset.decorated){title.dataset.decorated='1';title.title='Click to rename';title.addEventListener('click',saveTitle)}
    const header=$('chat-header'); if(header&&!header.querySelector('.chat-title-menu')){const b=document.createElement('button');b.className='chat-title-menu';b.textContent='⌄';b.title='Chat actions';b.onclick=(e)=>{e.stopPropagation();chatMenu(e.clientX,e.clientY)};header.querySelector('.header-actions')?.prepend(b)}
    const sidebar=$('sidebar'); if(sidebar&&!sidebar.querySelector('.account-dock')){const dock=document.createElement('button');dock.className='account-dock';dock.onclick=openSettingsPage;dock.innerHTML='<span class="account-avatar">?</span><span class="account-name">Account</span>';sidebar.appendChild(dock)}
    if($('ai-mode')&&!$('ai-mode').dataset.enhanced){$('ai-mode').dataset.enhanced='1';$('ai-mode').innerHTML='<option value="auto">Auto</option><option value="claude">Claude Opus 5</option><option value="gpt">GPT-5.4</option><option value="gemini">Gemini 3.1 Pro</option><option value="free">Free</option>';$('ai-mode').value=localStorage.getItem('pas-model')||'auto'}
    if(state.user){const dock=sidebar?.querySelector('.account-dock');if(dock){const name=state.user.display_name||state.user.email||'Account';const initials=name.split(/\s+/).filter(Boolean).slice(0,2).map((x)=>x[0]).join('').toUpperCase()||'?';dock.querySelector('.account-avatar').textContent=initials;dock.querySelector('.account-name').textContent=name}}
  };
  document.addEventListener('click',async(event)=>{
    const target=event.target.closest?.('[data-tools-toggle], [data-msg-action], [data-chat-action], .chat-row, [data-view="projects"], [data-view="settings"], [data-view="chat"], #new-chat, #new-chat-header, #calculations-toggle, [data-major-page], #menu-toggle');
    if(!target)return; event.preventDefault();event.stopImmediatePropagation();
    try {
      if(target.matches('#menu-toggle')){document.body.classList.toggle('nav-open');return}
      if(target.matches('[data-tools-toggle]')){const log=target.nextElementSibling;log.hidden=!log.hidden;return}
      if(target.matches('[data-msg-action]')){const action=target.dataset.msgAction;const article=target.closest('.message');const text=article?.querySelector('.content,.user-bubble')?.textContent||'';if(action==='copy')await navigator.clipboard.writeText(text);else if(action==='share'){if(navigator.share)await navigator.share({text});else await navigator.clipboard.writeText(text)}else if(action==='edit'){ $('chat-input').value=text;$('chat-input').focus()}else if(action==='retry'){ $('chat-input').value=text;await $('chat-form').requestSubmit()}else if(action==='branch'){const r=await send('/api/chats',{project_id:state.projectId,title:'Branch'});state.chatId=r.id;$('chat-input').value=text;await $('chat-form').requestSubmit()}return}
      if(target.matches('[data-chat-action]')){await doChatAction(target.dataset.chatAction);document.querySelector('.chat-menu')?.remove();return}
      if(target.matches('.chat-row')){state.chatId=Number(target.dataset.chatId);await openChat(state.chatId);const chat=await api(`/api/chats/${state.chatId}`);renderMessages(chat.messages);return}
      if(target.matches('[data-view="projects"]')){await openProjectsPage();return}
      if(target.matches('[data-view="settings"]')){await openSettingsPage();return}
      if(target.matches('[data-view="chat"], #new-chat, #new-chat-header')){draft();return}
      if(target.matches('#calculations-toggle')){const nav=$('#calculation-categories');if(nav){const hidden=nav.hidden;nav.hidden=!hidden;if(hidden){const majors=await api('/api/calculations/majors');nav.innerHTML=majors.map((m)=>`<button data-major-page="${escHtml(m.name)}">${escHtml(m.name)}</button>`).join('')}}return}
      if(target.matches('[data-major-page]')){await openCalculations(target.dataset.majorPage);return}
    } catch(error){notify(error.message)}
  },true);
  document.addEventListener('submit',async(event)=>{if(event.target.id!=='chat-form')return;event.preventDefault();event.stopImmediatePropagation();try{const input=$('chat-input');const content=input.value.trim();if(!content)return;if(!state.chatId){const r=await send('/api/chats',{project_id:state.projectId});state.chatId=r.id}input.value='';$('send-chat').disabled=true;const selected=$('ai-mode')?.value||'auto';const result=await send(`/api/chats/${state.chatId}/messages`,{content,mode:'auto',model:modelFor()});renderMessages(result.messages,result.tool_events||[]);if(result.title)$('chat-title').textContent=result.title;await loadChats()}catch(error){notify(error.message)}finally{$('send-chat').disabled=false}},true);
  document.addEventListener('keydown',(event)=>{const typing=event.target.matches?.('input,textarea,[contenteditable="true"]');if((event.ctrlKey||event.metaKey)&&['o','k'].includes(event.key.toLowerCase())&&!typing){event.preventDefault();event.stopImmediatePropagation();draft()}if(event.key==='Escape')document.querySelector('.chat-menu')?.remove();if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='/'&&!typing){event.preventDefault();openSettingsPage()}if(!typing&&event.key.toLowerCase()==='p'&&document.querySelector('.chat-menu'))doChatAction('pin').catch((e)=>notify(e.message));if(!typing&&event.key.toLowerCase()==='r'&&document.querySelector('.chat-menu'))doChatAction('rename').catch((e)=>notify(e.message));if(!typing&&event.key.toLowerCase()==='d'&&document.querySelector('.chat-menu'))doChatAction('delete').catch((e)=>notify(e.message))},true);
  document.addEventListener('contextmenu',(event)=>{const row=event.target.closest?.('.chat-row');if(!row)return;event.preventDefault();event.stopImmediatePropagation();state.chatId=Number(row.dataset.chatId);chatMenu(event.clientX,event.clientY)},true);
  const observer=new MutationObserver(decorate);observer.observe(document.body,{subtree:true,childList:true});window.addEventListener('load',decorate,{once:true});
  window.__pasRenderMessages=renderMessages;window.__pasDraftChat=draft;
})();
