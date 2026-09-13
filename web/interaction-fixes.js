(() => {
  window.newItem = async function newItem(kind) {
    if (!state.projectId) return;
    modal(kind === "folder" ? "New folder" : "New note", `<form id="create-item-form" class="form-stack"><label>${kind === "folder" ? "Name" : "Title"}<input name="name" required></label>${kind === "note" ? `<label>Description<textarea name="description" placeholder="Short description"></textarea></label><label>Content<textarea name="content"></textarea></label>` : ""}<div class="form-actions"><button type="button" class="outline-button" id="create-item-cancel">Cancel</button><button class="primary-button">Create</button></div></form>`);
    $("create-item-cancel").onclick = closeModal;
    $("create-item-form").onsubmit = async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target));
      try {
        if (kind === "folder") await send(`/api/projects/${state.projectId}/folders`, { name: values.name, parent_folder_id: state.folderId });
        else await send(`/api/projects/${state.projectId}/notes`, { title: values.name, content: values.content || "", folder_id: state.folderId, metadata: { description: values.description || "" } });
        closeModal();
        await showProjectFiles();
      } catch (error) {
        $("create-item-form").insertAdjacentHTML("afterend", `<div class="error">${esc(error.message)}</div>`);
      }
    };
    $("create-item-form").querySelector("input")?.focus();
  };

  const originalShowProjectFiles = window.showProjectFiles;
  window.showProjectFiles = async function showProjectFilesFixed() {
    const desiredSort = state.sort;
    if (desiredSort === "none") state.sort = "a_z";
    try { await originalShowProjectFiles(); } finally { state.sort = desiredSort; }
    if (desiredSort === "none" && state.items.length) {
      state.items = applyLocalOrder(state.items);
      const list = $("file-list");
      if (list) state.items.forEach(item => {
        const row = [...list.children].find(child => child.dataset?.kind === item.kind && Number(child.dataset.id) === Number(item.id));
        if (row) list.appendChild(row);
      });
    }
    const count = $("selection-count");
    if (count && state.selected.size && !count.parentElement.querySelector(".bulk-actions")) {
      const actions = document.createElement("div"); actions.className = "bulk-actions";
      actions.innerHTML = `<button class="quiet-button" data-bulk="archive">Archive</button><button class="quiet-button" data-bulk="invalidate">Invalidate</button><button class="quiet-button" data-bulk="copy">Copy</button><button class="quiet-button" data-bulk="paste">Paste</button><button class="quiet-button" data-bulk="delete">Delete</button>`;
      count.insertAdjacentElement("afterend", actions);
      actions.querySelectorAll("[data-bulk]").forEach(button => button.addEventListener("click", async () => {
        const action = button.dataset.bulk;
        const selection = [...state.selected].map(value => { const [kind, id] = value.split(":"); return { kind, id: Number(id) }; });
        try {
          if (action === "copy") { state.clipboard = selection; return; }
          if (action === "paste") { if (!state.clipboard.length) return alert("Nothing is copied."); await send(`/api/projects/${state.projectId}/paste`, { selection: state.clipboard, target_folder_id: state.folderId }); }
          else if (action === "delete") await send(`/api/projects/${state.projectId}/delete`, { selection });
          else await Promise.all(selection.map(item => send(`/api/projects/${state.projectId}/lifecycle`, { ...item, status: action === "archive" ? "Archived" : "Invalidated" })));
          state.selected.clear(); await showProjectFiles();
        } catch (error) { alert(error.message); }
      }));
    }
  };

  const originalEditNote = window.editNote;
  window.editNote = function editNoteFixed(note) {
    const metadata = note.metadata || {};
    modal("Edit note", `<div class="note-editor"><input id="note-title" value="${attr(note.name)}"><textarea id="note-description" placeholder="Description">${esc(metadata.description || "")}</textarea><textarea id="note-content" placeholder="Content">${esc(note.content || "")}</textarea><div class="form-actions"><button class="outline-button" id="delete-note">Delete</button><button class="primary-button" id="save-note">Save</button></div></div>`);
    $("save-note").onclick = async () => { try { await patch(`/api/projects/${state.projectId}/notes`, { id: note.id, title: $("note-title").value, content: $("note-content").value, metadata: { ...metadata, description: $("note-description").value } }); closeModal(); await showProjectFiles(); } catch (error) { alert(error.message); } };
    $("delete-note").onclick = async () => { if (!confirm("Delete this note?")) return; try { await del(`/api/projects/${state.projectId}/notes`, { id: note.id }); closeModal(); await showProjectFiles(); } catch (error) { alert(error.message); } };
  };

  window.renderProjectTools = function renderProjectToolsFixed() {
    if (!state.project) return;
    $("project-files-panel").hidden = true;
    $("project-files-panel").innerHTML = `<div class="properties"><div class="property"><span>Project</span><strong>${esc(state.project.name)}</strong></div><div class="property"><span>Description</span><strong>${esc(state.project.description || "") || "No description"}</strong></div><div class="form-actions"><button id="edit-project" class="outline-button">Edit project</button><button id="delete-project" class="outline-button">Delete project</button></div></div>`;
    $("edit-project").onclick = editProject;
    $("delete-project").onclick = async () => { if (!confirm("Delete this project and its project data?")) return; try { await del(`/api/projects/${state.projectId}`); state.projectId=null; state.project=null; state.chatId=null; state.folderId=null; $("project-tools").hidden=true; setView("chat"); await loadProjects(); await loadChats(); await loadChat(); } catch(error) { alert(error.message); } };
  };

  window.sendChat = async function sendChatFixed() {
    const input=$("chat-input"),content=input.value.trim(),mode=$("ai-mode").value;if(!content)return;
    if(!state.chatId){const r=await send("/api/chats",{project_id:state.projectId});state.chatId=r.id;}
    input.value="";$("send-chat").disabled=true;
    try { const result=await send(`/api/chats/${state.chatId}/messages`,{content,mode});chatMessages(result.messages);$("chat-title").textContent=result.title;await loadChats(); }
    catch(e){$("chat-messages").insertAdjacentHTML("beforeend",`<div class="error">${esc(e.message)}</div>`)}
    finally{$("send-chat").disabled=false}
  };

  document.addEventListener("click", event => {
    const button=event.target.closest(".file-open");
    if(!button) return;
    event.stopImmediatePropagation();
    const row=button.closest(".file-row");
    if(!row) return;
    const itemToken=token(row.dataset.kind,row.dataset.id);
    if(event.ctrlKey||event.metaKey){state.selected.has(itemToken)?state.selected.delete(itemToken):state.selected.add(itemToken)}else{state.selected.clear();state.selected.add(itemToken)}
    updateSelectionCount();
  }, true);

  document.addEventListener("keydown", async event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const active=document.activeElement;
    if (active?.matches("input,textarea,[contenteditable=true]")) return;
    if (event.key.toLowerCase()==="c" && state.selected.size) { event.preventDefault(); state.clipboard=[...state.selected].map(value=>{const [kind,id]=value.split(":");return {kind,id:Number(id)}}); }
    if (event.key.toLowerCase()==="v" && state.projectId && state.clipboard.length) { event.preventDefault(); try { await send(`/api/projects/${state.projectId}/paste`,{selection:state.clipboard,target_folder_id:state.folderId}); await showProjectFiles(); } catch(error){ alert(error.message); } }
  });
})();
