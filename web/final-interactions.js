(() => {
  const $=(id)=>document.getElementById(id);
  const toast=(message,ok=false)=>{if(typeof window.showError==='function'&&!ok)return window.showError(new Error(String(message)));const node=document.createElement('div');node.className=`ui-toast ${ok?'ok':'error'}`;node.textContent=String(message);document.body.appendChild(node);setTimeout(()=>node.remove(),3000);};
  const stripLegacy=()=>document.querySelectorAll('[data-msg-action]').forEach((node)=>{node.dataset.finalMsgAction=node.dataset.msgAction;node.removeAttribute('data-msg-action');});
  const sendRetry=async(promptText)=>{
    if(!state.chatId||!promptText)return;
    const mode=$('ai-mode')?.value||'auto';
    const model=({auto:'profile:auto',claude:'profile:claude-opus',gpt:'profile:gpt-5.4',gemini:'profile:gemini-3.1-pro',free:'profile:free'})[mode]||'profile:auto';
    const result=await api(`/api/chats/${state.chatId}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:promptText,mode:'auto',model})});
    if(window.__pasRenderMessages)window.__pasRenderMessages(result.messages||[],result.tool_events||[]);
    if($('chat-title'))$('chat-title').textContent=result.title||$('chat-title').textContent;
    await loadChats();
  };
  const branch=async()=>{
    const result=await api(`/api/chats/${state.chatId}/branch`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:`${$('chat-title')?.textContent||'Chat'} — branch`})});
    state.chatId=result.id;await loadChats();await loadChat();toast('Chat branched.',true);
  };
  const feedback=async(article,rating)=>{
    const index=Number(article?.dataset.messageIndex??-1);const chat=await api(`/api/chats/${state.chatId}`);const messages=(chat.messages||[]).filter((m)=>m.role==='assistant');const message=messages[index];
    if(!message?.id)throw new Error('Assistant message could not be identified.');
    await api(`/api/chats/${state.chatId}/feedback`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:message.id,rating})});
    if(window.__pasRenderMessages)window.__pasRenderMessages(chat.messages||[],[]);toast('Feedback saved.',true);
  };
  document.addEventListener('click',(event)=>{
    const action=event.target.closest?.('[data-final-msg-action]');if(!action)return;
    event.preventDefault();event.stopImmediatePropagation();
    const article=action.closest('.message');const type=action.dataset.finalMsgAction;const content=article?.querySelector('.content,.user-bubble')?.textContent||'';
    Promise.resolve().then(async()=>{
      if(type==='copy'){await navigator.clipboard.writeText(content);toast('Copied.',true);return;}
      if(type==='share'){if(navigator.share)await navigator.share({text:content});else{await navigator.clipboard.writeText(content);toast('Copied share text.',true);}return;}
      if(type==='edit'){$('chat-input').value=content;$('chat-input').focus();return;}
      if(type==='retry'){await sendRetry(article?.dataset.retryPrompt||'');return;}
      if(type==='branch'){await branch();return;}
      if(type==='rate-up'||type==='rate-down'){await feedback(article,type==='rate-up'?'up':'down');}
    }).catch((error)=>toast(error?.message||error));
  },true);
  const observe=()=>stripLegacy();
  window.addEventListener('load',observe,{once:true});
  new MutationObserver(observe).observe(document.body,{childList:true,subtree:true});
})();
