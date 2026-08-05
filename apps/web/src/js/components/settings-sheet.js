import { el } from "../dom.js";
import { icon } from "./icons.js";

export function settingsSheet() {
  return el("div", { id: "settingsSheet", className: "sheet", attrs: { role: "dialog", "aria-modal": "true" } }, [
    el("form", { id: "settingsForm", className: "panel" }, [
      el("div", { className: "sheet-handle", attrs: { "aria-hidden": "true" } }),
      el("div", { className: "row" }, [
        el("strong", { id: "settingsTitle", text: "설정" }),
        el("button", {
          id: "closeSettingsBtn",
          className: "icon-btn",
          type: "button",
          text: "×",
          attrs: { title: "닫기", "aria-label": "닫기" },
        }),
      ]),
      el("section", { id: "uiSettingsSection", className: "settings-section" }, [
        el("h2", { text: "UI 설정" }),
        field("apiBaseInput", "API 주소", el("input", { id: "apiBaseInput", attrs: { placeholder: "" } })),
        field("themeSelectButton", "테마", select("themeSelect", [
          ["system", "시스템"],
          ["light", "밝게"],
          ["dark", "어둡게"],
        ])),
      ]),
      el("section", { id: "modelSettingsSection", className: "settings-section" }, [
        el("h2", { text: "대화별 모델 설정" }),
        el("div", { className: "row" }, [
          field("providerSelectButton", "AI 제공자", select("providerSelect", [
            ["ollama", "Ollama"],
            ["openai-codex", "Codex"],
            ["claude-cli", "Claude Code"],
            ["openai", "OpenAI API"],
            ["anthropic", "Anthropic API"],
            ["gemini", "Gemini API"],
          ])),
          field("modelSelectButton", "모델", select("modelSelect", [])),
        ]),
        el("div", { className: "row" }, [
          field("numPredictInput", "최대 출력 글자 수", el("input", {
            id: "numPredictInput",
            type: "number",
            attrs: { min: "64", max: "", step: "1" },
          })),
          field("numCtxInput", "최대 컨텍스트", el("input", {
            id: "numCtxInput",
            type: "number",
            attrs: { min: "512", max: "", step: "1" },
          })),
        ]),
        field("adapterInput", "어댑터", el("input", { id: "adapterInput", attrs: { placeholder: "" } })),
        el("label", { className: "row row-start" }, [
          el("input", { id: "compactPromptInput", className: "checkbox", type: "checkbox" }),
          el("span", { text: "프롬프트 압축" }),
        ]),
      ]),
      el("section", { id: "providerConnectionsSection", className: "settings-section" }, [
        el("button", { id: "openProviderConnectionsBtn", className: "provider-connections-link", type: "button" }, [
          el("span", { className: "provider-connections-copy" }, [
            el("strong", { text: "AI 제공자 연결" }),
            el("span", { className: "meta", text: "연결 상태 확인 및 관리" }),
          ]),
          icon("gear"),
        ]),
      ]),
      el("section", { id: "importSettingsSection", className: "settings-section" }, [
        el("button", { id: "openZetaImportBtn", className: "zeta-import-entry", type: "button" }, [
          el("span", { className: "zeta-import-entry-mark", text: "Z" }),
          el("span", { className: "zeta-import-entry-copy" }, [
            el("strong", { text: "제타 대화 불러오기" }),
          ]),
          el("span", { className: "zeta-import-entry-arrow", text: "→", attrs: { "aria-hidden": "true" } }),
        ]),
        el("span", { id: "zetaImportAvailability", className: "meta" }),
      ]),
      el("button", { id: "settingsSaveBtn", className: "primary", type: "submit", text: "저장" }),
    ]),
  ]);
}

export function zetaImportDialog() {
  return el("div", { id: "zetaImportDialog", className: "dialog zeta-import-dialog", attrs: { role: "dialog", "aria-modal": "true" } }, [
    el("div", { id: "zetaImportPanel", className: "dialog-panel zeta-import-panel", dataset: { phase: "idle" } }, [
      el("div", { className: "zeta-import-handle", attrs: { "aria-hidden": "true" } }),
      el("div", { className: "zeta-import-header" }, [
        el("div", { className: "zeta-import-heading" }, [
          el("span", { className: "zeta-import-eyebrow", text: "ZETA IMPORT" }),
          el("strong", { text: "대화 이어 붙이기" }),
        ]),
        el("button", { id: "closeZetaImportBtn", className: "icon-btn", type: "button", text: "×", attrs: { "aria-label": "닫기" } }),
      ]),
      el("input", { id: "zetaImportFiles", type: "file", attrs: { accept: ".json,application/json", multiple: "" } }),
      el("div", { id: "zetaImportStatus", className: "zeta-import-status", attrs: { "aria-live": "polite" } }),
      el("div", { className: "zeta-import-progress-wrap" }, [
        el("progress", { id: "zetaImportProgress", attrs: { max: "1", value: "0" } }),
      ]),
      el("div", { id: "zetaImportPreview", className: "zeta-import-preview" }),
      el("div", { className: "zeta-import-actions" }, [
        el("button", { id: "chooseZetaImportFilesBtn", className: "zeta-import-choose", type: "button", text: "다른 파일 선택" }),
        el("button", { id: "commitZetaImportBtn", className: "primary zeta-import-commit", type: "button", text: "대화 불러오기", attrs: { disabled: "" } }),
      ]),
    ]),
  ]);
}

export function providerSettingsSheet() {
  return el("div", { id: "providerSettingsSheet", className: "dialog", attrs: { role: "dialog", "aria-modal": "true" } }, [
    el("div", { className: "dialog-panel provider-dialog-panel" }, [
      el("div", { className: "row" }, [
        el("strong", { id: "providerSettingsTitle", text: "AI 제공자 설정" }),
        el("button", { id: "closeProviderSettingsBtn", className: "icon-btn", type: "button", text: "×", attrs: { "aria-label": "닫기" } }),
      ]),
      el("div", { id: "providerSettingsContent", className: "provider-settings-content", attrs: { "aria-live": "polite" } }),
    ]),
  ]);
}

function field(inputId, label, control, id = null) {
  return el("div", { id, className: "field" }, [
    el("label", { text: label, attrs: { for: inputId } }),
    control,
  ]);
}

function select(id, values) {
  return el("div", { className: "custom-select" }, [
    el("input", { id, type: "hidden" }),
    el("button", {
      id: `${id}Button`,
      className: "select-button",
      type: "button",
      dataset: { selectToggle: id },
      attrs: { "aria-haspopup": "listbox" },
    }, [
      el("span", { className: "select-button-label" }),
      icon("chevronDown"),
    ]),
    el("div", { id: `${id}Menu`, className: "dropdown select-dropdown" }, selectOptions(id, values)),
  ]);
}

function selectOptions(id, values) {
  return values.map((item) => {
    const value = Array.isArray(item) ? item[0] : item;
    const label = Array.isArray(item) ? item[1] : item;
    return el("button", { type: "button", text: label, dataset: { selectOption: id, value, label } });
  });
}
