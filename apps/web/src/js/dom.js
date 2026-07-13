export const $ = (id) => document.getElementById(id);

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.id) node.id = options.id;
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.type) node.type = options.type;
  if (options.value !== undefined) node.value = options.value;
  if (options.selected) node.selected = true;
  if (options.dataset) Object.assign(node.dataset, options.dataset);
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) node.setAttribute(name, value);
  }
  node.append(...children.filter(Boolean));
  return node;
}

export function setChildren(parent, children) {
  parent.replaceChildren(...children.filter(Boolean));
}

export function parseJson(value) {
  try {
    return value ? JSON.parse(value) : {};
  } catch {
    return {};
  }
}

export function toast(message) {
  clearTimeout(toast.timer);
  $("toast").textContent = message;
  $("toast").classList.add("show");
  toast.timer = setTimeout(() => $("toast").classList.remove("show"), 1300);
}

export function confirmDialog(message, options = {}) {
  return openDialog({
    title: options.title || "확인",
    message,
    okText: options.okText || "확인",
    cancelText: options.cancelText || "취소",
    danger: Boolean(options.danger),
  });
}

export function promptDialog(title, value = "", options = {}) {
  return openDialog({
    title,
    value,
    multiline: options.multiline !== false,
    okText: options.okText || "저장",
    cancelText: options.cancelText || "취소",
  });
}

function openDialog({ title, message = "", value = null, multiline = false, okText, cancelText, danger = false }) {
  const root = $("appDialog");
  const panel = $("appDialogPanel");
  return new Promise((resolve) => {
    const input = value === null ? null : el(multiline ? "textarea" : "input", {
      id: "appDialogInput",
      value,
      attrs: multiline ? { rows: "8" } : {},
    });
    const close = (result) => {
      root.classList.remove("open");
      root.onpointerdown = null;
      panel.onsubmit = null;
      panel.onkeydown = null;
      setChildren(panel, []);
      resolve(result);
    };
    setChildren(panel, [
      el("strong", { className: "dialog-title", text: title }),
      message ? el("div", { className: "dialog-message", text: message }) : null,
      input,
      el("div", { className: "dialog-actions" }, [
        el("button", { type: "button", text: cancelText, dataset: { dialogCancel: "true" } }),
        el("button", { className: danger ? "danger" : "primary", type: "submit", text: okText }),
      ]),
    ]);
    root.classList.add("open");
    input?.focus();
    input?.select();
    root.onpointerdown = (event) => {
      if (event.target === root || event.target.closest("[data-dialog-cancel]")) close(null);
    };
    panel.onsubmit = (event) => {
      event.preventDefault();
      close(input ? input.value : true);
    };
    panel.onkeydown = (event) => {
      if (event.key === "Escape") close(null);
    };
  });
}

export function toggleDropdown(menu, trigger) {
  if (!menu) return;
  const wasOpen = menu.classList.contains("open");
  closeDropdowns();
  if (!wasOpen) openDropdown(menu, trigger);
}

export function closeDropdowns(selector = ".dropdown.open") {
  document.querySelectorAll(selector).forEach((node) => {
    node.classList.remove("open");
    node.style.left = "";
    node.style.top = "";
  });
}

export function openDropdown(menu, trigger) {
  if (!menu || !trigger) return;
  const rect = trigger.getBoundingClientRect();
  menu.style.minWidth = `${Math.max(104, rect.width)}px`;
  menu.classList.add("open");
  const menuRect = menu.getBoundingClientRect();
  const margin = 8;
  const left = Math.min(window.innerWidth - menuRect.width - margin, Math.max(margin, rect.left));
  const top = Math.min(window.innerHeight - menuRect.height - margin, rect.bottom + 4);
  menu.style.left = `${left}px`;
  menu.style.top = `${Math.max(margin, top)}px`;
}
