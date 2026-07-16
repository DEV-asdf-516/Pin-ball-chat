import { $ } from "./dom.js";

export function bindFormTabs(rootId) {
  $(rootId).addEventListener("click", (event) => {
    const button = event.target.closest("[data-form-tab]");
    if (button) activateFormTab(rootId, button.dataset.formTab);
  });
}

export function activateFormTab(rootId, tab) {
  const root = $(rootId);
  root.querySelectorAll("[data-form-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.formTab === tab);
  });
  root.querySelectorAll("[data-form-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.formPanel !== tab;
  });
}
