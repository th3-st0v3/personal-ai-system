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
    state.view = view; $('home-view').hidden=view!=='chat'; $('page-view').hidden=view==='chat';
    document.querySelectorAll('.nav-item[data-view]').forEach((button)=>button.classList.toggle('active',button.dataset.view===view));
    if (view!=='chat') $('project-tools').hidden=true; syncAccessibility();
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
