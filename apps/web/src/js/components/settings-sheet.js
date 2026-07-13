import { el } from "../dom.js";

export function settingsSheet() {
  return el("div", { id: "settingsSheet", className: "sheet", attrs: { role: "dialog", "aria-modal": "true" } }, [
    el("form", { id: "settingsForm", className: "panel" }, [
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
            ["local-stub", "로컬 테스트"],
            ["ollama", "Ollama"],
            ["openai", "OpenAI"],
            ["anthropic", "Anthropic"],
            ["gemini", "Gemini"],
          ])),
          field("modelSelectButton", "모델", select("modelSelect", [])),
        ]),
        el("div", { className: "row" }, [
          field("numPredictInput", "답변 길이", el("input", {
            id: "numPredictInput",
            type: "number",
            attrs: { min: "64", max: "8192", step: "1" },
          })),
          field("numCtxInput", "맥락 길이", el("input", {
            id: "numCtxInput",
            type: "number",
            attrs: { min: "512", max: "32768", step: "1" },
          })),
        ]),
        field("adapterInput", "어댑터", el("input", { id: "adapterInput", attrs: { placeholder: "" } })),
        el("label", { className: "row row-start" }, [
          el("input", { id: "compactPromptInput", className: "checkbox", type: "checkbox" }),
          el("span", { text: "프롬프트 압축" }),
        ]),
      ]),
      el("button", { id: "settingsSaveBtn", className: "primary", type: "submit", text: "저장" }),
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
    }),
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
