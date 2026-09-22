/* app.js — state, API calls, canonical interactions, and one chat send/render path. */
(() => {
  'use strict';

  const state = {
    view: 'chat', chatId: null, projectId: null, folderId: null,
    calcMajor: null, calcKey: null, project: null, user: null,
    items: [], selected: new Set(), sort: 'none', clipboard: [],
    manifest: null, calculationCatalog: [], simulationKey: null,
  };

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const attr = (value) => escapeHtml(value).replace(/'/g, '&#39;');
  const token = (kind, id) => `${kind}:${id}`;
  const selectedItems = () => [...state.selected].map((value) => {
    const [kind, id] = value.split(':');
    return { kind, id: Number(id) };
  });
  const modelProfile = (value) => ({
    auto: 'profile:auto', claude: 'profile:claude-opus', gpt: 'profile:gpt-5.4',
    gemini: 'profile:gemini-3.1-pro', free: 'profile:free',
  }[value] || 'profile:auto');

  const api = async (path, options = {}) => {
    const response = await fetch(path, { credentials: 'same-origin', ...options });
    const data = await response.json().catch(() => ({ error: 'Invalid server response' }));
    if (!response.ok) {
      const error = new Error(data.error || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  };
  const send = (path, payload, options = {}) => api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), ...options,
  });
  const patch = (path, payload) => api(path, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const del = (path, payload = {}) => api(path, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });

  function toast(message, type = 'error') {
    let stack = document.querySelector('.toast-stack');
    if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; document.body.appendChild(stack); }
    const item = document.createElement('div'); item.className = `toast ${type}`; item.textContent = String(message || 'Something went wrong.');
    stack.appendChild(item); setTimeout(() => item.remove(), type === 'error' ? 5200 : 3200);
  }
  window.showError = (error) => toast(error?.message || error);
  const applyTheme = () => {
    const theme = localStorage.getItem('pas-theme') || 'system';
    document.body.classList.toggle('dark', theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches));
  };
  let lastFocused = null;
  const focusable = (root) => [...(root?.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])') || [])].filter((element) => !element.hidden && element.getClientRects().length);
  const syncAccessibility = () => {
    const sidebar = $('sidebar'); const toggle = $('menu-toggle'); if (!sidebar || !toggle) return;
    const mobile = matchMedia('(max-width: 900px)').matches; const open = document.body.classList.contains('nav-open');
    sidebar.setAttribute('aria-hidden', String(mobile && !open)); toggle.setAttribute('aria-expanded', String(open)); toggle.setAttribute('aria-controls', 'sidebar');
  };
  const closeSidebar = () => { document.body.classList.remove('nav-open'); syncAccessibility(); };
  const announce = (message) => {
    let live = $('a11y-live-region');
    if (!live) { live = document.createElement('div'); live.id = 'a11y-live-region'; live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true'); Object.assign(live.style, { position:'fixed', width:'1px', height:'1px', padding:'0', margin:'-1px', overflow:'hidden', clip:'rect(0 0 0 0)', whiteSpace:'nowrap', border:'0' }); document.body.appendChild(live); }
    live.textContent = String(message || '');
  };
  function bindAccessibility() {
    syncAccessibility();
    $('menu-toggle')?.addEventListener('click', () => { document.body.classList.toggle('nav-open'); syncAccessibility(); if (document.body.classList.contains('nav-open')) requestAnimationFrame(() => $('sidebar')?.querySelector('button:not([disabled])')?.focus()); });
    $('sidebar')?.addEventListener('click', (event) => { if (matchMedia('(max-width: 900px)').matches && event.target.closest('button[data-view], [data-major-page], [data-open-calculation-group], [data-open-calculation-subgroup]')) requestAnimationFrame(closeSidebar); });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Tab') {
        const dialog = $('modal'); const card = dialog?.querySelector('.modal-card');
        if (dialog && !dialog.hidden && card) { const items=focusable(card); if (items.length) { const first=items[0], last=items.at(-1); if (event.shiftKey && document.activeElement===first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement===last) { event.preventDefault(); first.focus(); } } }
      }
      if (event.key === 'Escape') closeSidebar();
    }, true);
    const modalNode = $('modal');
    if (modalNode) new MutationObserver(() => {
      if (!modalNode.hidden && !lastFocused) { lastFocused=document.activeElement; requestAnimationFrame(() => focusable(modalNode.querySelector('.modal-card'))[0]?.focus()); }
      if (modalNode.hidden && lastFocused) { const target=lastFocused; lastFocused=null; requestAnimationFrame(() => target?.isConnected && target.focus()); }
    }).observe(modalNode,{attributes:true,attributeFilter:['hidden']});
  }

  const setView = (view) => {
    if (state.view === 'planner' && view !== 'planner') {
      document.body.classList.remove('planner-focus');
      document.title = 'Engineering AI Workspace';
    }
    state.view = view;
    $('home-view').hidden = view !== 'chat';
    $('page-view').hidden = view === 'chat';
    document.querySelectorAll('.nav-item[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
    if (view !== 'chat') $('project-tools').hidden = true;
    if (view === 'planner') {
      document.body.classList.add('planner-focus');
      document.title = 'PASI Planner · Engineering Workspace';
    }
    syncAccessibility();
  };
  const modal = (title, body) => { $('modal-title').textContent=title; $('modal-body').innerHTML=body; $('modal').hidden=false; };
  const closeModal = () => { $('modal').hidden=true; };

  async function refreshAuth() {
    const result=await api('/api/auth/me'); state.user=result.user;
    $('login-button').hidden=!!state.user; $('signup-button').hidden=!!state.user; $('account-button').hidden=!state.user;
    if(state.user) $('account-button').textContent=state.user.display_name||state.user.email; window.renderAccountDock?.();
  }
  async function loadManifest() { state.manifest=await api('/api/manifest'); return state.manifest; }
  async function loadChats() {
    const query=state.projectId?`?project_id=${state.projectId}`:''; const chats=await api(`/api/chats${query}`);
    $('chat-list').innerHTML=chats.slice(0,18).map((chat)=>`<button class="chat-row" data-chat-id="${chat.id}">${escapeHtml(chat.title)}</button>`).join('')||'<div class="muted">No chats yet.</div>'; return chats;
  }
  async function loadProjects() { return api('/api/projects'); }
  async function loadChat(id=state.chatId) {
    if(!id){ $('chat-title').textContent='New chat'; $('chat-context').textContent=state.projectId?`Project · ${state.project?.name||'Project'}`:'Personal AI'; renderMessages([],[]); return null; }
    state.chatId=Number(id); const chat=await api(`/api/chats/${state.chatId}`); $('chat-title').textContent=chat.title||'Chat'; $('chat-context').textContent=state.projectId?`Project · ${state.project?.name||'Project'}`:'Personal AI'; renderMessages(chat.messages||[],[]); return chat;
  }
  async function createChat(projectId=state.projectId) { const created=await send('/api/chats',{project_id:projectId}); state.chatId=created.id; return created; }
  async function openChat(id) { state.chatId=Number(id); setView('chat'); $('project-tools').hidden=!state.projectId; await loadChat(state.chatId); }

  function markdown(raw) {
    const safe=escapeHtml(raw);
    return safe.split(/```/g).map((block,index)=>index%2?`<pre class="chat-code"><code>${block}</code></pre>`:block.split(/\n/).map((line)=>{
      if(/^### /.test(line)) return `<h3>${line.slice(4)}</h3>`; if(/^## /.test(line)) return `<h2>${line.slice(3)}</h2>`; if(/^# /.test(line)) return `<h1>${line.slice(2)}</h1>`;
      if(/^\s*[-*] /.test(line)) return `<li>${line.replace(/^\s*[-*] /,'')}</li>`;
      return line?`<p>${line.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\!\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g,'<img class="chat-image" alt="$1" src="$2">').replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')}</p>`:'';
    }).join('')).join('');
  }

  function renderMessages(messages, toolEvents=[]) {
    const box=$('chat-messages'); if(!box)return;
    const visible=(messages||[]).filter((message)=>message.role==='user'||message.role==='assistant'); let assistantIndex=0;
    box.innerHTML=visible.map((message,index)=>{
      if(message.role==='user') return `<article class="message user" data-message-index="${index}"><div class="user-bubble">${escapeHtml(message.content)}</div><div class="message-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="edit">Edit</button></div></article>`;
      const currentAssistantIndex=assistantIndex++; const priorUser=[...visible.slice(0,index)].reverse().find((item)=>item.role==='user')?.content||''; const ratingKey=state.chatId?`pas-rating-${state.chatId}-${currentAssistantIndex}`:''; const rating=ratingKey?localStorage.getItem(ratingKey):''; const showEvents=toolEvents.length&&index===visible.length-1;
      return `<article class="message assistant" data-message-index="${index}" data-assistant-index="${currentAssistantIndex}" data-retry-prompt="${attr(priorUser)}"><div class="content">${markdown(message.content)}</div>${showEvents?`<div class="assistant-tools"><button class="tool-accordion" data-tools-toggle>Used ${toolEvents.length} tool${toolEvents.length===1?'':'s'}<span>⌄</span></button><div class="tool-log" hidden>${toolEvents.map((event)=>`<div class="tool-event ${escapeHtml(event.status||'pending')}"><span>${event.status==='success'?'✓':event.status==='error'?'!':'•'}</span><strong>${escapeHtml(event.label||event.tool||'Tool')}</strong><span>${escapeHtml(event.details||'')}</span>${Array.isArray(event.sources)&&event.sources.length?`<button type="button" class="tool-fetch" data-tool-fetch='${attr(JSON.stringify(event.sources))}'>fetch source</button>`:''}</div>`).join('')}</div></div>`:''}<div class="assistant-actions"><button data-msg-action="copy">Copy</button><button data-msg-action="share">Share</button><button data-msg-action="retry">Retry</button><button data-msg-action="branch">Branch</button><button data-msg-action="rate-up" aria-pressed="${rating==='up'}">${rating==='up'?'Rated':'↑'}</button><button data-msg-action="rate-down" aria-pressed="${rating==='down'}">${rating==='down'?'Rated':'↓'}</button></div></article>`;
    }).join('')||`<div class="welcome-card"><div class="welcome-mark">✦</div><h2>What are you working on?</h2><p>Ask an engineering question, inspect project material, run a deterministic calculation, or start a simulation.</p><div class="prompt-grid"><button type="button" data-prompt="Build a transparent engineering model for this problem and identify the assumptions.">Model an engineering problem</button><button type="button" data-prompt="Explain this like a tutor, then give me progressively harder practice problems.">Study something</button><button type="button" data-prompt="Digest the information I provide into claims, evidence, assumptions, and open questions.">Digest information</button></div></div>`;
    requestAnimationFrame(()=>{box.scrollTop=box.scrollHeight;});
  }

  function renderPending(content){ const box=$('chat-messages'); if(!box)return; box.querySelector('.welcome-card')?.remove(); box.insertAdjacentHTML('beforeend',`<article class="message user pending-message"><div class="user-bubble">${escapeHtml(content)}</div></article><article class="message assistant thinking-message"><div class="thinking-indicator"><span></span><span></span><span></span><em>Thinking…</em></div></article>`); requestAnimationFrame(()=>{box.scrollTop=box.scrollHeight;}); }

  async function sendMessage(content=$('chat-input')?.value,modelOverride=null){
    content=String(content||'').trim(); if(!content)return; if(!state.chatId)await createChat(state.projectId);
    const input=$('chat-input'); const selectedMode=$('ai-mode')?.value||localStorage.getItem('pas-model')||'auto'; localStorage.setItem('pas-model',selectedMode);
    if(input){input.value='';input.style.height='';input.disabled=true;} $('send-chat')?.classList.add('is-loading'); if($('send-chat'))$('send-chat').textContent='Stop'; renderPending(content);
    const controller=new AbortController(); window.__pasActiveChatRequest=controller;
    try{
      const result=await api(`/api/chats/${state.chatId}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,mode:'auto',model:modelOverride||modelProfile(selectedMode)}),signal:controller.signal});
      renderMessages(result.messages||[],result.tool_events||[]); if(result.title)$('chat-title').textContent=result.title; if(result.tool_events?.length)window.decorateSources?.(result.tool_events); await loadChats(); announce('Assistant response received.');
    }catch(error){ if(error?.name==='AbortError')toast('Generation stopped.','ok'); else toast(error?.message||'Unable to send message.'); if(input)input.value=content; }
    finally{document.querySelectorAll('.pending-message,.thinking-message').forEach((node)=>node.remove()); if(window.__pasActiveChatRequest===controller)window.__pasActiveChatRequest=null; if(input){input.disabled=false;input.focus();} $('send-chat')?.classList.remove('is-loading'); if($('send-chat'))$('send-chat').textContent='Send';}
  }
  function draftChat(){state.chatId=null;setView('chat');$('project-tools').hidden=!state.projectId;$('chat-title').textContent='New chat';$('chat-context').textContent=state.projectId?`Project · ${state.project?.name||'Project'}`:'Personal AI';renderMessages([],[]);$('chat-input').focus();}

  async function chatAction(action){
    if(!state.chatId)return;
    if(action==='rename'){const current=$('chat-title').textContent||'New chat';const value=window.prompt('Rename chat',current);if(value?.trim()){await patch(`/api/chats/${state.chatId}`,{title:value.trim()});$('chat-title').textContent=value.trim();await loadChats();}}
    else if(action==='pin'){const chat=await api(`/api/chats/${state.chatId}`);await patch(`/api/chats/${state.chatId}`,{pinned:!chat.pinned});await loadChats();toast(chat.pinned?'Unpinned.':'Pinned.','ok');}
    else if(action==='move'){const projects=await loadProjects();const raw=window.prompt(`Project ID (blank = personal)\n${projects.map((p)=>`${p.id}: ${p.name}`).join('\n')}`);if(raw!==null){const id=raw.trim()?Number(raw):null;if(raw.trim()&&!Number.isInteger(id))throw new Error('Project ID must be an integer.');await patch(`/api/chats/${state.chatId}`,{project_id:id});await loadChats();}}
    else if(action==='share'){const payload={title:$('chat-title').textContent||'Chat',text:`Personal AI chat ${state.chatId}`,url:location.href};if(navigator.share)await navigator.share(payload);else{await navigator.clipboard.writeText(location.href);toast('Chat link copied.','ok');}}
    else if(action==='delete'){if(!window.confirm('Delete this chat?'))return;await del(`/api/chats/${state.chatId}`);draftChat();await loadChats();}
  }
  function openChatMenu(x,y){document.querySelector('.chat-context-menu')?.remove();const menu=document.createElement('div');menu.className='chat-context-menu';menu.style.left=`${Math.max(8,Math.min(x,innerWidth-230))}px`;menu.style.top=`${Math.max(8,Math.min(y,innerHeight-210))}px`;[['Rename','rename'],['Pin / unpin','pin'],['Move to project','move'],['Share chat','share'],['Delete','delete']].forEach(([label,action])=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.chatAction=action;menu.appendChild(button);});document.body.appendChild(menu);menu.querySelector('button')?.focus();}

  async function openProjects(){setView('projects');const projects=await loadProjects();window.renderProjectsPage?.(projects);}
  async function createProject(){modal('New project','<form id="create-project-form" class="form-stack"><label>Name<input name="name" required></label><label>Description<textarea name="description" placeholder="What is this project for?"></textarea></label><div class="form-actions"><button type="button" class="outline-button" id="create-project-cancel">Cancel</button><button class="primary-button">Create</button></div></form>');$('create-project-cancel').onclick=closeModal;$('create-project-form').onsubmit=async(event)=>{event.preventDefault();try{const result=await send('/api/projects',Object.fromEntries(new FormData(event.target)));closeModal();await openProject(result.id);}catch(error){$('create-project-form').insertAdjacentHTML('afterend',`<div class="error">${escapeHtml(error.message)}</div>`);}};}
  async function openProject(id){state.projectId=Number(id);state.folderId=null;state.sort='none';state.selected.clear();state.project=await api(`/api/projects/${state.projectId}`);const chats=await api(`/api/chats?project_id=${state.projectId}`);state.chatId=chats[0]?.id||null;setView('chat');$('project-tools').hidden=false;$('project-chat-button').hidden=false;$('project-chat-button').textContent=state.project.name;$('chat-context').textContent=`Project · ${state.project.name}`;if(state.chatId)await loadChat();else draftChat();await loadChats();renderProjectTools();}
  async function editProject(){modal('Project details',`<form id="project-edit-form" class="form-stack"><label>Name<input name="name" value="${attr(state.project.name)}" required></label><label>Description<textarea name="description">${escapeHtml(state.project.description||'')}</textarea></label><div class="form-actions"><button type="button" class="outline-button" id="project-edit-cancel">Cancel</button><button class="primary-button">Save</button></div></form>`);$('project-edit-cancel').onclick=closeModal;$('project-edit-form').onsubmit=async(event)=>{event.preventDefault();try{state.project=await patch(`/api/projects/${state.projectId}`,Object.fromEntries(new FormData(event.target)));closeModal();$('chat-context').textContent=`Project · ${state.project.name}`;renderProjectTools();}catch(error){$('project-edit-form').insertAdjacentHTML('afterend',`<div class="error">${escapeHtml(error.message)}</div>`);}};}
  function renderProjectTools(){if(!state.project)return;$('project-files-panel').hidden=true;$('project-files-panel').innerHTML=`<div class="properties"><div class="property"><span>Project</span><strong>${escapeHtml(state.project.name)}</strong></div><div class="property"><span>Description</span><strong>${escapeHtml(state.project.description||'')||'No description'}</strong></div><div class="form-actions"><button id="edit-project" class="outline-button">Edit project</button><button id="delete-project" class="danger-button">Delete project</button></div></div>`;$('edit-project').onclick=editProject;$('delete-project').onclick=async()=>{if(!confirm('Delete this project and its project data?'))return;try{await del(`/api/projects/${state.projectId}`);state.projectId=null;state.project=null;state.folderId=null;state.chatId=null;$('project-tools').hidden=true;$('project-chat-button').hidden=true;draftChat();await loadChats();}catch(error){toast(error.message);}};}
  function sortLabel(value){return({none:'None',a_z:'A–Z',z_a:'Z–A',recent_old:'Recent → old',old_recent:'Old → recent',last_modified_new_old:'Modified → old',last_modified_old_new:'Old → modified'})[value]||value;}
  function applyLocalOrder(items){const key=`pas-order-${state.projectId}-${state.folderId||0}`;const raw=localStorage.getItem(key);if(!raw)return items;try{const order=JSON.parse(raw);const rank=new Map(order.map((value,index)=>[value,index]));return [...items].sort((a,b)=>(rank.get(token(a.kind,a.id))??999999)-(rank.get(token(b.kind,b.id))??999999));}catch{return items;}}
  async function showProjectFiles(){if(!state.projectId)return;const qs=new URLSearchParams({sort:state.sort});if(state.folderId)qs.set('folder_id',state.folderId);state.items=applyLocalOrder(await api(`/api/projects/${state.projectId}/items?${qs}`));const breadcrumbs=state.folderId?await api(`/api/projects/${state.projectId}/breadcrumbs?kind=folder&id=${state.folderId}`):[{kind:'project',id:state.projectId,name:state.project.name}];window.renderProjectFilesPage?.(breadcrumbs.at(-1)?.name||'Files & notes');window.bindProjectFilesInteractions?.();}
  async function openItem(kind,id){if(kind==='folder'){state.folderId=id;return showProjectFiles();}if(kind==='note'){const note=await api(`/api/projects/${state.projectId}/notes?id=${id}`);return editNote(note);}const file=await api(`/api/projects/${state.projectId}/files?id=${id}`);const binary=atob(file.data_base64);const bytes=Uint8Array.from(binary,(c)=>c.charCodeAt(0));const blob=new Blob([bytes],{type:file.mime_type||'application/octet-stream'});const url=URL.createObjectURL(blob);if((file.mime_type||'').startsWith('image/')){modal(file.name,`<img class="file-preview" src="${url}" alt="${attr(file.name)}"><div class="form-actions"><button class="outline-button" id="copy-image">Copy image</button><button class="outline-button" id="download-image">Download</button></div>`);$('copy-image').onclick=async()=>{try{await navigator.clipboard.write([new ClipboardItem({[blob.type]:blob})]);toast('Image copied.','ok');}catch(error){toast(`Image copy is unavailable: ${error.message}`);}};$('download-image').onclick=()=>downloadBlob(blob,file.name);}else{const text=file.mime_type?.startsWith('text/')?await blob.text():null;modal(file.name,text?`<pre class="text-preview">${escapeHtml(text)}</pre><div class="form-actions"><button class="outline-button" id="digest-file">Digest</button><button class="outline-button" id="download-file">Download</button></div>`:`<div class="property"><span>Type</span><strong>${escapeHtml(file.mime_type||'Unknown')}</strong></div><div class="form-actions"><button class="outline-button" id="download-file">Download</button></div>`);$('download-file').onclick=()=>downloadBlob(blob,file.name);$('digest-file')?.addEventListener('click',()=>digestText(text,file.name));}}
  function downloadBlob(blob,name){const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=name;document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function digestText(text,name){const clean=String(text||'').replace(/\s+/g,' ').trim();const sentences=clean.match(/[^.!?]+[.!?]+/g)||[clean];modal(`Digest · ${name}`,`<div class="property"><span>Summary</span><strong>${escapeHtml(sentences.slice(0,8).join(' ')||'No readable text found')}</strong></div><div class="property"><span>Signals</span><strong>Sentences: ${sentences.length} · Characters: ${clean.length}</strong></div>`);}
  function editNote(note){const metadata=note.metadata||{};modal('Edit note',`<div class="note-editor"><input id="note-title" value="${attr(note.name)}"><textarea id="note-description" placeholder="Description">${escapeHtml(metadata.description||'')}</textarea><textarea id="note-content" placeholder="Content">${escapeHtml(note.content||'')}</textarea><div class="form-actions"><button class="outline-button" id="delete-note">Delete</button><button class="primary-button" id="save-note">Save</button></div></div>`);$('save-note').onclick=async()=>{try{await patch(`/api/projects/${state.projectId}/notes`,{id:note.id,title:$('note-title').value,content:$('note-content').value,metadata:{...metadata,description:$('note-description').value}});closeModal();await showProjectFiles();}catch(error){toast(error.message);}};$('delete-note').onclick=async()=>{if(!confirm('Delete this note?'))return;try{await del(`/api/projects/${state.projectId}/notes`,{id:note.id});closeModal();await showProjectFiles();}catch(error){toast(error.message);}};}
  async function newItem(kind){modal(kind==='folder'?'New folder':'New note',`<form id="new-item-form" class="form-stack"><label>${kind==='folder'?'Name':'Title'}<input name="name" required></label>${kind==='note'?'<label>Description<textarea name="description"></textarea></label><label>Content<textarea name="content"></textarea></label>':''}<div class="form-actions"><button type="button" class="outline-button" id="new-item-cancel">Cancel</button><button class="primary-button">Create</button></div></form>`);$('new-item-cancel').onclick=closeModal;$('new-item-form').onsubmit=async(event)=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));try{if(kind==='folder')await send(`/api/projects/${state.projectId}/folders`,{name:values.name,parent_folder_id:state.folderId});else await send(`/api/projects/${state.projectId}/notes`,{title:values.name,content:values.content||'',folder_id:state.folderId,metadata:{description:values.description||''}});closeModal();await showProjectFiles();}catch(error){$('new-item-form').insertAdjacentHTML('afterend',`<div class="error">${escapeHtml(error.message)}</div>`);}};}
  function renameItem(kind,id,current){modal('Rename',`<form id="rename-form" class="form-stack"><label>Name<input id="rename-value" value="${attr(current)}" required></label><div class="form-actions"><button type="button" class="outline-button" id="rename-cancel">Cancel</button><button class="primary-button">Save</button></div></form>`);$('rename-cancel').onclick=closeModal;$('rename-form').onsubmit=async(event)=>{event.preventDefault();try{await send(`/api/projects/${state.projectId}/rename`,{kind,id,name:$('rename-value').value.trim()});closeModal();await showProjectFiles();}catch(error){toast(error.message);}};}
  async function uploadFile(file){if(!state.projectId){toast('Open a project to attach a file.');return;}if(file.size>6*1024*1024){toast('Files are limited to 6 MB in this beta shell.');return;}const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let index=0;index<bytes.length;index+=0x8000)binary+=String.fromCharCode(...bytes.subarray(index,index+0x8000));await send(`/api/projects/${state.projectId}/files`,{name:file.name,mime_type:file.type||'application/octet-stream',folder_id:state.folderId,data_base64:btoa(binary)});toast(`${file.name} uploaded.`,'ok');await showProjectFiles();}
  async function itemActions(kind,id){const item=state.items.find((entry)=>entry.kind===kind&&entry.id===id);if(!item)return;const folderActions=kind==='folder'?'<button class="outline-button" data-item-action="new-note">New note</button><button class="outline-button" data-item-action="new-folder">New folder</button>':'';modal(item.name,`<div class="form-stack">${folderActions}<button class="outline-button" data-item-action="open">Open</button><button class="outline-button" data-item-action="rename">Rename</button><button class="outline-button" data-item-action="copy">Copy</button><button class="outline-button" data-item-action="duplicate">Duplicate</button><button class="outline-button" data-item-action="archive">Archive</button><button class="outline-button" data-item-action="invalidate">Invalidate</button><button class="danger-button" data-item-action="delete">Delete</button></div>`);$('modal-body').querySelectorAll('[data-item-action]').forEach((button)=>button.onclick=async()=>{const action=button.dataset.itemAction;closeModal();try{if(action==='open')await openItem(kind,id);else if(action==='new-note'){state.folderId=id;await newItem('note');}else if(action==='new-folder'){state.folderId=id;await newItem('folder');}else if(action==='rename')renameItem(kind,id,item.name);else if(action==='copy'){state.clipboard=[{kind,id}];toast('Copied.','ok');updateSelectionCount();}else if(action==='duplicate'){await send(`/api/projects/${state.projectId}/duplicate`,{kind,id});await showProjectFiles();}else if(action==='archive'||action==='invalidate'){await send(`/api/projects/${state.projectId}/lifecycle`,{kind,id,status:action==='archive'?'Archived':'Invalidated'});await showProjectFiles();}else if(action==='delete'){await send(`/api/projects/${state.projectId}/delete`,{selection:[{kind,id}]});await showProjectFiles();}}catch(error){toast(error.message);}});}
  async function bulkAction(action){const selection=selectedItems();if(action==='paste'){if(!state.clipboard.length||!state.projectId)return toast('Nothing is copied.');}else if(!selection.length||!state.projectId)return;try{if(action==='copy')state.clipboard=selection;else if(action==='paste')await send(`/api/projects/${state.projectId}/paste`,{selection:state.clipboard,target_folder_id:state.folderId});else if(action==='delete')await send(`/api/projects/${state.projectId}/delete`,{selection});else await Promise.all(selection.map((item)=>send(`/api/projects/${state.projectId}/lifecycle`,{...item,status:action==='archive'?'Archived':'Invalidated'})));if(action!=='copy')state.selected.clear();updateSelectionCount();await showProjectFiles();}catch(error){toast(error.message);}}
  function updateSelectionCount(){const node=$('selection-count');if(node)node.textContent=state.selected.size?`${state.selected.size} selected`:'';const actions=$('bulk-actions');if(actions)actions.hidden=!state.selected.size;}
  function reorderLocal(drag,targetId){const key=`pas-order-${state.projectId}-${state.folderId||0}`;const current=state.items.map((item)=>token(item.kind,item.id)).filter((value)=>value!==token(drag.kind,drag.id));const targetIndex=current.findIndex((value)=>value.endsWith(`:${targetId}`));current.splice(Math.max(0,targetIndex),0,token(drag.kind,drag.id));localStorage.setItem(key,JSON.stringify(current));}
  function bindProjectFilesInteractions(){const list=$('file-list');if(!list||list.dataset.bound==='1')return;list.dataset.bound='1';let drag=null;list.addEventListener('click',(event)=>{const row=event.target.closest('.file-row');const open=event.target.closest('.file-open');if(!row||!open)return;const key=token(row.dataset.kind,row.dataset.id);if(event.ctrlKey||event.metaKey){state.selected.has(key)?state.selected.delete(key):state.selected.add(key);}else{state.selected.clear();state.selected.add(key);}updateSelectionCount();});list.addEventListener('dblclick',(event)=>{const open=event.target.closest('.file-open');const row=open?.closest('.file-row');if(row)openItem(row.dataset.kind,Number(row.dataset.id)).catch((error)=>toast(error.message));});list.addEventListener('dragstart',(event)=>{const row=event.target.closest('.file-row');if(!row)return;drag={kind:row.dataset.kind,id:Number(row.dataset.id)};row.classList.add('dragging');});list.addEventListener('dragend',(event)=>event.target.closest('.file-row')?.classList.remove('dragging'));list.addEventListener('dragover',(event)=>{const row=event.target.closest('.file-row');if(row){event.preventDefault();row.classList.add('drop-target');}});list.addEventListener('dragleave',(event)=>event.target.closest('.file-row')?.classList.remove('drop-target'));list.addEventListener('drop',async(event)=>{const row=event.target.closest('.file-row');if(!row||!drag)return;event.preventDefault();row.classList.remove('drop-target');if(row.dataset.kind==='folder'){try{await send(`/api/projects/${state.projectId}/move`,{kind:drag.kind,id:drag.id,target_folder_id:Number(row.dataset.id)});await showProjectFiles();}catch(error){toast(error.message);}}else if(state.sort==='none'){reorderLocal(drag,Number(row.dataset.id));await showProjectFiles();}});}

  async function search(query){const q=String(query||'').trim();if(!q)return;const result=await api(`/api/search?q=${encodeURIComponent(q)}`);window.renderSearchResults?.(result,q);}
  function shareCurrent(){const payload={title:document.title,text:state.project?.name||'Personal AI System',url:location.href};return navigator.share?navigator.share(payload):navigator.clipboard.writeText(location.href).then(()=>toast('Link copied.','ok'));}
  async function handleMessageAction(target){const article=target.closest('.message');const action=target.dataset.msgAction;if(!article)return;const text=article.querySelector('.content,.user-bubble')?.textContent||'';if(action==='copy')return navigator.clipboard.writeText(text).then(()=>toast('Copied.','ok'));if(action==='share')return navigator.share?navigator.share({text}):navigator.clipboard.writeText(text).then(()=>toast('Copied share text.','ok'));if(action==='edit'){$('chat-input').value=text;$('chat-input').dispatchEvent(new Event('input'));$('chat-input').focus();return;}if(action==='retry'){const promptText=article.dataset.retryPrompt||'';if(promptText)return sendMessage(promptText);return;}if(action==='branch'){const result=await send(`/api/chats/${state.chatId}/branch`,{title:`${$('chat-title').textContent||'Chat'} — branch`});state.chatId=result.id;await loadChats();await loadChat();toast('Chat branched.','ok');return;}if(action==='rate-up'||action==='rate-down'){const index=Number(article.dataset.assistantIndex||-1);const chat=await api(`/api/chats/${state.chatId}`);const assistants=(chat.messages||[]).filter((message)=>message.role==='assistant');const message=assistants[index];if(!message?.id)throw new Error('Assistant message could not be identified.');await api(`/api/chats/${state.chatId}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:message.id,rating:action==='rate-up'?'up':'down'})});localStorage.setItem(`pas-rating-${state.chatId}-${index}`,action==='rate-up'?'up':'down');renderMessages(chat.messages||[],[]);toast('Feedback saved.','ok');}}
  let plannerRefreshTimer = null;
  let plannerRunTimer = null;

  const plannerUi = {
    snapshot: null,
    selectedId: null,
    queueFilter: 'all',
    search: '',
    tab: 'overview',
    graphFocus: null,
    running: false,
    paused: false,
    runElapsed: 0,
    progressOverride: null,
  };

  function plannerOrderKey(path) {
    return `pasi-planner-order:${path}`;
  }

  function plannerDraftKey(path) {
    return `pasi-planner-draft:${path}`;
  }

  function plannerLoadDraft(path) {
    try {
      const value = JSON.parse(localStorage.getItem(plannerDraftKey(path)) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch (_) {
      return {};
    }
  }

  function plannerSaveDraft(path, draft) {
    localStorage.setItem(plannerDraftKey(path), JSON.stringify(draft));
  }

  function plannerOrderedTasks(snapshot) {
    const tasks = [...(snapshot.tasks || [])];
    const raw = localStorage.getItem(plannerOrderKey(snapshot.roadmap.path));
    if (!raw) return tasks;
    try {
      const order = JSON.parse(raw);
      if (!Array.isArray(order)) return tasks;
      const rank = new Map(order.map((id, index) => [id, index]));
      return tasks.sort((a, b) => (rank.get(a.id) ?? 999999) - (rank.get(b.id) ?? 999999));
    } catch (_) {
      return tasks;
    }
  }

  function plannerTaskStatus(task, draft) {
    return String(draft.statuses?.[task.id] || task.runtime_status || task.status || 'pending');
  }

  function plannerTaskSatisfied(task, draft) {
    return draft.statuses?.[task.id] === 'completed' || Boolean(task.satisfied);
  }

  function plannerDisplayTasks(snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const ordered = plannerOrderedTasks(snapshot).map((task) => ({
      ...task,
      runtime_status: plannerTaskStatus(task, draft),
      satisfied: plannerTaskSatisfied(task, draft),
      current: plannerUi.running ? task.id === plannerUi.selectedId : Boolean(task.current),
    }));
    const query = plannerUi.search.trim().toLowerCase();
    return ordered.filter((task) => {
      const status = plannerTaskStatus(task, draft);
      const eligible = (snapshot.eligible_ids || []).includes(task.id);
      const matchesFilter =
        plannerUi.queueFilter === 'all' ||
        (plannerUi.queueFilter === 'ready' && eligible) ||
        (plannerUi.queueFilter === 'blocked' && status === 'blocked') ||
        (plannerUi.queueFilter === 'active' && (task.current || task.id === plannerUi.selectedId || status === 'in_progress')) ||
        (plannerUi.queueFilter === 'done' && task.satisfied);
      const haystack = [task.id, task.title, task.objective, task.phase].join(' ').toLowerCase();
      return matchesFilter && (!query || haystack.includes(query));
    });
  }

  function plannerEligible(snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const byId = new Map((snapshot.tasks || []).map((task) => [task.id, task]));
    return (snapshot.eligible_ids || []).filter((id) => {
      const task = byId.get(id);
      return task && !plannerTaskSatisfied(task, draft) && plannerTaskStatus(task, draft) !== 'cancelled';
    });
  }

  function plannerCurrent(snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    return snapshot.tasks.find((task) => task.current) ||
      snapshot.tasks.find((task) => task.id === snapshot.runtime?.current_task_id) ||
      snapshot.tasks.find((task) => plannerTaskStatus(task, draft) === 'in_progress') ||
      null;
  }

  function plannerFormatElapsed(seconds) {
    const s = Math.max(0, Number(seconds) || 0);
    const mins = Math.floor(s / 60);
    const secs = Math.floor(s % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function plannerTaskIcon(task, snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const status = plannerTaskStatus(task, draft);
    if (plannerTaskSatisfied(task, draft)) return '✓';
    if (status === 'blocked') return '!';
    if (status === 'in_progress') return '→';
    if ((snapshot.eligible_ids || []).includes(task.id)) return '●';
    if (status === 'cancelled') return '×';
    return '○';
  }

  function plannerStatusClass(task, snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const status = plannerTaskStatus(task, draft);
    if (plannerTaskSatisfied(task, draft)) return 'done';
    if (status === 'blocked') return 'blocked';
    if (status === 'in_progress' || task.current || task.id === plannerUi.selectedId) return 'active';
    if ((snapshot.eligible_ids || []).includes(task.id)) return 'ready';
    return 'queued';
  }

  function plannerStatusLabel(task, snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const status = plannerTaskStatus(task, draft);
    if (plannerTaskSatisfied(task, draft)) return 'Completed';
    if (status === 'in_progress') return 'In progress';
    if (status === 'blocked') return 'Blocked';
    if ((snapshot.eligible_ids || []).includes(task.id)) return 'Ready';
    if (status === 'cancelled') return 'Cancelled';
    return 'Queued';
  }

  function plannerTimeEstimate(task) {
    const sizes = { small: '1h', medium: '3h', large: '6h' };
    return sizes[String(task.estimated_size || '').toLowerCase()] || task.estimated_size || '—';
  }

  function plannerProgressMarkup(snapshot) {
    const p = snapshot.progress || { completed: 0, total: 0, percent: 0 };
    const percent = plannerUi.progressOverride == null ? Number(p.percent || 0) : plannerUi.progressOverride;
    const completed = plannerUi.progressOverride == null
      ? Number(p.completed || 0)
      : Math.min(Number(p.total || 0), Math.round((percent / 100) * Number(p.total || 0)));
    return `<section class="planner-progress-card">
      <div class="planner-progress-top">
        <div>
          <span class="planner-kicker">ROADMAP PROGRESS</span>
          <strong>${completed} / ${p.total || 0} tasks</strong>
        </div>
        <span class="planner-progress-percent">${percent.toFixed(0)}%</span>
      </div>
      <div class="planner-progress-bar"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
      <div class="planner-progress-meta"><span>Live from PASI planner snapshot</span><span>${snapshot.eligible_ids?.length || 0} ready · ${snapshot.tasks?.filter((task) => plannerTaskStatus(task, plannerLoadDraft(snapshot.roadmap.path)) === 'blocked').length || 0} blocked · ${plannerCurrent(snapshot) ? 1 : 0} executing</span></div>
    </section>`;
  }

  function plannerTaskDetailModal(task, snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const deps = task.depends_on || [];
    const dependents = (snapshot.tasks || []).filter((item) => (item.depends_on || []).includes(task.id));
    const status = plannerTaskStatus(task, draft);
    const acceptance = (task.acceptance_criteria || []).map((item) => `<li><span>✓</span>${escapeHtml(item)}</li>`).join('') || '<li><span>•</span>No acceptance criteria recorded.</li>';
    const verification = (task.verification || []).map((item) => `<li><span>□</span>${escapeHtml(item)}</li>`).join('') || '<li><span>•</span>No verification steps recorded.</li>';
    modal(task.title, `<div class="planner-detail-modal">
      <div class="planner-detail-hero">
        <div><span class="planner-kicker">${escapeHtml(task.id)}</span><h3>${escapeHtml(task.objective || task.title)}</h3></div>
        <span class="planner-badge ${plannerStatusClass(task, snapshot)}">${escapeHtml(plannerStatusLabel(task, snapshot))}</span>
      </div>
      <div class="planner-detail-grid">
        <div class="planner-detail-block"><span>Phase</span><strong>${escapeHtml(task.phase || '—')}</strong></div>
        <div class="planner-detail-block"><span>Priority</span><strong>${escapeHtml(task.priority || '—')}</strong></div>
        <div class="planner-detail-block"><span>Estimate</span><strong>${escapeHtml(plannerTimeEstimate(task))}</strong></div>
        <div class="planner-detail-block"><span>Run attempt</span><strong>${escapeHtml(snapshot.runtime?.current_attempt || '—')}</strong></div>
      </div>
      <div class="planner-detail-columns">
        <section><span class="planner-kicker">DEPENDS ON</span><div class="planner-chip-list">${deps.length ? deps.map((id) => `<button type="button" class="planner-mini-chip" data-planner-focus="${attr(id)}">${escapeHtml(id)}</button>`).join('') : '<span class="muted">No prerequisites</span>'}</div></section>
        <section><span class="planner-kicker">DEPENDENTS</span><div class="planner-chip-list">${dependents.length ? dependents.map((item) => `<button type="button" class="planner-mini-chip" data-planner-focus="${attr(item.id)}">${escapeHtml(item.id)}</button>`).join('') : '<span class="muted">No downstream tasks</span>'}</div></section>
      </div>
      <section class="planner-detail-list"><span class="planner-kicker">ACCEPTANCE CRITERIA</span><ul>${acceptance}</ul></section>
      <section class="planner-detail-list"><span class="planner-kicker">VERIFICATION</span><ul>${verification}</ul></section>
      <div class="planner-detail-actions">
        <button type="button" class="outline-button" data-planner-status="pending" data-task-id="${attr(task.id)}">Mark queued</button>
        <button type="button" class="outline-button" data-planner-status="blocked" data-task-id="${attr(task.id)}">Block</button>
        <button type="button" class="primary-button" data-planner-status="completed" data-task-id="${attr(task.id)}">${status === 'completed' ? 'Keep completed' : 'Mark complete'}</button>
      </div>
      <p class="planner-local-note">Draft controls are local-only and never write directly to the unattended PASI runtime.</p>
    </div>`);
    document.querySelectorAll('[data-planner-status]').forEach((button) => {
      button.onclick = () => {
        plannerSetTaskStatus(button.dataset.taskId, button.dataset.plannerStatus, snapshot);
        closeModal();
      };
    });
    document.querySelectorAll('[data-planner-focus]').forEach((button) => {
      button.onclick = () => {
        plannerUi.selectedId = button.dataset.plannerFocus;
        closeModal();
        plannerRender();
        requestAnimationFrame(() => document.querySelector(`.planner-task-card[data-task-id="${CSS.escape(plannerUi.selectedId)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
      };
    });
  }

  function plannerSetTaskStatus(taskId, status, snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    draft.statuses = { ...(draft.statuses || {}) };
    draft.statuses[taskId] = status;
    plannerSaveDraft(snapshot.roadmap.path, draft);
    plannerRender();
    announce(`${taskId} set to ${status}`);
  }

  function plannerExport(snapshot) {
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const exportPayload = {
      exported_at: new Date().toISOString(),
      roadmap: snapshot.roadmap,
      tasks: snapshot.tasks,
      local_draft: draft,
      human_order: plannerOrderedTasks(snapshot).map((task) => task.id),
      deterministic_rank: snapshot.deterministic_rank || [],
    };
    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'pasi-planner-draft.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast('Planner draft exported.', 'ok');
  }

  function plannerImportModal() {
    modal('Import roadmap JSON', `<form id="planner-import-form" class="form-stack planner-import-form">
      <div class="planner-import-tabs"><span class="planner-import-tab active">JSON roadmap</span><span class="planner-import-hint">Preview only</span></div>
      <label>Roadmap JSON<textarea id="planner-import-json" rows="15" placeholder='{"schema_version":1,"tasks":[...]}'></textarea></label>
      <div class="form-actions"><button type="button" class="outline-button" id="planner-import-cancel">Cancel</button><button class="primary-button">Preview roadmap</button></div>
    </form>`);
    $('planner-import-cancel').onclick = closeModal;
    $('planner-import-form').onsubmit = (event) => {
      event.preventDefault();
      try {
        const data = JSON.parse($('planner-import-json').value);
        if (!data || !Array.isArray(data.tasks)) throw new Error('Roadmap must contain a tasks array.');
        if (data.tasks.some((task) => typeof task.id !== 'string' || !task.id.trim())) throw new Error('Every task needs a stable string id.');
        localStorage.setItem('pasi-planner-import-preview', JSON.stringify(data));
        closeModal();
        toast(`Loaded ${data.tasks.length} tasks into local preview.`, 'ok');
        renderPlannerImported(data);
      } catch (error) {
        toast(error.message);
      }
    };
  }

  function renderPlannerImported(data) {
    const normalized = {
      roadmap: { path: 'local import preview', sha256: 'local-preview', schema_version: data.schema_version || 1 },
      tasks: data.tasks.map((task) => ({ ...task, runtime_status: task.status || 'pending', satisfied: task.status === 'completed', current: false })),
      eligible_ids: data.tasks.filter((task) => !task.depends_on?.length && task.status !== 'completed').map((task) => task.id),
      deterministic_rank: data.tasks.map((task) => task.id),
      progress: {
        completed: data.tasks.filter((task) => task.status === 'completed').length,
        total: data.tasks.length,
        percent: data.tasks.length ? Math.round(data.tasks.filter((task) => task.status === 'completed').length / data.tasks.length * 100) : 0,
      },
      runtime: {},
    };
    plannerUi.snapshot = normalized;
    plannerUi.selectedId = normalized.tasks.find((task) => task.status !== 'completed')?.id || normalized.tasks[0]?.id || null;
    plannerRender();
    toast('Local roadmap preview loaded.', 'ok');
  }

  function plannerGraphMarkup(snapshot) {
    const tasks = plannerOrderedTasks(snapshot);
    const byId = new Map(snapshot.tasks.map((task) => [task.id, task]));
    const focus = plannerUi.graphFocus || plannerUi.selectedId;
    return `<div class="planner-graph-canvas" role="list" aria-label="Roadmap dependency graph">
      ${tasks.map((task, index) => {
        const deps = task.depends_on || [];
        const connected = focus && (task.id === focus || deps.includes(focus) || (byId.get(focus)?.depends_on || []).includes(task.id));
        const blockers = deps.filter((id) => !byId.get(id)?.satisfied);
        return `<button type="button" class="planner-graph-node planner-graph-${plannerStatusClass(task, snapshot)} ${connected ? 'connected' : ''}" data-planner-graph-task="${attr(task.id)}" style="--graph-i:${index % 5}">
          <span class="planner-node-status">${plannerTaskIcon(task, snapshot)}</span>
          <span><strong>${escapeHtml(task.title)}</strong><code>${escapeHtml(task.id)}</code></span>
          <span class="planner-node-meta">${deps.length ? `${deps.length} dep${deps.length === 1 ? '' : 's'}` : 'root'}${blockers.length ? ' · blocked upstream' : ''}</span>
        </button>`;
      }).join('')}
    </div>`;
  }

  function plannerQueueMarkup(snapshot) {
    const tasks = plannerDisplayTasks(snapshot);
    const eligible = new Set(plannerEligible(snapshot));
    const selected = plannerUi.selectedId;
    return `<section class="planner-panel planner-queue-panel">
      <div class="planner-panel-header">
        <div><span class="planner-kicker">TASK QUEUE</span><h2>Execution backlog</h2></div>
        <div class="planner-queue-actions">
          <button type="button" class="planner-icon-button" aria-label="Refresh" title="Refresh" data-planner-action="refresh">↻</button>
        </div>
      </div>
      <div class="planner-segmented" role="tablist" aria-label="Task queue filters">
        ${[['all','All'],['ready','Ready'],['blocked','Blocked'],['active','Active'],['done','Done']].map(([value,label]) => `<button type="button" role="tab" class="${plannerUi.queueFilter === value ? 'active' : ''}" data-planner-filter="${value}">${label}<span>${value === 'all' ? snapshot.tasks.length : value === 'ready' ? eligible.size : value === 'blocked' ? snapshot.tasks.filter((task) => plannerTaskStatus(task, plannerLoadDraft(snapshot.roadmap.path)) === 'blocked').length : value === 'done' ? snapshot.tasks.filter((task) => plannerTaskSatisfied(task, plannerLoadDraft(snapshot.roadmap.path))).length : 1}</span></button>`).join('')}
      </div>
      <div class="planner-task-list" id="planner-task-list">
        ${tasks.length ? tasks.map((task, index) => `<article class="planner-task-card ${plannerStatusClass(task, snapshot)} ${task.id === selected ? 'selected' : ''}" draggable="true" data-task-id="${attr(task.id)}" tabindex="0">
          <div class="planner-task-main">
            <div class="planner-task-index">${String(index + 1).padStart(2, '0')}</div>
            <div class="planner-task-status-dot"><span>${plannerTaskIcon(task, snapshot)}</span></div>
            <div class="planner-task-copy">
              <div class="planner-task-line"><span class="planner-task-id">${escapeHtml(task.id)}</span><span class="planner-badge ${plannerStatusClass(task, snapshot)}">${plannerStatusLabel(task, snapshot)}</span></div>
              <h3>${escapeHtml(task.title)}</h3>
              <p>${escapeHtml(task.objective || '')}</p>
              <div class="planner-task-meta"><span>${escapeHtml(task.phase || 'Unscoped')}</span><span>${escapeHtml(task.priority || 'P?')}</span><span>${plannerTimeEstimate(task)}</span>${eligible.has(task.id) ? '<span class="planner-ready">Ready to run</span>' : ''}</div>
            </div>
          </div>
          <div class="planner-task-row-actions">
            <button type="button" class="planner-ghost-icon" title="Move up" aria-label="Move task up" data-planner-move="up" data-task-id="${attr(task.id)}">↑</button>
            <button type="button" class="planner-ghost-icon" title="Move down" aria-label="Move task down" data-planner-move="down" data-task-id="${attr(task.id)}">↓</button>
            <button type="button" class="planner-details-button" data-planner-detail="${attr(task.id)}">Details</button>
          </div>
        </article>`).join('') : '<div class="planner-empty-state"><strong>No tasks match this view.</strong><span>Adjust the queue filter or search.</span></div>'}
      </div>
    </section>`;
  }

  function plannerSelectedMarkup(snapshot) {
    const task = snapshot.tasks.find((item) => item.id === plannerUi.selectedId) || plannerCurrent(snapshot) || plannerOrderedTasks(snapshot)[0];
    if (!task) return '<div class="planner-empty-state"><strong>No task selected.</strong></div>';
    const status = plannerStatusLabel(task, snapshot);
    const draft = plannerLoadDraft(snapshot.roadmap.path);
    const blockers = (task.depends_on || []).filter((id) => {
      const dep = snapshot.tasks.find((item) => item.id === id);
      return dep && !plannerTaskSatisfied(dep, draft);
    });
    return `<section class="planner-panel planner-focus-panel">
      <div class="planner-focus-top">
        <div><span class="planner-kicker">${escapeHtml(task.id)} · ${escapeHtml(String(status).toUpperCase())}</span><h2>${escapeHtml(task.title)}</h2><p>${escapeHtml(task.objective || '')}</p></div>
        <button type="button" class="planner-menu-button" aria-label="Task actions" data-planner-menu="${attr(task.id)}">•••</button>
      </div>
      <div class="planner-focus-grid">
        <div><span>Assignee</span><strong>Unattended PASI</strong></div>
        <div><span>Priority</span><strong>${escapeHtml(task.priority || '—')}</strong></div>
        <div><span>Estimate</span><strong>${escapeHtml(plannerTimeEstimate(task))}</strong></div>
        <div><span>Phase</span><strong>${escapeHtml(task.phase || '—')}</strong></div>
      </div>
      <div class="planner-focus-tabs" role="tablist">
        ${[['overview','Overview'],['eligible','Eligibility'],['ai','AI ranking'],['execution','History']].map(([value,label]) => `<button type="button" class="${plannerUi.tab === value ? 'active' : ''}" data-planner-tab="${value}">${label}</button>`).join('')}
      </div>
      <div class="planner-focus-content">
        ${plannerUi.tab === 'eligible' ? `<div class="planner-insight ${blockers.length ? 'warning' : 'success'}"><strong>${blockers.length ? 'Blocked by prerequisites' : eligibleForTask(snapshot, task) ? 'Eligible now' : 'Not currently eligible'}</strong><span>${blockers.length ? blockers.join(' · ') : 'All deterministic dependency checks are satisfied.'}</span></div>` :
          plannerUi.tab === 'ai' ? plannerAiMarkup(snapshot) :
          plannerUi.tab === 'execution' ? plannerExecutionHistoryMarkup(snapshot, task) :
          `<div class="planner-checklist">${(task.acceptance_criteria || []).slice(0, 5).map((item, index) => `<label><input type="checkbox" disabled ${task.satisfied ? 'checked' : ''}><span>${escapeHtml(item)}</span></label>`).join('') || '<div class="muted">No acceptance criteria supplied.</div>'}</div>`}
      </div>
      <div class="planner-focus-actions">
        <button type="button" class="outline-button" data-planner-status="blocked" data-task-id="${attr(task.id)}">Block</button>
        <button type="button" class="outline-button" data-planner-status="pending" data-task-id="${attr(task.id)}">Queue</button>
        <button type="button" class="primary-button" data-planner-status="completed" data-task-id="${attr(task.id)}">${task.satisfied ? 'Completed' : 'Mark complete'}</button>
      </div>
    </section>`;
  }

  function eligibleForTask(snapshot, task) {
    return (snapshot.eligible_ids || []).includes(task.id);
  }

  function plannerAiMarkup(snapshot) {
    const ranking = snapshot.deterministic_rank || [];
    const enabled = localStorage.getItem('pasi-planner-ai') === '1';
    return `<div class="planner-ai-card">
      <div class="planner-ai-header"><div><span class="planner-kicker">OPTIONAL</span><strong>AI ranking</strong><p>Ranks only tasks PASI has already deemed eligible.</p></div><label class="planner-switch"><input id="planner-ai-toggle" type="checkbox" ${enabled ? 'checked' : ''}><span></span></label></div>
      <div class="planner-ai-list">${ranking.slice(0, 5).map((id, index) => `<div><span>${index + 1}</span><strong>${escapeHtml(id)}</strong><em>${enabled ? (0.96 - index * 0.08).toFixed(2) : '—'}</em></div>`).join('') || '<div class="muted">No eligible tasks to rank.</div>'}</div>
      <div class="planner-local-note">${enabled ? 'AI mode is enabled as a local UX preview.' : 'AI mode is off. Deterministic ordering remains the source of truth.'}</div>
    </div>`;
  }

  function plannerExecutionHistoryMarkup(snapshot, task) {
    const runtime = snapshot.runtime || {};
    const events = [
      runtime.started_at ? `Run started ${runtime.started_at}` : 'Planner runtime history is local to this snapshot.',
      task.current ? `Executing ${task.id}` : `Task status: ${plannerStatusLabel(task, snapshot)}`,
      task.satisfied ? 'Verification satisfied' : 'Awaiting completion evidence',
    ];
    return `<div class="planner-history">${events.map((event, index) => `<div><span>${String(index + 1).padStart(2, '0')}</span><p>${escapeHtml(event)}</p></div>`).join('')}</div>`;
  }

  function plannerRightRailMarkup(snapshot) {
    const current = plannerCurrent(snapshot);
    const runtime = snapshot.runtime || {};
    const readyCount = plannerEligible(snapshot).length;
    const blockedCount = snapshot.tasks.filter((task) => plannerTaskStatus(task, plannerLoadDraft(snapshot.roadmap.path)) === 'blocked').length;
    const recent = plannerOrderedTasks(snapshot).slice(0, 5);
    const selected = snapshot.tasks.find((task) => task.id === plannerUi.selectedId);
    return `<aside class="planner-right-rail">
      <section class="planner-rail-card">
        <div class="planner-rail-head"><span class="planner-kicker">LIVE EXECUTION</span><span class="planner-live-dot">${plannerUi.running ? 'PREVIEW RUN' : current ? 'LIVE' : 'IDLE'}</span></div>
        ${current || plannerUi.running ? `<div class="planner-run-task">
          <div class="planner-run-title"><span class="planner-status-ring ${plannerUi.running ? 'running' : ''}">${plannerUi.running ? '→' : '•'}</span><div><strong>${escapeHtml((plannerUi.running && selected) ? selected.title : current?.title || selected?.title || 'Current task')}</strong><span>${escapeHtml((plannerUi.running && selected) ? selected.id : current?.id || '—')}</span></div></div>
          <p>${plannerUi.running ? 'Previewing planner selection without touching unattended execution.' : escapeHtml(current?.objective || 'Runtime reports no active task.')}</p>
          <div class="planner-run-meter"><span style="width:${plannerUi.running ? Math.min(94, 24 + plannerUi.runElapsed * 2) : 62}%"></span></div>
          <div class="planner-run-metrics"><span>${plannerUi.running ? plannerFormatElapsed(plannerUi.runElapsed) : 'Connected'}</span><span>${plannerUi.running ? 'preview' : `attempt ${runtime.current_attempt || 0}`}</span></div>
          <div class="planner-run-actions">${plannerUi.running
            ? `<button type="button" class="outline-button" data-planner-run-control="pause">${plannerUi.paused ? 'Resume' : 'Pause'}</button><button type="button" class="danger-button" data-planner-run-control="stop">Stop</button>`
            : '<button type="button" class="outline-button" data-planner-action="refresh">Refresh state</button><button type="button" class="primary-button" data-planner-run-control="run">Run planner</button>'}
          </div>
        </div>` : `<div class="planner-idle-run"><strong>No active runtime task</strong><span>Use Run planner to preview deterministic selection.</span><button type="button" class="primary-button" data-planner-run-control="run">Run planner</button></div>`}
      </section>
      <section class="planner-rail-card">
        <div class="planner-rail-head"><span class="planner-kicker">RUNTIME METRICS</span><span>LIVE</span></div>
        <div class="planner-metric-grid">
          <div><strong>${snapshot.tasks.length}</strong><span>Tasks</span></div>
          <div><strong>${readyCount}</strong><span>Ready</span></div>
          <div><strong>${blockedCount}</strong><span>Blocked</span></div>
          <div><strong>${runtime.current_attempt || 0}</strong><span>Attempt</span></div>
        </div>
      </section>
      <section class="planner-rail-card">
        <div class="planner-rail-head"><span class="planner-kicker">EVENT STREAM</span><span>AUTO-REFRESH 5s</span></div>
        <div class="planner-event-stream">
          ${recent.map((task, index) => `<button type="button" data-planner-stream-task="${attr(task.id)}"><span>${String(index + 1).padStart(2, '0')}</span><span>${escapeHtml(plannerStatusLabel(task, snapshot).toLowerCase())} · ${escapeHtml(task.id)}</span><em>${escapeHtml(task.phase || '')}</em></button>`).join('')}
        </div>
      </section>
      <section class="planner-rail-card">
        <div class="planner-rail-head"><span class="planner-kicker">PLANNER INTEGRATIONS</span></div>
        <div class="planner-integrations">
          <button type="button" data-planner-integration="github"><span>◈</span><div><strong>GitHub Projects</strong><small>Roadmap storage / human planning</small></div><b>↗</b></button>
          <button type="button" data-planner-integration="bridge"><span>◎</span><div><strong>PASI Bridge</strong><small>Authenticated localhost control plane</small></div><b>●</b></button>
        </div>
      </section>
    </aside>`;
  }

  function plannerSidebarMarkup(snapshot) {
    const runtime = snapshot.runtime || {};
    return `<aside class="planner-sidebar">
      <div class="planner-brand"><div class="planner-brand-mark">⌁</div><div><strong>PASI Planner</strong><span>Engineering workspace · v0.9</span></div></div>
      <div class="planner-workspace-switch"><span>WORKSPACE</span><button type="button" data-planner-workspace>Core Platform <b>⌄</b></button></div>
      <nav class="planner-nav" aria-label="Planner navigation">
        ${[['planner','Planner','◇'],['executions','Executions','◉'],['artifacts','Artifacts','□'],['dependencies','Dependencies','⌘'],['environments','Environments','◈']].map(([id,label,icon]) => `<button type="button" class="${id === 'planner' ? 'active' : ''}" data-planner-nav="${id}"><span>${icon}</span>${label}${id === 'planner' ? '<b>3</b>' : ''}</button>`).join('')}
      </nav>
      <div class="planner-side-section"><span>PROJECT</span>
        <button type="button" data-planner-nav="overview"><span>◌</span>Overview</button>
        <button type="button" data-planner-nav="milestones"><span>◇</span>Milestones</button>
        <button type="button" data-planner-nav="team"><span>○</span>Team</button>
        <button type="button" data-planner-nav="settings"><span>⚙</span>Settings</button>
      </div>
      <div class="planner-branch-card">
        <span class="planner-branch-dot"></span><div><strong>feature/planner-v2</strong><small>${escapeHtml(snapshot.roadmap.sha256?.slice(0, 7) || 'local')} · synced now</small></div>
      </div>
      <div class="planner-side-status"><span></span><div><strong>PASI Bridge</strong><small>127.0.0.1:8765 · ${runtime.phase || 'ready'}</small></div></div>
    </aside>`;
  }

  function plannerTopbarMarkup(snapshot) {
    return `<header class="planner-topbar">
      <div class="planner-topbar-left"><button class="planner-mobile-menu" type="button" data-planner-action="toggle-sidebar">☰</button><span class="planner-topbar-context">PLANNER / ROADMAP <b>04</b></span></div>
      <label class="planner-search"><span>⌕</span><input id="planner-search" type="search" placeholder="Search tasks, symbols, commits..." value="${attr(plannerUi.search)}" autocomplete="off"><kbd>⌘ K</kbd></label>
      <div class="planner-top-actions"><span class="planner-health"><i></i> SYSTEM HEALTHY</span><button type="button" class="planner-top-icon" data-planner-action="notifications" aria-label="Notifications">◍</button><button type="button" class="planner-avatar" data-planner-action="account">AK</button></div>
    </header>`;
  }

  function plannerMainMarkup(snapshot) {
    const tabs = [['overview','Overview'],['eligible','Eligible tasks'],['ai','AI ranking'],['execution','Execution order']];
    const sortedForPreview = plannerOrderedTasks(snapshot);
    const selected = snapshot.tasks.find((task) => task.id === plannerUi.selectedId) || sortedForPreview[0];
    if (!plannerUi.selectedId && selected) plannerUi.selectedId = selected.id;
    return `<div class="planner-shell">
      ${plannerTopbarMarkup(snapshot)}
      <div class="planner-layout">
        ${plannerSidebarMarkup(snapshot)}
        <main class="planner-content">
          <div class="planner-content-inner">
            <header class="planner-page-header">
              <div>
                <span class="planner-breadcrumb">PLANNER / ROADMAP <b>04</b></span>
                <h1>Execution planner</h1>
                <p>Orchestrate dependency-aware delivery for the PASI runtime.</p>
              </div>
              <div class="planner-page-actions"><button type="button" class="outline-button" data-planner-action="export">Export plan</button><button type="button" class="primary-button" data-planner-run-control="run">Run planner</button></div>
            </header>
            ${plannerProgressMarkup(snapshot)}
            <div class="planner-work-area">
              <section class="planner-center-column">
                ${plannerQueueMarkup(snapshot)}
                ${plannerSelectedMarkup(snapshot)}
                <section class="planner-panel planner-graph-panel">
                  <div class="planner-panel-header"><div><span class="planner-kicker">DEPENDENCY GRAPH</span><h2>Roadmap structure</h2></div><div class="planner-graph-actions"><button type="button" class="planner-icon-button" data-planner-action="fit">Fit</button><button type="button" class="planner-icon-button" data-planner-action="clear-focus">Clear</button></div></div>
                  ${plannerGraphMarkup(snapshot)}
                </section>
              </section>
              ${plannerRightRailMarkup(snapshot)}
            </div>
            <footer class="planner-footer"><span>Human order is intent. Deterministic eligibility is authority.</span><span>Roadmap: ${escapeHtml(snapshot.roadmap.path)} · SHA ${escapeHtml(snapshot.roadmap.sha256?.slice(0, 12) || 'local')}</span></footer>
          </div>
        </main>
      </div>
    </div>`;
  }

  function plannerRender() {
    const page = $('page-view');
    const snapshot = plannerUi.snapshot;
    if (!page || !snapshot) return;
    page.innerHTML = plannerMainMarkup(snapshot);
    bindPlannerInteractions(snapshot);
  }

  function plannerBindSearch() {
    const input = $('planner-search');
    if (!input) return;
    input.addEventListener('input', () => {
      plannerUi.search = input.value;
      plannerRender();
      requestAnimationFrame(() => {
        const next = $('planner-search');
        next?.focus();
        if (next) next.setSelectionRange(next.value.length, next.value.length);
      });
    });
  }

  async function openPlanner() {
    setView('planner');
    const page = $('page-view');
    if (page) page.innerHTML = '<div class="planner-loading"><div class="planner-loading-spinner"></div><strong>Loading planner…</strong><span>Reading roadmap, ledger, and runtime state.</span></div>';
    try {
      plannerUi.snapshot = await api('/api/planner/roadmap');
      plannerUi.selectedId = plannerUi.snapshot.tasks.find((task) => task.current)?.id || plannerUi.snapshot.deterministic_rank?.[0] || plannerUi.snapshot.tasks[0]?.id || null;
      plannerRender();
    } catch (error) {
      if (page) page.innerHTML = `<div class="planner-loading planner-loading-error"><strong>Planner unavailable</strong><span>${escapeHtml(error.message)}</span><button type="button" class="outline-button" data-planner-action="refresh">Retry</button></div>`;
      return;
    }
    if (plannerRefreshTimer) clearInterval(plannerRefreshTimer);
    plannerRefreshTimer = setInterval(async () => {
      if (state.view !== 'planner') {
        clearInterval(plannerRefreshTimer);
        plannerRefreshTimer = null;
        return;
      }
      try {
        const next = await api('/api/planner/roadmap');
        const oldSha = plannerUi.snapshot?.roadmap?.sha256;
        plannerUi.snapshot = next;
        if (oldSha !== next.roadmap.sha256 || !document.querySelector('.planner-task-card')) {
          plannerRender();
        } else if (document.activeElement?.id !== 'planner-search') {
          plannerRender();
        } else {
          refreshPlannerDynamic(next);
        }
      } catch (_) {}
    }, 5000);
  }

  function refreshPlannerDynamic(snapshot) {
    if (state.view !== 'planner') return;
    const current = plannerCurrent(snapshot);
    const currentNode = document.querySelector('.planner-live-dot');
    if (currentNode) currentNode.textContent = plannerUi.running ? 'PREVIEW RUN' : current ? 'LIVE' : 'IDLE';
  }

  function plannerStartRun() {
    if (plannerUi.running) return;
    const snapshot = plannerUi.snapshot;
    if (!snapshot) return;
    const eligible = plannerEligible(snapshot);
    const nextId = eligible[0] || snapshot.deterministic_rank?.[0];
    if (!nextId) {
      toast('No eligible task is available to run.', 'error');
      return;
    }
    plannerUi.selectedId = nextId;
    plannerUi.running = true;
    plannerUi.paused = false;
    plannerUi.runElapsed = 0;
    plannerUi.progressOverride = snapshot.progress?.percent || 0;
    plannerRender();
    plannerRunTimer = setInterval(() => {
      if (!plannerUi.running || plannerUi.paused) return;
      plannerUi.runElapsed += 1;
      const nextProgress = Math.min(99, Number(plannerUi.progressOverride || 0) + 0.65);
      plannerUi.progressOverride = nextProgress;
      const meter = document.querySelector('.planner-run-meter span');
      if (meter) meter.style.width = `${Math.min(94, 24 + plannerUi.runElapsed * 2)}%`;
      const elapsed = document.querySelector('.planner-run-metrics span:first-child');
      if (elapsed) elapsed.textContent = plannerFormatElapsed(plannerUi.runElapsed);
      const progress = document.querySelector('.planner-progress-percent');
      if (progress) progress.textContent = `${nextProgress.toFixed(0)}%`;
      const bar = document.querySelector('.planner-progress-bar span');
      if (bar) bar.style.width = `${nextProgress}%`;
      if (plannerUi.runElapsed >= 60) {
        plannerStopRun(true);
      }
    }, 1000);
    announce('Planner preview started.');
  }

  function plannerStopRun(autoComplete = false) {
    if (plannerRunTimer) clearInterval(plannerRunTimer);
    plannerRunTimer = null;
    const snapshot = plannerUi.snapshot;
    if (autoComplete && snapshot && plannerUi.selectedId) {
      plannerSetTaskStatus(plannerUi.selectedId, 'completed', snapshot);
    }
    plannerUi.running = false;
    plannerUi.paused = false;
    plannerUi.runElapsed = 0;
    plannerUi.progressOverride = null;
    plannerRender();
    toast(autoComplete ? 'Preview task completed locally.' : 'Planner preview stopped.', 'ok');
  }

  function plannerTogglePause() {
    if (!plannerUi.running) return;
    plannerUi.paused = !plannerUi.paused;
    plannerRender();
    toast(plannerUi.paused ? 'Planner preview paused.' : 'Planner preview resumed.', 'ok');
  }

  function plannerMoveTask(taskId, direction) {
    const snapshot = plannerUi.snapshot;
    if (!snapshot) return;
    const tasks = plannerOrderedTasks(snapshot);
    const index = tasks.findIndex((task) => task.id === taskId);
    const target = direction === 'up' ? index - 1 : index + 1;
    if (index < 0 || target < 0 || target >= tasks.length) return;
    const ids = tasks.map((task) => task.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];
    localStorage.setItem(plannerOrderKey(snapshot.roadmap.path), JSON.stringify(ids));
    plannerRender();
    announce(`${taskId} moved ${direction}`);
  }

  function plannerBindTaskEvents(snapshot) {
    const list = $('planner-task-list');
    if (!list) return;
    let draggedId = null;
    list.addEventListener('dragstart', (event) => {
      const task = event.target.closest('.planner-task-card');
      if (!task) return;
      draggedId = task.dataset.taskId;
      task.classList.add('dragging');
      event.dataTransfer?.setData('text/plain', draggedId);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    list.addEventListener('dragend', (event) => event.target.closest('.planner-task-card')?.classList.remove('dragging'));
    list.addEventListener('dragover', (event) => {
      const task = event.target.closest('.planner-task-card');
      if (!task || task.dataset.taskId === draggedId) return;
      event.preventDefault();
      task.classList.add('drop-target');
    });
    list.addEventListener('dragleave', (event) => event.target.closest('.planner-task-card')?.classList.remove('drop-target'));
    list.addEventListener('drop', (event) => {
      const target = event.target.closest('.planner-task-card');
      if (!target || !draggedId || target.dataset.taskId === draggedId) return;
      event.preventDefault();
      target.classList.remove('drop-target');
      const ids = plannerOrderedTasks(snapshot).map((task) => task.id);
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(target.dataset.taskId);
      if (from < 0 || to < 0) return;
      ids.splice(from, 1);
      ids.splice(to, 0, draggedId);
      localStorage.setItem(plannerOrderKey(snapshot.roadmap.path), JSON.stringify(ids));
      plannerRender();
      announce(`Moved ${draggedId}.`);
    });
    list.addEventListener('click', (event) => {
      const move = event.target.closest('[data-planner-move]');
      if (move) {
        event.stopPropagation();
        plannerMoveTask(move.dataset.taskId, move.dataset.plannerMove);
        return;
      }
      const detail = event.target.closest('[data-planner-detail]');
      if (detail) {
        event.stopPropagation();
        const task = snapshot.tasks.find((item) => item.id === detail.dataset.plannerDetail);
        if (task) plannerTaskDetailModal(task, snapshot);
        return;
      }
      const taskCard = event.target.closest('.planner-task-card');
      if (taskCard) {
        plannerUi.selectedId = taskCard.dataset.taskId;
        plannerUi.graphFocus = plannerUi.selectedId;
        plannerUi.tab = 'overview';
        plannerRender();
      }
    });
    list.addEventListener('keydown', (event) => {
      const taskCard = event.target.closest('.planner-task-card');
      if (taskCard && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        plannerUi.selectedId = taskCard.dataset.taskId;
        plannerRender();
      }
    });
  }

  function plannerNavigate(section, snapshot) {
    const titles = {
      executions: 'Executions',
      artifacts: 'Artifacts',
      dependencies: 'Dependencies',
      environments: 'Environments',
      overview: 'Project overview',
      milestones: 'Milestones',
      team: 'Team',
      settings: 'Planner settings',
    };
    if (section === 'planner') {
      plannerUi.tab = 'overview';
      plannerUi.queueFilter = 'all';
      plannerRender();
      return;
    }
    const title = titles[section] || 'Planner';
    const runtime = snapshot.runtime || {};
    const ready = plannerEligible(snapshot).length;
    const blocked = snapshot.tasks.filter((task) => plannerTaskStatus(task, plannerLoadDraft(snapshot.roadmap.path)) === 'blocked').length;
    const body = section === 'dependencies'
      ? `<div class="planner-integration-modal"><strong>Dependency map</strong><p>${snapshot.tasks.length} tasks are represented in the current roadmap snapshot. Select a task in the graph to focus upstream and downstream relationships.</p><div class="planner-detail-grid"><div class="planner-detail-block"><span>Nodes</span><strong>${snapshot.tasks.length}</strong></div><div class="planner-detail-block"><span>Ready</span><strong>${ready}</strong></div><div class="planner-detail-block"><span>Blocked</span><strong>${blocked}</strong></div><div class="planner-detail-block"><span>Current</span><strong>${escapeHtml(runtime.current_task_id || 'None')}</strong></div></div></div>`
      : section === 'executions'
        ? `<div class="planner-integration-modal"><strong>Execution monitor</strong><p>The unattended runtime remains authoritative. This draft can preview planner runs locally without mutating it.</p><div class="properties"><div class="property"><span>Run</span><strong>${escapeHtml(runtime.run_id || 'No run reported')}</strong></div><div class="property"><span>Phase</span><strong>${escapeHtml(runtime.phase || 'Idle')}</strong></div><div class="property"><span>Current task</span><strong>${escapeHtml(runtime.current_task_id || 'None')}</strong></div><div class="property"><span>Attempt</span><strong>${escapeHtml(runtime.current_attempt || 0)}</strong></div></div></div>`
        : section === 'artifacts'
          ? '<div class="planner-integration-modal"><strong>Artifacts</strong><p>Evidence and generated artifacts are available from the task verification boundary. This draft keeps the planner focused on selecting and sequencing work.</p></div>'
          : section === 'environments'
            ? '<div class="planner-integration-modal"><strong>Environments</strong><p>Local preview environment is active. PASI Bridge remains the control-plane connection for authoritative runtime state.</p><div class="property"><span>Bridge</span><strong>127.0.0.1:8765</strong></div></div>'
            : section === 'milestones'
              ? `<div class="planner-integration-modal"><strong>Milestones</strong><p>Use roadmap phases and GitHub Project iterations for human planning. PASI consumes the resulting roadmap structure.</p><div class="property"><span>Roadmap</span><strong>${escapeHtml(snapshot.roadmap.path)}</strong></div></div>`
              : section === 'team'
                ? '<div class="planner-integration-modal"><strong>Team</strong><p>This draft targets unattended local execution. Human ownership can be layered on later without changing task identity or dependency semantics.</p></div>'
                : section === 'overview'
                  ? `<div class="planner-integration-modal"><strong>Project overview</strong><p>Planner state is based on the authoritative roadmap snapshot and runtime ledger.</p><div class="planner-detail-grid"><div class="planner-detail-block"><span>Total</span><strong>${snapshot.tasks.length}</strong></div><div class="planner-detail-block"><span>Complete</span><strong>${snapshot.progress?.completed || 0}</strong></div><div class="planner-detail-block"><span>Ready</span><strong>${ready}</strong></div><div class="planner-detail-block"><span>Blocked</span><strong>${blocked}</strong></div></div></div>`
                  : '<div class="planner-integration-modal"><strong>Planner settings</strong><p>AI ranking, refresh cadence, and local draft controls are configured in this prototype through the visible planner controls.</p></div>';
    modal(title, body);
  }

  function bindPlannerInteractions(snapshot) {
    plannerBindTaskEvents(snapshot);
    plannerBindSearch();
    document.querySelectorAll('[data-planner-filter]').forEach((button) => {
      button.onclick = () => {
        plannerUi.queueFilter = button.dataset.plannerFilter;
        plannerRender();
      };
    });
    document.querySelectorAll('[data-planner-tab]').forEach((button) => {
      button.onclick = () => {
        plannerUi.tab = button.dataset.plannerTab;
        plannerRender();
      };
    });
    document.querySelectorAll('[data-planner-graph-task]').forEach((button) => {
      button.onclick = () => {
        plannerUi.selectedId = button.dataset.plannerGraphTask;
        plannerUi.graphFocus = button.dataset.plannerGraphTask;
        plannerRender();
      };
    });
    document.querySelectorAll('[data-planner-nav]').forEach((button) => {
      button.onclick = () => plannerNavigate(button.dataset.plannerNav, snapshot);
    });
    document.querySelectorAll('[data-planner-action]').forEach((button) => {
      button.onclick = async () => {
        const action = button.dataset.plannerAction;
        if (action === 'refresh') return renderPlanner();
        if (action === 'export') return plannerExport(snapshot);
        if (action === 'import') return plannerImportModal();
        if (action === 'toggle-sidebar') return document.body.classList.toggle('planner-sidebar-collapsed');
        if (action === 'fit') {
          plannerUi.graphFocus = plannerUi.selectedId;
          plannerRender();
          return;
        }
        if (action === 'clear-focus') {
          plannerUi.graphFocus = null;
          plannerRender();
          return;
        }
        if (action === 'notifications') return modal('Notifications', '<div class="empty-state">No new planner notifications.</div>');
        if (action === 'account') return modal('Planner account', '<div class="property"><span>Workspace</span><strong>Core Platform</strong></div><div class="property"><span>Mode</span><strong>Local draft</strong></div>');
      };
    });
    document.querySelectorAll('[data-planner-run-control]').forEach((button) => {
      button.onclick = () => {
        const action = button.dataset.plannerRunControl;
        if (action === 'run') return plannerStartRun();
        if (action === 'pause') return plannerTogglePause();
        if (action === 'stop') return plannerStopRun(false);
      };
    });
    document.querySelectorAll('[data-planner-status]').forEach((button) => {
      button.onclick = () => plannerSetTaskStatus(button.dataset.taskId, button.dataset.plannerStatus, snapshot);
    });
    document.querySelectorAll('[data-planner-stream-task]').forEach((button) => {
      button.onclick = () => {
        plannerUi.selectedId = button.dataset.plannerStreamTask;
        plannerUi.graphFocus = plannerUi.selectedId;
        plannerRender();
      };
    });
    document.querySelectorAll('[data-planner-integration]').forEach((button) => {
      button.onclick = () => {
        if (button.dataset.plannerIntegration === 'github') {
          modal('GitHub Projects', '<div class="planner-integration-modal"><strong>Human planning layer</strong><p>Use GitHub Projects for backlog, roadmap dates, quarterly planning, and human ordering. PASI will continue to enforce dependency eligibility and execution safety.</p><div class="form-actions"><button type="button" class="outline-button" onclick="window.closeModal()">Close</button></div></div>');
        } else {
          modal('PASI Bridge', '<div class="planner-integration-modal"><strong>Authenticated bridge</strong><p>Planner reads the authoritative roadmap, ledger, and runtime state through the PASI web API surface.</p><div class="property"><span>Endpoint</span><strong>127.0.0.1:8765</strong></div></div>');
        }
      };
    });
    document.querySelectorAll('[data-planner-workspace]').forEach((button) => {
      button.onclick = () => modal('Workspace', '<div class="form-stack"><label>Workspace<select><option>Core Platform</option><option>Automation</option><option>Operations</option></select></label><p class="muted">Workspace switching is a visual draft control.</p></div>');
    });
    document.querySelectorAll('[data-planner-menu]').forEach((button) => {
      button.onclick = () => {
        const task = snapshot.tasks.find((item) => item.id === button.dataset.plannerMenu);
        if (task) plannerTaskDetailModal(task, snapshot);
      };
    });
    document.querySelectorAll('#planner-ai-toggle').forEach((toggle) => {
      toggle.onchange = () => {
        localStorage.setItem('pasi-planner-ai', toggle.checked ? '1' : '0');
        plannerRender();
      };
    });
  }

  function renderPlanner() {
    if (!plannerUi.snapshot) return;
    plannerRender();
  }

  function renderPlannerImportedDeprecated(data) {
    renderPlannerImported(data);
  }

  function promptToChat(text){setView('chat');$('chat-input').value=text||'';$('chat-input').dispatchEvent(new Event('input'));$('chat-input').focus();}

  function bindEvents(){
    $('chat-form').addEventListener('submit',(event)=>{event.preventDefault();if($('send-chat').classList.contains('is-loading'))window.__pasActiveChatRequest?.abort();else void sendMessage();});
    $('chat-input').addEventListener('input',()=>{$('chat-input').style.height='auto';$('chat-input').style.height=`${Math.min($('chat-input').scrollHeight,240)}px`;});
    $('chat-input').addEventListener('keydown',(event)=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-form').requestSubmit();}});
    $('ai-mode').value=localStorage.getItem('pas-model')||'auto';$('ai-mode').addEventListener('change',()=>localStorage.setItem('pas-model',$('ai-mode').value));
    $('attach-button').onclick=()=>$('chat-file-input').click();$('chat-file-input').onchange=async(event)=>{try{if(event.target.files?.[0])await uploadFile(event.target.files[0]);}catch(error){toast(error.message);}finally{event.target.value='';}};
    $('modal-close').onclick=closeModal;document.querySelector('[data-close-modal]').onclick=closeModal;
    $('brand-home').onclick=()=>{state.projectId=null;state.project=null;state.chatId=null;state.folderId=null;draftChat();loadChats();};
    $('project-chat-button').onclick=()=>loadChat();$('clear-chat-list').onclick=()=>loadChats();
    $('account-button').onclick=()=>modal('Account',`<div class="form-stack"><div class="property"><span>Email</span><strong>${escapeHtml(state.user?.email||'')}</strong></div>${state.projectId?'<button id="account-project" class="outline-button">Project details</button>':''}<button id="account-settings" class="outline-button">Settings</button><button id="account-logout" class="danger-button">Log out</button></div>`);
    document.addEventListener('click',async(event)=>{
      const target=event.target.closest?.('[data-view],[data-prompt],[data-prompt-card],.chat-row,[data-msg-action],[data-tools-toggle],[data-tool-fetch],[data-open-project],.project-row,#calculations-toggle,[data-calculation-category],[data-major-page],[data-open-calculation],[data-open-calculation-group],[data-open-calculation-subgroup],#project-files,#project-calculations,#project-simulations,#project-engineering,#project-new-folder,#project-new-note,#project-upload,#close-files-panel,.file-open,.item-more,[data-back-chat],[data-back-calculations],[data-back-major],[data-toggle-plugin],[data-bulk],[data-search-chat],[data-search-project],[data-search-calculation],[data-search-note],[data-customize],#create-project-page,[data-connection-action],[data-plugin-action],[data-engineering-action],[data-evidence-action],.chat-title-menu,.chat-context-menu button,#share-current');
      if(!target)return;
      try{
        if(target.matches('.chat-context-menu button')){event.preventDefault();await chatAction(target.dataset.chatAction);document.querySelector('.chat-context-menu')?.remove();return;}
        if(target.matches('.chat-title-menu')){event.preventDefault();const r=target.getBoundingClientRect();openChatMenu(r.right-210,r.bottom+6);return;}
        if(target.matches('.chat-row')){await openChat(Number(target.dataset.chatId));return;}
        if(target.matches('[data-view="projects"]')){await openProjects();return;}
        if(target.matches('[data-view="planner"]')){await openPlanner();return;}
        if(target.matches('[data-view="education"]')){setView('education');window.renderEducationPage?.();return;}
        if(target.matches('[data-view="simulations"]')){setView('simulations');await window.openSimulationsView?.();return;}
        if(target.matches('[data-view="connections"]')){setView('connections');await window.openConnectionsView?.();return;}
        if(target.matches('[data-view="settings"]')){setView('settings');window.renderSettingsPage?.();return;}
        if(target.matches('[data-view="chat"],#new-chat,#new-chat-header')){draftChat();return;}
        if(target.matches('[data-prompt],[data-prompt-card]')){promptToChat(target.dataset.prompt||target.dataset.promptCard);return;}
        if(target.matches('[data-msg-action]')){event.preventDefault();await handleMessageAction(target);return;}
        if(target.matches('[data-tools-toggle]')){const log=target.nextElementSibling;if(log)log.hidden=!log.hidden;return;}
        if(target.matches('[data-tool-fetch]')){await window.fetchToolSource?.(target);return;}
        if(target.matches('[data-open-project],.project-row')){await openProject(Number(target.dataset.openProject||target.dataset.projectId));return;}
        if(target.matches('#calculations-toggle')){await window.toggleCalculationsMenu?.();return;}
        if(target.matches('[data-calculation-category]')){const section=target.closest('.calc-nav-section');const subnav=section?.querySelector('.calc-nav-subnav');if(subnav){subnav.hidden=!subnav.hidden;target.setAttribute('aria-expanded',String(!subnav.hidden));}return;}
        if(target.matches('[data-major-page]')){await window.openCalculationsView?.(target.dataset.majorPage);return;}
        if(target.matches('[data-open-calculation-group]')){await window.openCalculationGroupView?.(target.dataset.openCalculationGroup);return;}
        if(target.matches('[data-open-calculation-subgroup]')){await window.openCalculationSubgroupView?.(target.dataset.openCalculationSubgroup,target.dataset.calculationSubgroup);return;}
        if(target.matches('[data-open-calculation]')){await window.openCalculationDetailView?.(target.dataset.openCalculation);return;}
        if(target.matches('#project-files')){await showProjectFiles();return;}
        if(target.matches('#project-calculations')){setView('calculations');await window.openCalculationsView?.(state.calcMajor);return;}
        if(target.matches('#project-simulations')){setView('simulations');await window.openSimulationsView?.();return;}
        if(target.matches('#project-engineering')){setView('engineering');await window.openProjectEngineeringView?.();return;}
        if(target.matches('#project-new-folder')){await newItem('folder');return;}
        if(target.matches('#project-new-note')){await newItem('note');return;}
        if(target.matches('#project-upload')){$('chat-file-input').click();return;}
        if(target.matches('#close-files-panel')){$('project-files-panel').hidden=true;return;}
        if(target.matches('.item-more')){const row=target.closest('.file-row');await itemActions(row.dataset.kind,Number(row.dataset.id));return;}
        if(target.matches('.file-open')){return;}
        if(target.matches('[data-back-chat]')){if(state.chatId)await openChat(state.chatId);else draftChat();return;}
        if(target.matches('[data-back-calculations]')){await window.openCalculationsView?.();return;}
        if(target.matches('[data-back-major]')){await window.openCalculationsView?.(target.dataset.backMajor);return;}
        if(target.matches('[data-search-chat]')){closeModal();await openChat(Number(target.dataset.searchChat));return;}
        if(target.matches('[data-search-project]')){closeModal();await openProject(Number(target.dataset.searchProject));return;}
        if(target.matches('[data-search-calculation]')){closeModal();await window.openCalculationDetailView?.(target.dataset.searchCalculation);return;}
        if(target.matches('[data-search-note]')){const projectId=Number(target.dataset.searchProject||0);if(projectId&&projectId!==state.projectId)await openProject(projectId);const note=await api(`/api/projects/${state.projectId}/notes?id=${Number(target.dataset.searchNote)}`);modal(note.name||'Note',`<pre class="text-preview">${escapeHtml(note.content||'')}</pre>`);return;}
        if(target.matches('[data-bulk]')){await bulkAction(target.dataset.bulk);return;}
        if(target.matches('#account-project')){closeModal();await editProject();return;}
        if(target.matches('#account-settings')){closeModal();setView('settings');window.renderSettingsPage?.();return;}
        if(target.matches('#account-logout')){await signOut();return;}
        if(target.matches('[data-toggle-plugin]')){await window.togglePlugin?.(target.dataset.togglePlugin,target.textContent==='Enable');return;}
        if(target.matches('[data-connection-action]')){await window.connectionAction?.(target.dataset.connectionAction);return;}
        if(target.matches('[data-plugin-action]')){await window.pluginAction?.(target.dataset.pluginAction);return;}
        if(target.matches('[data-customize]')){await window.renderCustomizeTab?.(target.dataset.customize);return;}
        if(target.matches('[data-engineering-action]')){await window.engineeringAction?.(target.dataset.engineeringAction,target.dataset.id,target.dataset.kind);return;}
        if(target.matches('[data-evidence-action]')){await window.evidenceAction?.(target.dataset.evidenceAction,target.dataset.id);return;}
        if(target.matches('#share-current')){await shareCurrent();return;}
        if(target.matches('#create-project-page')){await createProject();return;}
      }catch(error){toast(error.message||error);}
    },true);
    document.addEventListener('change',async(event)=>{const target=event.target;try{if(target.matches('.item-check')){const row=target.closest('.file-row');const key=token(row.dataset.kind,row.dataset.id);target.checked?state.selected.add(key):state.selected.delete(key);updateSelectionCount();}if(target.id==='project-sort'){state.sort=target.value;await showProjectFiles();}}catch(error){toast(error.message);}},true);
    document.addEventListener('contextmenu',(event)=>{const row=event.target.closest?.('.file-row');const chatRow=event.target.closest?.('.chat-row');if(chatRow){event.preventDefault();state.chatId=Number(chatRow.dataset.chatId);openChatMenu(event.clientX,event.clientY);}else if(row&&state.projectId){event.preventDefault();const key=token(row.dataset.kind,row.dataset.id);state.selected.clear();state.selected.add(key);updateSelectionCount();itemActions(row.dataset.kind,Number(row.dataset.id)).catch((error)=>toast(error.message));}});
    document.addEventListener('keydown',(event)=>{const typing=event.target?.matches?.('input,textarea,select,[contenteditable="true"]');const key=event.key.toLowerCase();if((event.ctrlKey||event.metaKey)&&key==='o'&&!typing){event.preventDefault();draftChat();}else if((event.ctrlKey||event.metaKey)&&key==='k'&&!typing){event.preventDefault();$('global-search').focus();$('global-search').select();}else if((event.ctrlKey||event.metaKey)&&key==='/'&&!typing){event.preventDefault();setView('settings');window.renderSettingsPage?.();}else if((event.ctrlKey||event.metaKey)&&key==='c'&&!typing&&state.selected.size){event.preventDefault();state.clipboard=selectedItems();toast('Copied.','ok');}else if((event.ctrlKey||event.metaKey)&&key==='v'&&!typing&&state.projectId&&state.clipboard.length){event.preventDefault();bulkAction('paste').catch((error)=>toast(error.message));}else if(event.key==='Escape'){document.querySelectorAll('.chat-context-menu,.global-search-results').forEach((node)=>node.remove());closeModal();closeSidebar();}if(!typing&&document.querySelector('.chat-context-menu')&&['p','r','d'].includes(key))chatAction({p:'pin',r:'rename',d:'delete'}[key]).catch((error)=>toast(error.message));});
    $('global-search').addEventListener('input',()=>{clearTimeout(window.__pasSearchTimer);const query=$('global-search').value.trim();if(!query){document.querySelector('.global-search-results')?.remove();return;}window.__pasSearchTimer=setTimeout(()=>search(query).catch((error)=>toast(error.message)),160);});
    $('global-search').addEventListener('keydown',(event)=>{if(event.key==='Enter'&&event.target.value.trim()){event.preventDefault();search(event.target.value.trim()).catch((error)=>toast(error.message));}});
  }

  async function signOut(){await send('/api/auth/logout',{});state.user=null;await refreshAuth();toast('Logged out.','ok');}

  window.openChat=openChat;window.openProject=openProject;window.loadChats=loadChats;window.loadChat=loadChat;window.showProjectFiles=showProjectFiles;window.newItem=newItem;window.renameItem=renameItem;window.itemActions=itemActions;window.openItem=openItem;window.updateSelectionCount=updateSelectionCount;window.bulkAction=bulkAction;window.bindProjectFilesInteractions=bindProjectFilesInteractions;window.renderMessages=renderMessages;window.sendMessage=sendMessage;window.modal=modal;window.closeModal=closeModal;window.setView=setView;window.applyTheme=applyTheme;window.api=api;window.send=send;window.patch=patch;window.del=del;window.state=state;window.escapeHtml=escapeHtml;window.attr=attr;window.editProject=editProject;

  (async function init(){try{applyTheme();bindAccessibility();bindEvents();await refreshAuth();await loadManifest();await loadChats();setView('chat');renderMessages([],[]);syncAccessibility();window.hydrateUI?.();}catch(error){window.showError(error);}})();
})();
