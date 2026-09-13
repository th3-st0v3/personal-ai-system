"use strict";

const workspaceItems = () => [...document.querySelectorAll("#items .item")];
const focusItem = (item) => { if (!item) return; item.focus(); item.scrollIntoView({ block: "nearest" }); };

new MutationObserver(() => workspaceItems().forEach(item => item.tabIndex = 0)).observe(document.getElementById("items"), { childList: true, subtree: true });

document.addEventListener("keydown", event => {
  const menu = document.getElementById("menu");
  if (event.key === "Escape" && !menu.hidden) { menu.hidden = true; return; }
  const item = event.target.closest?.("#items .item");
  if (!item) return;
  const items = workspaceItems();
  const index = items.indexOf(item);
  if (event.key === "ArrowDown" || event.key === "ArrowRight") { event.preventDefault(); focusItem(items[Math.min(index + 1, items.length - 1)]); }
  else if (event.key === "ArrowUp" || event.key === "ArrowLeft") { event.preventDefault(); focusItem(items[Math.max(index - 1, 0)]); }
  else if (event.key === "Enter") { event.preventDefault(); item.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); }
  else if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); item.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: item.getBoundingClientRect().left, clientY: item.getBoundingClientRect().bottom })); }
  else if (event.key === "Delete") { event.preventDefault(); item.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: item.getBoundingClientRect().left, clientY: item.getBoundingClientRect().bottom })); setTimeout(() => document.querySelector("#menu [data-action='delete']")?.click(), 0); }
});
