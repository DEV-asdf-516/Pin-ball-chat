import { el } from "../dom.js";

export function mainTabs(active) {
  return el("div", { className: "seg two" }, [
    el("button", { className: active === "plots" ? "active" : "", text: "플롯", dataset: { tab: "plots" } }),
    el("button", { className: active === "conversations" ? "active" : "", text: "대화", dataset: { tab: "conversations" } }),
  ]);
}

export function refreshButton(id) {
  return el("button", {
    id,
    className: "icon-btn",
    text: "↻",
    attrs: { title: "새로고침", "aria-label": "새로고침" },
  });
}

export function searchField(id) {
  return el("label", { className: "search-field", attrs: { for: id } }, [
    el("span", { className: "search-icon", attrs: { "aria-hidden": "true" } }),
    el("input", { id, attrs: { placeholder: "", autocomplete: "off", type: "search" } }),
  ]);
}
