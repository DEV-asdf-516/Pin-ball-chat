import { apiBase, api } from "./api.js";
import { keys, modelOptions } from "./config.js";
import { $, closeDropdowns, el, setChildren, toast, toggleDropdown } from "./dom.js";
import { state } from "./state.js";

const DEFAULT_NUM_PREDICT = 1500;
const DEFAULT_NUM_CTX = 8192;
const defaultGenerationSettings = {
  provider: "local-stub",
  model: "local-stub",
  numPredict: DEFAULT_NUM_PREDICT,
  numCtx: DEFAULT_NUM_CTX,
  compactPrompt: true,
  adapterId: "",
};
const loadedModelOptions = new Map();
const labels = {
  themeSelect: { system: "시스템", light: "밝게", dark: "어둡게" },
  providerSelect: { "local-stub": "로컬 테스트", ollama: "Ollama", openai: "OpenAI", anthropic: "Anthropic", gemini: "Gemini" },
};

export function applyTheme(theme = localStorage.getItem(keys.theme) || "system") {
  setSelectValue("themeSelect", theme);
  const resolved = theme === "system"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : theme;
  document.documentElement.dataset.theme = resolved;
}

export function loadSettings() {
  localStorage.removeItem(keys.settings);
  resetGenerationSettings();
  syncSettingsForm();
}

export function providerModel() {
  return state.settings.model;
}

export function generationBody(extra = {}) {
  return {
    provider: state.settings.provider,
    model: providerModel(),
    adapterId: state.settings.adapterId || null,
    numPredict: Number(state.settings.numPredict) || DEFAULT_NUM_PREDICT,
    numCtx: Number(state.settings.numCtx) || DEFAULT_NUM_CTX,
    compactPrompt: Boolean(state.settings.compactPrompt),
    ...extra,
  };
}

export async function loadConversationSettings() {
  resetGenerationSettings();
  try {
    const settings = await api(`/api/conversations/${state.conversation.conversationId}/settings`);
    if (!settings) {
      syncSettingsForm();
      return;
    }
    state.settings.provider = settings.provider || state.settings.provider;
    state.settings.model = settings.model || state.settings.model;
    state.settings.numPredict = settings.num_predict || state.settings.numPredict;
    state.settings.numCtx = settings.num_ctx || state.settings.numCtx;
    state.settings.compactPrompt = settings.compact_prompt ?? state.settings.compactPrompt;
    state.settings.adapterId = settings.adapter_id || "";
    syncSettingsForm();
  } catch {
    syncSettingsForm();
  }
}

export async function saveConversationSettings() {
  if (!state.conversation) return;
  await api(`/api/conversations/${state.conversation.conversationId}/settings`, {
    method: "PUT",
    body: JSON.stringify(generationBody()),
  });
}

export function syncSettingsForm() {
  $("apiBaseInput").value = apiBase();
  setSelectValue("providerSelect", state.settings.provider);
  renderModelOptions();
  $("numPredictInput").value = state.settings.numPredict;
  $("numCtxInput").value = state.settings.numCtx;
  $("adapterInput").value = state.settings.adapterId || "";
  $("compactPromptInput").checked = state.settings.compactPrompt;
}

function fallbackModels(provider) {
  return modelOptions[provider] || [];
}

function renderModelOptions(models = fallbackModels(state.settings.provider), preferFirst = false) {
  const selected = state.settings.model || "";
  const options = models.length ? models : (selected ? [selected] : []);
  setChildren($("modelSelectMenu"), options.map((m) => selectOption("modelSelect", m, m)));
  if (models.length && preferFirst) state.settings.model = models[0];
  else if (models.length && !models.includes(selected)) {
    state.settings.model = models[0];
  }
  setSelectValue("modelSelect", state.settings.model);
  $("modelSelectButton").disabled = !options.length;
}

async function refreshModelOptions(preferFirst = false) {
  const provider = state.settings.provider;
  const models = await providerModels(provider);
  if (provider !== state.settings.provider) return;
  renderModelOptions(models, preferFirst);
}

async function providerModels(provider) {
  if (loadedModelOptions.has(provider)) return loadedModelOptions.get(provider);
  try {
    const models = normalizeModels(await api(`/api/models?provider=${encodeURIComponent(provider)}`), fallbackModels(provider));
    loadedModelOptions.set(provider, models);
    return models;
  } catch {}
  return fallbackModels(provider);
}

function normalizeModels(data, fallback) {
  const raw = Array.isArray(data) ? data : data?.models;
  const models = (Array.isArray(raw) ? raw : [])
    .map((item) => typeof item === "string" ? item : item?.id || item?.name || item?.model)
    .filter(Boolean);
  return models.length ? models : fallback;
}

export function bindSettings() {
  $("settingsBtn").onclick = () => openSettingsSheet();
  $("chatSettingsBtn").onclick = () => openSettingsSheet();
  $("closeSettingsBtn").onclick = () => $("settingsSheet").classList.remove("open");
  $("settingsSheet").onclick = (event) => {
    const toggle = event.target.closest("[data-select-toggle]");
    if (toggle) {
      event.preventDefault();
      toggleDropdown($(`${toggle.dataset.selectToggle}Menu`), toggle);
      return;
    }
    const option = event.target.closest("[data-select-option]");
    if (option) {
      event.preventDefault();
      handleSelectOption(option);
      return;
    }
    if (event.target === $("settingsSheet")) {
      closeDropdowns();
      $("settingsSheet").classList.remove("open");
      return;
    }
    if (!event.target.closest(".dropdown")) closeDropdowns();
  };
  $("settingsForm").onsubmit = async (event) => {
    event.preventDefault();
    const inChat = canEditConversationSettings();
    localStorage.setItem(keys.apiBase, $("apiBaseInput").value.trim() || "http://localhost:8080");
    if (inChat) {
      state.settings.provider = $("providerSelect").value;
      state.settings.model = $("modelSelect").value;
      state.settings.numPredict = Number($("numPredictInput").value) || DEFAULT_NUM_PREDICT;
      state.settings.numCtx = Number($("numCtxInput").value) || DEFAULT_NUM_CTX;
      state.settings.adapterId = $("adapterInput").value.trim();
      state.settings.compactPrompt = $("compactPromptInput").checked;
      try {
        await saveConversationSettings();
      } catch {}
    }
    $("settingsSheet").classList.remove("open");
    toast(inChat ? "대화 설정 저장 완료" : "UI 설정 저장 완료");
  };
}

function openSettingsSheet() {
  closeDropdowns();
  syncSettingsForm();
  const inChat = canEditConversationSettings();
  $("settingsTitle").textContent = inChat ? "대화 설정" : "UI 설정";
  setModelSettingsVisible(inChat);
  $("settingsSaveBtn").textContent = inChat ? "대화 설정 저장" : "저장";
  $("settingsSheet").classList.add("open");
  if (inChat) refreshModelOptions();
}

function setModelSettingsVisible(visible) {
  $("modelSettingsSection").hidden = !visible;
  $("modelSettingsSection").classList.toggle("is-hidden", !visible);
  if (!visible) closeDropdowns("#providerSelectMenu.open, #modelSelectMenu.open");
}

function canEditConversationSettings() {
  return state.route === "chat" && Boolean(state.conversation?.conversationId);
}

function handleSelectOption(option) {
  const id = option.dataset.selectOption;
  const value = option.dataset.value || "";
  setSelectValue(id, value, option.dataset.label || value);
  closeDropdowns();
  if (id === "themeSelect") {
    localStorage.setItem(keys.theme, value);
    applyTheme(value);
  }
  if (id === "providerSelect") {
    state.settings.provider = value;
    state.settings.model = fallbackModels(value)[0] || state.settings.model;
    syncSettingsForm();
    refreshModelOptions(true);
  }
  if (id === "modelSelect") state.settings.model = value;
}

function setSelectValue(id, value, label = null) {
  $(id).value = value || "";
  $(`${id}Button`).textContent = label || labels[id]?.[value] || value || "모델 없음";
}

function selectOption(id, value, label) {
  return el("button", { type: "button", text: label, dataset: { selectOption: id, value, label } });
}

function resetGenerationSettings() {
  Object.assign(state.settings, defaultGenerationSettings);
}
