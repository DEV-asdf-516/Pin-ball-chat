import { el } from "../dom.js";

export function plotCreatePage() {
  return el("section", { id: "plotCreateScreen", className: "screen" }, [
    el("form", { id: "plotCreateForm", className: "detail form-page" }, [
      formTabs("plotCreate", "prompt"),
      el("div", { dataset: { formPanel: "prompt" } }, [
        el("section", { className: "form-card" }, [
          el("h2", { text: "플롯" }),
          field("plotCreateTitle", "제목", el("input", { id: "plotCreateTitle", attrs: { autocomplete: "off", maxlength: "40", placeholder: "" } })),
          field("plotCreateSource", "내용", el("textarea", { id: "plotCreateSource", attrs: { rows: "10", placeholder: "" } })),
          field("plotCreateGenreList", "장르", el("div", { id: "plotCreateGenreList", className: "genre-picker" })),
        ]),
        el("section", { className: "form-card" }, [
          el("h2", { text: "캐릭터" }),
          el("div", { className: "avatar-field" }, [
            el("label", { id: "plotCreateAvatarPreview", className: "avatar-preview avatar-upload-target", text: "+", attrs: { for: "plotCreateCharacterAvatarFile" } }),
            el("input", { id: "plotCreateCharacterAvatarFile", className: "file-input", type: "file", attrs: { accept: "image/*" } }),
          ]),
          field("plotCreateCharacterName", "캐릭터 명", el("input", { id: "plotCreateCharacterName", attrs: { autocomplete: "off", maxlength: "40", placeholder: "" } })),
          field("plotCreateCharacterSource", "캐릭터 설명", el("textarea", { id: "plotCreateCharacterSource", attrs: { rows: "8", placeholder: "" } })),
        ]),
      ]),
      el("div", { dataset: { formPanel: "intro" }, attrs: { hidden: "" } }, [
        el("section", { className: "form-card" }, [
          el("h2", { text: "인트로" }),
          el("div", { id: "plotCreateIntroEditor", className: "intro-editor" }),
        ]),
      ]),
    ]),
    el("div", { className: "bottom" }, [
      el("button", { className: "primary full-width", type: "submit", text: "등록", attrs: { form: "plotCreateForm" } }),
    ]),
  ]);
}

function formTabs(prefix, active) {
  return el("div", { className: "form-tabs" }, [
    tabButton("prompt", "프롬프트", active),
    tabButton("intro", "인트로", active),
  ].map((button) => {
    button.dataset.formTabRoot = prefix;
    return button;
  }));
}

function tabButton(value, label, active) {
  return el("button", {
    type: "button",
    className: value === active ? "active" : "",
    text: label,
    dataset: { formTab: value },
  });
}

function field(inputId, label, control) {
  return el("div", { className: "field" }, [
    el("label", { text: label, attrs: { for: inputId } }),
    control,
  ]);
}
