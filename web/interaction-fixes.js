(() => {
  window.newItem = async function newItem(kind) {
    if (!state.projectId) return;
    modal(kind === "folder" ? "New folder" : "New note", `<form id="create-item-form" class="form-stack"><label>${kind === "folder" ? "Name" : "Title"}<input name="name" required></label>${kind === "note" ? `<label>Content<textarea name="content"></textarea></label>` : ""}<div class="form-actions"><button type="button" class="outline-button" id="create-item-cancel">Cancel</button><button class="primary-button">Create</button></div></form>`);
    $("create-item-cancel").onclick = closeModal;
    $("create-item-form").onsubmit = async event => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target));
      try {
        if (kind === "folder") await send(`/api/projects/${state.projectId}/folders`, { name: values.name, parent_folder_id: state.folderId });
        else await send(`/api/projects/${state.projectId}/notes`, { title: values.name, content: values.content || "", folder_id: state.folderId });
        closeModal();
        await showProjectFiles();
      } catch (error) {
        $("create-item-form").insertAdjacentHTML("afterend", `<div class="error">${esc(error.message)}</div>`);
      }
    };
    $("create-item-form").querySelector("input")?.focus();
  };
})();
