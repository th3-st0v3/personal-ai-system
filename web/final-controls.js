(() => {
  const $=(id)=>document.getElementById(id);
  const openMenu=(x,y)=>{
    document.querySelector('.final-chat-menu')?.remove();
    const menu=document.createElement('div');menu.className='final-chat-menu ux-context-menu';menu.style.left=`${Math.max(8,Math.min(x,innerWidth-210))}px`;menu.style.top=`${Math.max(8,Math.min(y,innerHeight-220))}px`;
    [['Rename','rename'],['Pin / unpin','pin'],['Move to project','move'],['Share chat','share'],['Delete','delete']].forEach(([label,action])=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.chatAction=action;menu.appendChild(button);});
    document.body.appendChild(menu);
  };
  const currentChat=async()=>{
    if(!state.chatId)return null;
    return api(`/api/chats/${state.chatId}`);
  };
  const runAction=async(action)=>{
    const chat=await currentChat();if(!chat)return;
    if(action==='rename'){const value=prompt('Rename chat',chat.title||'New chat');if(value?.trim()){await patch(`/api/chats/${state.chatId}`,{title:value.trim()});$('chat-title').textContent=value.trim();await loadChats();}}
    if(action==='pin'){await patch(`/api/chats/${state.chatId}`,{pinned:!chat.pinned});await loadChats();}
    if(action==='move'){const projects=await api('/api/projects');const raw=prompt(`Project ID (blank = personal)\n${projects.map(p=>`${p.id}: ${p.name}`).join('\n')}`);if(raw!==null){const id=raw.trim()?Number(raw):null;if(raw.trim()&&!Number.isInteger(id))throw new Error('Project ID must be an integer.');await patch(`/api/chats/${state.chatId}`,{project_id:id});await loadChats();}}
    if(action==='share'){if(navigator.share)await navigator.share({title:chat.title||'Chat',text:`${chat.title||'Chat'}\n${location.href}`});else{await navigator.clipboard.writeText(location.href);window.showError?.(new Error('Chat link copied to clipboard.'));}}
    if(action==='delete'){if(!confirm('Delete this chat?'))return;await del(`/api/chats/${state.chatId}`);state.chatId=null;await loadChats();setView('chat');$('chat-title').textContent='New chat';}
  };
  const renameCurrent=()=>runAction('rename');
  const bind=()=>{
    const title=$('chat-title');
    if(title&&!title.dataset.renameBound){title.dataset.renameBound='1';title.tabIndex=0;title.title='Rename chat';title.addEventListener('click',(e)=>{e.preventDefault();renameCurrent().catch((err)=>window.showError?.(err));});title.addEventListener('keydown',(e)=>{if(e.key==='Enter'){e.preventDefault();renameCurrent().catch((err)=>window.showError?.(err));}});}
    const line=document.querySelector('.chat-title-line');
    if(line&&!$('chat-title-menu')){const button=document.createElement('button');button.id='chat-title-menu';button.type='button';button.className='icon-button chat-title-menu';button.textContent='⋯';button.title='Chat actions';button.setAttribute('aria-label','Chat actions');button.addEventListener('click',(e)=>{e.preventDefault();e.stopPropagation();const r=button.getBoundingClientRect();openMenu(r.right-200,r.bottom+6);});line.appendChild(button);}
  };
  document.addEventListener('click',(event)=>{
    const action=event.target.closest?.('[data-chat-action]');
    if(action){event.preventDefault();event.stopPropagation();runAction(action.dataset.chatAction).catch((err)=>window.showError?.(err)).finally(()=>document.querySelector('.final-chat-menu')?.remove());return;}
    const menu=document.querySelector('.final-chat-menu');if(menu&&!menu.contains(event.target)&&!event.target.closest('#chat-title-menu'))menu.remove();
  });
  document.addEventListener('keydown',(event)=>{if(event.key==='Escape')document.querySelector('.final-chat-menu')?.remove();if(!event.target.matches?.('input,textarea,[contenteditable=true]')&&document.querySelector('.final-chat-menu')){if(event.key.toLowerCase()==='p'){event.preventDefault();runAction('pin').catch((err)=>window.showError?.(err));}if(event.key.toLowerCase()==='r'){event.preventDefault();runAction('rename').catch((err)=>window.showError?.(err));}if(event.key.toLowerCase()==='d'){event.preventDefault();runAction('delete').catch((err)=>window.showError?.(err));}}});
  new MutationObserver(bind).observe(document.body,{childList:true,subtree:true});
  window.addEventListener('load',bind,{once:true});
})();
