(() => {
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const valueOf = (target) => target?.value ?? '';
  const modelProfile = (value) => ({ auto:'profile:auto', claude:'profile:claude-opus', gpt:'profile:gpt-5.4', gemini:'profile:gemini-3.1-pro', free:'profile:free' }[value] || 'profile:auto');
  const toast = (message, ok = false) => { if (window.showError && !ok) return window.showError(new Error(String(message))); const node=document.createElement('div'); node.className=`ui-toast ${ok?'ok':'error'}`; node.textContent=String(message); document.body.appendChild(node); setTimeout(()=>node.remove(), 3600); };
  const copyText = async (text) => { await navigator.clipboard.writeText(text); toast('Copied.', true); };
  const openModal = (title, body) => { if (typeof modal === 'function') modal(title, body); };
  const close = () => { if (typeof closeModal === 'function') closeModal(); };

  const renderMessages = (messages, events = []) => {
    const box=$('chat-messages'); if (!box) return;
    const visible = messages.filter((m) => m.role === 'user' || m.role === 'assistant');
    box.innerHTML = visible.map((m, index) => {
      if (m.role === 'user') return `<article class="message user" data-message-index="${index}"><div class="user-bubble">${escapeHtml(m.content)}</div><div class="message-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="edit">Edit</button></div></article>`;
      const priorUser = [...visible.slice(0,index)].reverse().find((item) => item.role === 'user')?.content || '';
      const ratingKey = state.chatId ? `pas-rating-${state.chatId}-${index}` : '';
      const rating = ratingKey ? localStorage.getItem(ratingKey) : '';
      return `<article class="message assistant" data-message-index="${index}" data-retry-prompt="${escapeHtml(priorUser)}"><div class="content">${renderMarkdown(m.content)}</div>${events.length && index === visible.length - 1 ? renderTools(events) : ''}<div class="assistant-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="retry">Retry</button><button data-msg-action="branch">Branch</button><button data-msg-action="rate-up" aria-pressed="${rating==='up'}">${rating==='up'?'Rated':'↑'}</button><button data-msg-action="rate-down" aria-pressed="${rating==='down'}">${rating==='down'?'Rated':'↓'}</button></div></article>`;
    }).join('') || `<div class="welcome-card"><div class="welcome-mark">✦</div><h2>What are you working on?</h2><p>Ask an engineering question, inspect project material, run a deterministic calculation, or start a simulation.</p></div>`;
    requestAnimationFrame(()=>{box.scrollTop=box.scrollHeight;});
  };
  const renderMarkdown = (raw) => {
    const safe=escapeHtml(raw);
    return safe.split(/```/g).map((block,i)=>i%2?`<pre class="chat-code"><code>${block}</code></pre>`:block.split(/\n/).map(line=>{
      if (/^### /.test(line)) return `<h3>${line.slice(4)}</h3>`;
      if (/^## /.test(line)) return `<h2>${line.slice(3)}</h2>`;
      if (/^# /.test(line)) return `<h1>${line.slice(2)}</h1>`;
      if (/^\s*[-*] /.test(line)) return `<li>${line.replace(/^\s*[-*] /,'')}</li>`;
      return line ? `<p>${line.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\!\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g,'<img class="chat-image" alt="$1" src="$2">').replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')}</p>` : '';
    }).join('')).join('');
  };
  const renderTools = (events) => `<div class="assistant-tools"><button class="tool-accordion" data-tools-toggle>Used ${events.length} tool${events.length===1?'':'s'}<span>⌄</span></button><div class="tool-log" hidden>${events.map((event)=>`<div class="tool-event ${escapeHtml(event.status)}"><strong>${escapeHtml(event.label || event.tool || 'Tool')}</strong><span>${escapeHtml(event.details || '')}</span>${Array.isArray(event.sources)&&event.sources.length?`<button type="button" class="tool-fetch" data-tool-fetch='${escapeHtml(JSON.stringify(event.sources))}'>fetch</button>`:''}</div>`).join('')}</div></div>`;

  const sendMessage = async (content, modelOverride) => {
    content=String(content||'').trim(); if (!content) return;
    if (!state.chatId) { const created=await send('/api/chats',{project_id:state.projectId}); state.chatId=created.id; }
    const input=$('chat-input');
    const mode=$('ai-mode')?.value || localStorage.getItem('pas-model') || 'auto';
    localStorage.setItem('pas-model',mode);
    if (input) { input.value=''; input.style.height=''; input.disabled=true; }
    $('send-chat')?.classList.add('is-loading');
    const box=$('chat-messages');
    if (box) box.insertAdjacentHTML('beforeend',`<article class="message user pending-message"><div class="user-bubble">${escapeHtml(content)}</div></article><article class="message assistant thinking-message"><div class="thinking-indicator"><span></span><span></span><span></span><em>Thinking…</em></div></article>`);
    const controller=new AbortController(); window.__pasActiveChatRequest=controller;
    try {
      const result=await api(`/api/chats/${state.chatId}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,mode:'auto',model:modelOverride || modelProfile(mode)}),signal:controller.signal});
      renderMessages(result.messages || [], result.tool_events || []); if ($('chat-title')) $('chat-title').textContent=result.title || 'New chat'; await loadChats();
    } catch(error) {
      if (error?.name==='AbortError') toast('Generation stopped.', true); else toast(error?.message || 'Unable to send message.');
      if (input) input.value=content;
    } finally {
      document.querySelectorAll('.pending-message,.thinking-message').forEach((n)=>n.remove());
      if (window.__pasActiveChatRequest===controller) window.__pasActiveChatRequest=null;
      if (input) { input.disabled=false; input.focus(); }
      $('send-chat')?.classList.remove('is-loading');
    }
  };

  const chatMenu = (x,y) => {
    document.querySelector('.production-chat-menu')?.remove();
    const menu=document.createElement('div'); menu.className='production-chat-menu ux-context-menu'; menu.style.left=`${Math.max(8,Math.min(x,innerWidth-250))}px`; menu.style.top=`${Math.max(8,Math.min(y,innerHeight-260))}px`;
    [['Rename','rename'],['Pin / unpin','pin'],['Move to project','move'],['Share chat','share'],['Delete','delete']].forEach(([label,action])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.productionChatAction=action;menu.appendChild(b);});
    document.body.appendChild(menu);
  };
  const chatAction = async (action) => {
    if (!state.chatId) return;
    if (action==='rename') { const title=prompt('Chat name',$('chat-title')?.textContent||'New chat'); if (title?.trim()) { await patch(`/api/chats/${state.chatId}`,{title:title.trim()}); $('chat-title').textContent=title.trim(); await loadChats(); } }
    if (action==='pin') { const chat=await api(`/api/chats/${state.chatId}`); await patch(`/api/chats/${state.chatId}`,{pinned:!chat.pinned}); await loadChats(); toast(chat.pinned?'Unpinned.':'Pinned.',true); }
    if (action==='move') { const projects=await api('/api/projects'); const choice=prompt(`Enter project ID, or leave blank for personal.\n${projects.map(p=>`${p.id}: ${p.name}`).join('\n')}`); const projectId=choice?.trim()?Number(choice):null; if (choice!==null) { await patch(`/api/chats/${state.chatId}`,{project_id:Number.isFinite(projectId)?projectId:null}); await loadChats(); } }
    if (action==='share') { const payload={title:$('chat-title')?.textContent||'Chat',text:`Personal AI chat ${state.chatId}`,url:location.href}; if (navigator.share) await navigator.share(payload); else await copyText(location.href); }
    if (action==='delete') { if (!confirm('Delete this chat?')) return; await del(`/api/chats/${state.chatId}`); if (typeof __pasDraftChat==='function') __pasDraftChat(); else { state.chatId=null; $('chat-title').textContent='New chat'; } await loadChats(); }
  };

  const settingsPage = () => {
    setView('settings');
    $('page-view').innerHTML=`<div class="page settings-page"><div class="page-head"><div><h1 class="page-title">Settings</h1><p class="page-subtitle">Control the workspace without changing its engineering safety boundaries.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="settings-card"><h2>Appearance</h2><label>Theme<select id="production-theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label>Model<select id="production-model"><option value="auto">Auto</option><option value="claude">Claude Opus 5</option><option value="gpt">GPT-5.4</option><option value="gemini">Gemini 3.1 Pro</option><option value="free">Free routing</option></select></label><label>Memory<select id="production-memory"><option value="on">On</option><option value="off">Off</option><option value="project">Project only</option></select></label><label>Tool activity<select id="production-tools"><option value="on">Show</option><option value="off">Hide</option></select></label></div><div class="settings-card"><h2>Keyboard</h2><p><kbd>Ctrl+O</kbd> new chat · <kbd>Ctrl+K</kbd> search · <kbd>Ctrl+/</kbd> settings · <kbd>Shift+Enter</kbd> newline · <kbd>Enter</kbd> send</p></div><div class="settings-card"><h2>Safety</h2><p>Engineering calculations and simulations remain deterministic tools. Project files, notes, and ingested sources are treated as untrusted data. Consequential actions stay behind explicit user actions.</p></div></div>`;
    const theme=$('production-theme'); const model=$('production-model'); const memory=$('production-memory'); const tools=$('production-tools');
    theme.value=localStorage.getItem('pas-theme')||'system'; model.value=localStorage.getItem('pas-model')||'auto'; memory.value=localStorage.getItem('pas-memory')||'on'; tools.value=localStorage.getItem('pas-tools')||'on';
    theme.onchange=()=>{localStorage.setItem('pas-theme',theme.value); if (typeof applyTheme==='function') applyTheme();};
    model.onchange=()=>{localStorage.setItem('pas-model',model.value); if ($('ai-mode')) $('ai-mode').value=model.value;};
    memory.onchange=()=>localStorage.setItem('pas-memory',memory.value);
    tools.onchange=()=>localStorage.setItem('pas-tools',tools.value);
  };

  const educationPage = () => {
    setView('education');
    const plan=JSON.parse(localStorage.getItem('pas-education-plan')||'[]');
    $('page-view').innerHTML=`<div class="page"><div class="page-head"><div><h1 class="page-title">Education</h1><p class="page-subtitle">Build a study loop that uses explanations, retrieval practice, and progressively harder engineering work.</p></div><button class="primary-button" id="education-add">Add study goal</button></div><div class="card-grid"><div class="page-card"><h3>Study goals</h3><div id="education-goals">${plan.length?plan.map((item,i)=>`<div class="property"><strong>${escapeHtml(item)}</strong><button type="button" data-education-remove="${i}">Remove</button></div>`).join(''):'No study goals yet.'}</div></div><div class="page-card"><h3>Start a session</h3><p>Use the chat with a focused prompt and project context.</p><button class="outline-button" id="education-session">Open study chat</button></div></div></div>`;
    $('education-add').onclick=()=>{const goal=prompt('Study goal');if(!goal?.trim())return;plan.push(goal.trim());localStorage.setItem('pas-education-plan',JSON.stringify(plan));educationPage();};
    $('education-session').onclick=()=>{state.view='chat';setView('chat');$('chat-input').value='Teach me one concept step-by-step, then quiz me without giving away the answer.';$('chat-input').focus();};
    document.querySelectorAll('[data-education-remove]').forEach((b)=>b.onclick=()=>{plan.splice(Number(b.dataset.educationRemove),1);localStorage.setItem('pas-education-plan',JSON.stringify(plan));educationPage();});
  };

  const globalSearch = async (query) => {
    const q=String(query||'').trim(); if (!q) return;
    const [chats,projects]=await Promise.all([api('/api/chats'),api('/api/projects')]);
    const chatHits=chats.filter(c=>String(c.title).toLowerCase().includes(q.toLowerCase()));
    const projectHits=projects.filter(p=>String(p.name).toLowerCase().includes(q.toLowerCase()));
    openModal('Search results',`<div class="search-results"><h3>Chats</h3>${chatHits.map(c=>`<button class="search-hit" data-search-chat="${c.id}">${escapeHtml(c.title)}</button>`).join('')||'<p class="muted">No chat matches.</p>'}<h3>Projects</h3>${projectHits.map(p=>`<button class="search-hit" data-search-project="${p.id}">${escapeHtml(p.name)}</button>`).join('')||'<p class="muted">No project matches.</p>'}</div>`);
  };

  window.__pasRenderMessages = renderMessages;

  window.addEventListener('submit', (event) => {
    if (event.target?.id !== 'chat-form') return;
    event.preventDefault(); event.stopImmediatePropagation();
    const input=$('chat-input'); sendMessage(valueOf(input)).catch((e)=>toast(e.message));
  }, true);
  window.addEventListener('click', (event) => {
    const target=event.target.closest?.('#send-chat.is-loading,[data-msg-action],[data-tools-toggle],[data-tool-fetch],[data-production-chat-action],.production-chat-menu button,#menu-toggle,#new-chat,#new-chat-header,#login-button,#signup-button,#account-button,[data-view],[data-major-page],[data-open-project],.chat-row,#calculations-toggle,#project-files,#project-calculations,#project-simulations,#project-engineering,#clear-chat-list,.source-card,[data-back-chat]');
    if (!target) return;
    if (target.matches('#send-chat.is-loading')) { event.preventDefault(); event.stopImmediatePropagation(); window.__pasActiveChatRequest?.abort(); return; }
    event.preventDefault(); event.stopImmediatePropagation();
    Promise.resolve().then(async()=>{
      if (target.matches('#menu-toggle')) { document.body.classList.toggle('nav-open'); return; }
      if (target.matches('#new-chat,#new-chat-header,[data-view="chat"]')) { state.chatId=null; if(typeof setView==='function')setView('chat'); $('chat-title').textContent='New chat'; $('chat-context').textContent=state.projectId?`Project · ${state.project?.name||'Project'}`:''; if ($('chat-messages')) $('chat-messages').innerHTML='<div class="welcome-card"><div class="welcome-mark">✦</div><h2>What are you working on?</h2><p>Ask an engineering question, inspect project material, run a deterministic calculation, or start a simulation.</p></div>'; $('chat-input').focus(); return; }
      if (target.matches('[data-view="projects"]')) { return openProjects(); }
      if (target.matches('[data-view="education"]')) { return educationPage(); }
      if (target.matches('[data-view="simulations"]')) { return openSimulations(); }
      if (target.matches('[data-view="connections"]')) { return openConnections(); }
      if (target.matches('[data-view="settings"]')) { return settingsPage(); }
      if (target.matches('#calculations-toggle')) { const nav=$('calculation-categories'); const majors=await api('/api/calculations/majors'); nav.innerHTML=majors.map(m=>`<button type="button" data-major-page="${escapeHtml(m.name)}">${escapeHtml(m.name)}</button>`).join(''); nav.hidden=!nav.hidden; return; }
      if (target.matches('[data-major-page]')) { return openCalculations(target.dataset.majorPage); }
      if (target.matches('.chat-row')) { state.chatId=Number(target.dataset.chatId); await loadChat(); const chat=await api(`/api/chats/${state.chatId}`); renderMessages(chat.messages||[]); return; }
      if (target.matches('[data-open-project],.project-row')) { const id=Number(target.dataset.openProject||target.dataset.projectId); return openProject(id); }
      if (target.matches('#project-files')) return showProjectFiles();
      if (target.matches('#project-calculations')) return openCalculations();
      if (target.matches('#project-simulations')) return openSimulations();
      if (target.matches('#project-engineering')) return openProjectEngineering();
      if (target.matches('#clear-chat-list')) return loadChats();
      if (target.matches('#login-button')) return document.dispatchEvent(new MouseEvent('click',{bubbles:true}));
      if (target.matches('#signup-button')) return document.dispatchEvent(new MouseEvent('click',{bubbles:true}));
      if (target.matches('#account-button')) return openModal('Account',`<div class="form-stack"><div class="property"><span>Account</span><strong>${escapeHtml(state.user?.email||'Local workspace')}</strong></div><button type="button" class="outline-button" id="production-settings-open">Settings</button>${state.user?'<button type="button" class="outline-button" id="production-logout">Log out</button>':''}</div>`);
      if (target.matches('[data-back-chat]')) { if(state.chatId) return openChat(state.chatId); state.chatId=null; if(typeof setView==='function')setView('chat'); return; }
      if (target.matches('[data-msg-action]')) {
        const action=target.dataset.msgAction; const article=target.closest('.message'); const content=article?.querySelector('.content,.user-bubble')?.textContent||'';
        if(action==='copy') return copyText(content);
        if(action==='share') return navigator.share ? navigator.share({text:content}) : copyText(content);
        if(action==='edit'){ $('chat-input').value=content; $('chat-input').focus(); return; }
        if(action==='retry'){ const promptText=article?.dataset.retryPrompt||''; if(promptText){$('chat-input').value=promptText;return sendMessage(promptText);} return; }
        if(action==='branch'){ const promptText=article?.dataset.retryPrompt||content; const created=await send('/api/chats',{project_id:state.projectId,title:'Branch'}); state.chatId=created.id; await sendMessage(promptText); return; }
        if(action==='rate-up'||action==='rate-down'){ if(!state.chatId)return;const key=`pas-rating-${state.chatId}-${article?.dataset.messageIndex||''}`;localStorage.setItem(key,action==='rate-up'?'up':'down');renderMessages((await api(`/api/chats/${state.chatId}`)).messages||[]);return; }
      }
      if (target.matches('[data-tools-toggle]')) { const log=target.nextElementSibling; if(log)log.hidden=!log.hidden; return; }
      if (target.matches('[data-tool-fetch]')) { const sources=JSON.parse(target.dataset.toolFetch||'[]'); return openModal('Retrieved sources',sources.map(s=>`<div class="property"><strong>${escapeHtml(s.title||'Project source')}</strong><span>${escapeHtml(s.location||'')}</span></div>`).join('')||'<p>No source metadata.</p>'); }
      if (target.matches('.source-card')) return;
    }).catch((error)=>toast(error.message||error));
  }, true);
  window.addEventListener('contextmenu',(event)=>{const row=event.target.closest?.('.chat-row');if(!row)return;event.preventDefault();event.stopImmediatePropagation();state.chatId=Number(row.dataset.chatId);chatMenu(event.clientX,event.clientY);},true);
  window.addEventListener('click',(event)=>{const action=event.target.closest?.('[data-production-chat-action]');if(!action)return;event.preventDefault();event.stopImmediatePropagation();chatAction(action.dataset.productionChatAction).catch((e)=>toast(e.message)).finally(()=>document.querySelector('.production-chat-menu')?.remove());},true);
  window.addEventListener('keydown',(event)=>{
    const typing=event.target.matches?.('input,textarea,[contenteditable="true"]'); const key=event.key.toLowerCase();
    if((event.ctrlKey||event.metaKey)&&key==='o'&&!typing){event.preventDefault();event.stopImmediatePropagation();state.chatId=null;setView('chat');$('chat-title').textContent='New chat';$('chat-input').focus();}
    if((event.ctrlKey||event.metaKey)&&key==='k'){event.preventDefault();event.stopImmediatePropagation();$('global-search')?.focus();}
    if((event.ctrlKey||event.metaKey)&&key==='/'&&!typing){event.preventDefault();event.stopImmediatePropagation();settingsPage();}
    if((key==='p'||key==='r'||key==='d')&&!typing&&document.querySelector('.production-chat-menu')){event.preventDefault();event.stopImmediatePropagation();chatAction({p:'pin',r:'rename',d:'delete'}[key]).catch((e)=>toast(e.message));}
    if(key==='escape'){document.querySelectorAll('.production-chat-menu,.ux-context-menu').forEach((n)=>n.remove());}
  },true);
  $('global-search')?.addEventListener('keydown',(event)=>{if(event.key==='Enter'){globalSearch(event.target.value).catch((e)=>toast(e.message));}});
  window.addEventListener('load',()=>{try{if($('ai-mode'))$('ai-mode').value=localStorage.getItem('pas-model')||'auto';}catch{}},{once:true});
})();
