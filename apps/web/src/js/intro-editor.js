import { $, el, setChildren } from "./dom.js";

const ROLES = [
  ["assistant", "AI"],
  ["user", "사용자"],
];

export function renderIntroEditor(id, intro = null) {
  const blocks = normalizeBlocks(intro);
  setChildren($(id), [
    el("div", { className: "intro-blocks" }, blocks.map(introBlock)),
    el("button", { className: "intro-add-btn", type: "button", text: "+", dataset: { introAdd: "true" } }),
  ]);
}

export function bindIntroEditor(id) {
  $(id).onclick = (event) => {
    const editor = $(id);
    const add = event.target.closest("[data-intro-add]");
    if (add) {
      editor.querySelector(".intro-blocks").append(introBlock({ type: "assistant", content: "" }));
      return;
    }

    const remove = event.target.closest("[data-intro-remove]");
    if (remove) {
      remove.closest("[data-intro-block]")?.remove();
      return;
    }

    const role = event.target.closest("[data-intro-role]");
    if (!role) return;
    const block = role.closest("[data-intro-block]");
    block.dataset.introType = role.dataset.introRole;
    block.querySelectorAll("[data-intro-role]").forEach((button) => {
      button.classList.toggle("active", button === role);
    });
  };
}

export function introValue(id) {
  const blocks = [...$(id).querySelectorAll("[data-intro-block]")]
    .map((block) => ({
      type: block.dataset.introType || "assistant",
      content: block.querySelector("[data-intro-content]")?.value.trim() || "",
    }))
    .filter((block) => block.content);
  return blocks.length ? { blocks } : null;
}

function normalizeBlocks(intro) {
  const blocks = Array.isArray(intro?.blocks) ? intro.blocks : [];
  const normalized = blocks
    .filter((block) => block && ["assistant", "user"].includes(block.type) && block.content)
    .map((block) => ({ type: block.type, content: block.content }));
  return normalized.length ? normalized : [{ type: "assistant", content: "" }];
}

function introBlock(block) {
  const type = block.type || "assistant";
  return el("div", { className: "intro-block", dataset: { introBlock: "true", introType: type } }, [
    el("div", { className: "intro-block-head" }, [
      el("div", { className: "intro-role-toggle" }, ROLES.map(([value, label]) => (
        el("button", {
          type: "button",
          className: value === type ? "active" : "",
          text: label,
          dataset: { introRole: value },
        })
      ))),
      el("button", { className: "intro-remove-btn", type: "button", text: "×", dataset: { introRemove: "true" } }),
    ]),
    el("textarea", { text: block.content || "", attrs: { rows: "5", placeholder: "" }, dataset: { introContent: "true" } }),
  ]);
}
