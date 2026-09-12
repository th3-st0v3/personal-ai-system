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
    await originalShowProjectFiles();
    if (state.sort === "none" && state.items.length) {
      const ordered = applyLocalOrder(state.items);
      state.items = ordered;
      const list = $("file-list");
      if (list) ordered.forEach(item => {
        const row = list.querySelector(`.file-row[data-kind="${CSS.escape(item.kind)}"][data-id="${item.id}"]`);
        if (row) list.appendChild(row);
      });
    }
    const count = $("selection-count");
    if (count && state.selected.size) {
      const actions = document.createElement("div");
      actions.className = "bulk-actions";
      actions.innerHTML = `<button class="quiet-button" data-bulk="archive">Archive</button><button class="quiet-button" data-bulk="invalidate">Invalidate</button><button class="quiet-button" data-bulk="copy">Copy</button><button class="quiet-button" data-bulk="delete">Delete</button>`;
      count.insertAdjacentElement("afterend", actions);
      actions.querySelectorAll("[data-bulk]").forEach(button => button.addEventListener("click", async () => {
        const action = button.dataset.bulk;
        const selection = [...state.selected].map(value => { const [kind, id] = value.split(":"); return { kind, id: Number(id) }; });
        try {
          if (action === "copy") { state.clipboard = selection; return; }
          if (action === "delete") await send(`/api/projects/${state.projectId}/delete`, { selection });
          else await Promise.all(selection.map(item => send(`/api/projects/${state.projectId}/lifecycle`, { ...item, status: action === "archive" ? "Archived" : "Invalidated" })));
          state.selected.clear();
          await showProjectFiles();
        } catch (error) { alert(error.message); }
      }));
    }
  };

  const originalEditNote = window.editNote;
  window.editNote = function editNoteFixed(note) {
    const metadata = note.metadata || {};
    modal("Edit note", `<div class="note-editor"><input id="note-title" value="${attr(note.name)}"><textarea id="note-description" placeholder="Description">${esc(metadata.description || "")}</textarea><textarea id="note-content">${esc(note.content || "")}</textarea><div class="form-actions"><button class="outline-button" id="delete-note">Delete</button><button class="primary-button" id="save-note">Save</button></div></div>`);
    $("save-note").onclick = async () => {
      await patch(`/api/projects/${state.projectId}/notes`, { id: note.id, title: $("note-title").value, content: $("note-content").value, metadata: { ...metadata, description: $("note-description").value } });
      closeModal();
      showProjectFiles();
    };
    $("delete-note").onclick = async () => {
      if (!confirm("Delete this note?")) return;
      await del(`/api/projects/${state.projectId}/notes`, { id: note.id });
      closeModal();
      showProjectFiles();
    };
  };
})();
