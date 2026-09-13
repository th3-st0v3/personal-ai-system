(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>\"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const renameCurrent = async () => {
    if (!state.chatId) return;
    const current = $('chat-title')?.textContent?.trim() || 'New chat';
    const title = prompt('Rename chat', current);
    if (!title?.trim() || title.trim() === current) return;
    await patch(`/api/chats/${state.chatId}`, {title:title.trim()});
    $('chat-title').textContent = title.trim();
    await loadChats();
  };
  const makeMenuButton = () => {
    const line = document.querySelector('.chat-title-line');
    if (!line || $('chat-title-menu')) return;
    const button = document.createElement('button');
    button.id='chat-title-menu'; button.type='button'; button.className='icon-button chat-title-menu'; button.setAttribute('aria-label','Chat actions'); button.title='Chat actions'; button.textContent='⋯';
    line.appendChild(button);
    button.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();const rect=button.getBoundingClientRect();if(typeof chatMenu==='function') chatMenu(rect.right-210,rect.bottom+6);});
  };
  const bindTitle = () => {
    const title=$('chat-title');
    if (!title || title.dataset.renameBound==='1') return;
    title.dataset.renameBound='1'; title.tabIndex=0; title.title='Rename chat';
    title.addEventListener('click',(event)=>{event.preventDefault();renameCurrent().catch((e)=>window.showError?.(e));});
    title.addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();renameCurrent().catch((e)=>window.showError?.(e));}});
  };
  const observer = new MutationObserver(()=>{bindTitle();makeMenuButton();});
  observer.observe(document.body,{childList:true,subtree:true});
  window.addEventListener('load',()=>{bindTitle();makeMenuButton();},{once:true});
})();
