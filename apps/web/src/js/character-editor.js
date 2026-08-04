import { apiBase } from "./api.js";
import { $, bindGrowingTextarea, el, parseJson, setChildren } from "./dom.js";

export const MAX_CHARACTER_SLOTS = 10;
let slotSequence = 0;

export function renderCharacterEditor(id, characters = []) {
  const root = $(id);
  if (!root) return;
  const ordered = [...characters].sort(
    (left, right) => (left.sort_order ?? left.sortOrder ?? 0) - (right.sort_order ?? right.sortOrder ?? 0),
  );
  const slots = ordered.length ? ordered : [null];
  setChildren(root, [
    el("div", { className: "character-slots" }, slots.map((character) => characterSlot(character))),
    el("button", {
      className: "character-add-btn",
      type: "button",
      text: "+",
      dataset: { characterAdd: "true" },
    }),
  ]);
  root.querySelectorAll("[data-character-source]").forEach((textarea) => bindGrowingTextarea(textarea));
  refreshControls(root);
}

export function bindCharacterEditor(id) {
  const root = $(id);
  if (!root) return;

  root.onclick = (event) => {
    const add = event.target.closest("[data-character-add]");
    if (add) {
      const slots = root.querySelector(".character-slots");
      if (!slots || slots.children.length >= MAX_CHARACTER_SLOTS) return;
      const slot = characterSlot(null);
      slots.append(slot);
      bindGrowingTextarea(slot.querySelector("[data-character-source]"));
      refreshControls(root);
      return;
    }

    const remove = event.target.closest("[data-character-remove]");
    if (!remove || remove.disabled) return;
    const slots = root.querySelector(".character-slots");
    if (!slots || slots.children.length <= 1) return;
    remove.closest("[data-character-slot]")?.remove();
    refreshControls(root);
  };

  root.onchange = (event) => {
    const input = event.target.closest("[data-character-avatar]");
    if (!input) return;
    const slot = input.closest("[data-character-slot]");
    const file = input.files?.[0];
    if (!slot || !file) {
      if (slot) renderAvatar(slot, slot.dataset.avatarUrl || "");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => renderAvatar(slot, typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => renderAvatar(slot, slot.dataset.avatarUrl || "");
    reader.readAsDataURL(file);
  };
}

export function characterValues(id) {
  const root = $(id);
  if (!root) return [];
  return [...root.querySelectorAll("[data-character-slot]")].map((slot, index) => ({
    id: slot.dataset.characterId || "",
    name: slot.querySelector("[data-character-name]")?.value.trim() || "",
    sourceText: slot.querySelector("[data-character-source]")?.value.trim() || "",
    sortOrder: index,
    avatarUrl: slot.dataset.avatarUrl || "",
    avatarFile: slot.querySelector("[data-character-avatar]")?.files?.[0] || null,
  }));
}

function characterSlot(character) {
  const characterId = character?.id || "";
  const slotKey = characterId || `new_${slotSequence++}`;
  const nameInputId = `characterName_${slotKey}`;
  const sourceInputId = `characterSource_${slotKey}`;
  const avatarInputId = `characterAvatar_${slotKey}`;
  const avatarUrl = characterAvatarUrl(character);
  const preview = el("label", {
    className: "avatar-preview avatar-upload-target",
    attrs: { for: avatarInputId },
  });
  preview.dataset.previewUrl = avatarUrl;
  if (avatarUrl) preview.append(el("img", { attrs: { src: avatarUrl, alt: "" } }));
  else preview.textContent = "+";

  return el("div", {
    className: "character-slot",
    dataset: { characterSlot: "true", characterId, avatarUrl },
  }, [
    el("div", { className: "character-slot-head" }, [
      el("button", {
        className: "character-remove-btn",
        type: "button",
        text: "×",
        dataset: { characterRemove: "true" },
        attrs: { "aria-label": "캐릭터 제거" },
      }),
    ]),
    el("div", { className: "avatar-field" }, [
      preview,
      el("input", {
        className: "file-input",
        type: "file",
        dataset: { characterAvatar: "true" },
        attrs: { id: avatarInputId, accept: "image/png,image/jpeg,image/webp,image/gif" },
      }),
    ]),
    field(nameInputId, "캐릭터 명", el("input", {
      value: characterName(character),
      attrs: { autocomplete: "off", maxlength: "40", placeholder: "" },
      dataset: { characterName: "true" },
    })),
    field(sourceInputId, "캐릭터 설명", el("textarea", {
      text: character?.source_text || "",
      attrs: { rows: "8", placeholder: "" },
      dataset: { characterSource: "true" },
    })),
  ]);
}

function field(inputId, label, control) {
  control.id = inputId;
  return el("div", { className: "field" }, [
    el("label", { text: label, attrs: { for: inputId } }),
    control,
  ]);
}

function refreshControls(root) {
  const slots = [...root.querySelectorAll("[data-character-slot]")];
  slots.forEach((slot) => {
    const remove = slot.querySelector("[data-character-remove]");
    if (remove) remove.disabled = slots.length <= 1;
  });
  const add = root.querySelector("[data-character-add]");
  if (add) add.disabled = slots.length >= MAX_CHARACTER_SLOTS;
}

function renderAvatar(slot, value) {
  const preview = slot.querySelector(".avatar-preview");
  if (!preview) return;
  const src = safeImageUrl(value);
  preview.dataset.previewUrl = src;
  preview.replaceChildren();
  if (src) preview.append(el("img", { attrs: { src, alt: "" } }));
  else preview.textContent = "+";
}

function characterName(character) {
  const profile = parseJson(character?.profile_json);
  return profile.displayName || profile.display_name || character?.name || profile.name || "";
}

function characterAvatarUrl(character) {
  return safeImageUrl(parseJson(character?.profile_json).avatarUrl);
}

function safeImageUrl(value) {
  if (typeof value !== "string" || !value) return "";
  if (value.startsWith("data:image/")) return value;
  try {
    const url = new URL(value, apiBase());
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}
