import { apiBase, api } from "./api.js";
import { activeConversation } from "./actions.js";
import { keys, modelOptions } from "./config.js";
import { $, closeDropdowns, confirmDialog, el, setChildren, toast, toggleDropdown } from "./dom.js";
import { providerErrorMessage } from "./provider-errors.js";
import { state } from "./state.js";

const DEFAULT_NUM_PREDICT = 1500;
const DEFAULT_NUM_CTX = 8192;
const providerGenerationDefaults = {
  "local-stub": { numPredict: DEFAULT_NUM_PREDICT, numCtx: DEFAULT_NUM_CTX },
  ollama: { numPredict: 1500, numCtx: 8192 },
  "openai-codex": { numPredict: 4096, numCtx: 65536 },
  "claude-cli": { numPredict: 8192, numCtx: 65536 },
  gemini: { numPredict: 8192, numCtx: 65536 },
};
const defaultGenerationSettings = {
  provider: "ollama",
  model: "",
  numPredict: DEFAULT_NUM_PREDICT,
  numCtx: DEFAULT_NUM_CTX,
  compactPrompt: true,
  adapterId: "",
};
const loadedModelOptions = new Map();
const pendingProviderLogins = new Map();
let providerLoginPoll = null;
let activeProviderSettings = null;
let providerViewVersion = 0;
let settingsSnapshot = null;
let modelLoadVersion = 0;
let conversationSettingsVersion = 0;
const renderedProviderConnections = new Map();
const renderedProviderStatuses = new Map();
const labels = {
  themeSelect: { system: "시스템", light: "밝게", dark: "어둡게" },
  providerSelect: { "local-stub": "로컬 테스트", ollama: "Ollama", "openai-codex": "Codex", "claude-cli": "Claude Code", gemini: "Gemini" },
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
  const defaults = generationDefaults(state.settings.provider);
  return {
    provider: state.settings.provider,
    model: providerModel(),
    adapterId: state.settings.adapterId || null,
    numPredict: Number(state.settings.numPredict) || defaults.numPredict,
    numCtx: Number(state.settings.numCtx) || defaults.numCtx,
    compactPrompt: Boolean(state.settings.compactPrompt),
    ...extra,
  };
}

export async function loadConversationSettings() {
  const loadVersion = ++conversationSettingsVersion;
  resetGenerationSettings();
  const conv = activeConversation();
  if (!conv) {
    syncSettingsForm();
    return;
  }
  try {
    const settings = await api(`/api/conversations/${conv.id}/settings`);
    if (loadVersion !== conversationSettingsVersion || activeConversation()?.id !== conv.id) return;
    if (!settings) {
      await selectDefaultModel();
      if (loadVersion !== conversationSettingsVersion || activeConversation()?.id !== conv.id) return;
      syncSettingsForm();
      return;
    }
    state.settings.provider = settings.provider || state.settings.provider;
    state.settings.model = settings.model || state.settings.model;
    const defaults = generationDefaults(state.settings.provider);
    state.settings.numPredict = settings.num_predict || defaults.numPredict;
    state.settings.numCtx = settings.num_ctx || defaults.numCtx;
    state.settings.compactPrompt = settings.compact_prompt ?? state.settings.compactPrompt;
    state.settings.adapterId = settings.adapter_id || "";
    await selectDefaultModel();
    if (loadVersion !== conversationSettingsVersion || activeConversation()?.id !== conv.id) return;
    syncSettingsForm();
  } catch {
    if (loadVersion !== conversationSettingsVersion || activeConversation()?.id !== conv.id) return;
    syncSettingsForm();
  }
}

export async function saveConversationSettings() {
  const conv = activeConversation();
  if (!conv) return;
  await api(`/api/conversations/${conv.id}/settings`, {
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

function generationDefaults(provider) {
  return providerGenerationDefaults[provider] || providerGenerationDefaults.ollama;
}

async function selectDefaultModel() {
  if (state.settings.model) return;
  const models = await providerModels(state.settings.provider);
  if (models.length) state.settings.model = models[0];
}

function renderModelOptions(models = fallbackModels(state.settings.provider), preferFirst = false) {
  const selected = normalizedModelId(state.settings.provider, state.settings.model);
  state.settings.model = selected;
  const options = models.length ? models : (selected ? [selected] : []);
  setChildren($("modelSelectMenu"), options.map((model) => selectOption(
    "modelSelect",
    model,
    modelOptionLabel(state.settings.provider, model),
  )));
  if (models.length && preferFirst) state.settings.model = models[0];
  else if (models.length && !models.includes(selected)) {
    state.settings.model = models[0];
  }
  setSelectValue("modelSelect", state.settings.model, modelOptionLabel(state.settings.provider, state.settings.model));
  $("modelSelectButton").disabled = !options.length;
}

function modelOptionLabel(provider, model) {
  if (!model) return null;
  return normalizedModelId(provider, model);
}

function normalizedModelId(provider, model) {
  if (provider !== "claude-cli") return model || "";
  return {
    sonnet: "claude-sonnet-4-6",
    opus: "claude-opus-4-8",
    haiku: "claude-haiku-4-5-20251001",
  }[model] || model || "";
}

async function refreshModelOptions(preferFirst = false) {
  const loadVersion = ++modelLoadVersion;
  const provider = state.settings.provider;
  const models = await providerModels(provider);
  if (loadVersion !== modelLoadVersion || provider !== state.settings.provider || !$("settingsSheet").classList.contains("open")) return;
  renderModelOptions(models, preferFirst);
}

async function providerModels(provider) {
  if (loadedModelOptions.has(provider)) return loadedModelOptions.get(provider);
  try {
    const models = normalizeModels(await api(`/api/models?provider=${encodeURIComponent(provider)}`), fallbackModels(provider), provider);
    loadedModelOptions.set(provider, models);
    return models;
  } catch {
    if (provider === state.settings.provider && $("settingsSheet").classList.contains("open")) toast(`${providerLabel(provider)} 모델 목록을 불러오지 못했습니다.`);
  }
  return fallbackModels(provider);
}

function normalizeModels(data, fallback, provider) {
  const raw = Array.isArray(data) ? data : data?.models;
  const models = (Array.isArray(raw) ? raw : [])
    .map((item) => typeof item === "string" ? item : item?.id || item?.name || item?.model)
    .map((model) => normalizedModelId(provider, model))
    .filter(Boolean);
  return models.length ? [...new Set(models)] : fallback;
}

export function bindSettings() {
  window.addEventListener("message", handleProviderAuthMessage);
  $("settingsBtn").onclick = () => openSettingsSheet();
  $("chatSettingsBtn").onclick = () => openSettingsSheet();
  $("closeSettingsBtn").onclick = closeSettingsSheet;
  $("closeProviderSettingsBtn").onclick = closeProviderSettings;
  $("providerSettingsSheet").onclick = (event) => {
    if (event.target === $("providerSettingsSheet")) closeProviderSettings();
  };
  $("openProviderConnectionsBtn").onclick = () => openProviderConnections();
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
      closeSettingsSheet();
      return;
    }
    if (!event.target.closest(".dropdown")) closeDropdowns();
  };
  $("settingsForm").onsubmit = async (event) => {
    event.preventDefault();
    const inChat = canEditConversationSettings();
    const apiAddress = $("apiBaseInput").value.trim();
    if (apiAddress) localStorage.setItem(keys.apiBase, apiAddress);
    else localStorage.removeItem(keys.apiBase);
    if (inChat) {
      state.settings.provider = $("providerSelect").value;
      state.settings.model = $("modelSelect").value;
      const defaults = generationDefaults(state.settings.provider);
      state.settings.numPredict = Number($("numPredictInput").value) || defaults.numPredict;
      state.settings.numCtx = Number($("numCtxInput").value) || defaults.numCtx;
      state.settings.adapterId = $("adapterInput").value.trim();
      state.settings.compactPrompt = $("compactPromptInput").checked;
      if (!state.settings.model) {
        toast("사용할 모델을 먼저 선택하세요.");
        return;
      }
      try {
        await saveConversationSettings();
      } catch (err) {
        toast(`대화 설정 저장 실패: ${err.message}`);
        return;
      }
    }
    settingsSnapshot = null;
    modelLoadVersion += 1;
    $("settingsSheet").classList.remove("open");
    toast(inChat ? "대화 설정 저장 완료" : "UI 설정 저장 완료");
  };
}

function openSettingsSheet() {
  closeDropdowns();
  settingsSnapshot = { ...state.settings };
  syncSettingsForm();
  const inChat = canEditConversationSettings();
  $("settingsTitle").textContent = inChat ? "대화 설정" : "UI 설정";
  setModelSettingsVisible(inChat);
  $("settingsSaveBtn").textContent = inChat ? "대화 설정 저장" : "저장";
  $("settingsSheet").classList.add("open");
  if (inChat) refreshModelOptions();
}

function closeSettingsSheet() {
  closeDropdowns();
  modelLoadVersion += 1;
  if (settingsSnapshot) Object.assign(state.settings, settingsSnapshot);
  settingsSnapshot = null;
  $("settingsSheet").classList.remove("open");
}

function setModelSettingsVisible(visible) {
  $("modelSettingsSection").hidden = !visible;
  $("modelSettingsSection").classList.toggle("is-hidden", !visible);
  if (!visible) closeDropdowns("#providerSelectMenu.open, #modelSelectMenu.open");
}

async function openProviderConnections() {
  const viewVersion = ++providerViewVersion;
  activeProviderSettings = null;
  clearTimeout(providerLoginPoll);
  $("providerSettingsTitle").textContent = "AI 제공자 연결";
  $("providerSettingsSheet").classList.add("open");
  const root = $("providerSettingsContent");
  root.classList.add("provider-connection-list");
  setChildren(root, [el("span", { className: "meta", text: "연결 상태를 확인하는 중…" })]);
  try {
    const data = await api("/api/provider-connections");
    if (viewVersion !== providerViewVersion || activeProviderSettings !== null || !$("providerSettingsSheet").classList.contains("open")) return;
    const providers = (Array.isArray(data?.providers) ? data.providers : [])
      .filter((connection) => !["openai", "anthropic", "gemini"].includes(connection.provider));
    setChildren(root, providers.map(providerConnectionRow));
  } catch {
    if (viewVersion !== providerViewVersion || activeProviderSettings !== null || !$("providerSettingsSheet").classList.contains("open")) return;
    setChildren(root, [el("span", { className: "meta", text: "연결 상태를 확인할 수 없습니다." })]);
  }
}

function providerConnectionRow(connection) {
  const button = el("button", { type: "button", className: "provider-connection" }, [
    el("span", { className: "provider-connection-copy" }, [
      el("strong", { text: providerLabel(connection.provider) }),
      el("span", { className: "meta", text: providerActionText(connection) }),
    ]),
    el("span", { className: `connection-status${connection.status === "connected" ? " connected" : connection.status === "error" ? " error" : ""}`, text: connectionStatus(connection.status) }),
    el("span", { className: "provider-connection-chevron", text: "›", attrs: { "aria-hidden": "true" } }),
  ]);
  button.onclick = () => {
    if (connection.provider === "openai-codex" && connection.status === "disconnected") {
      startCodexAuthorization();
      return;
    }
    openProviderSettings(connection.provider);
  };
  return button;
}

function providerLabel(provider) {
  return {
    "openai-codex": "Codex", "claude-cli": "Claude Code", gemini: "Gemini API", ollama: "Ollama",
  }[provider] || provider;
}

function connectionStatus(status) {
  return { connected: "연결됨", disconnected: "연결 필요", login_pending: "로그인 진행 중", error: "연결 오류" }[status] || status;
}

function providerActionText(connection) {
  if (connection.status === "connected") return "설정 열기";
  if (connection.actionRequired === "api_key_required") return "환경변수 API 키 필요";
  if (connection.actionRequired === "provider_timeout") return "연결 확인 시간이 초과되었습니다";
  if (connection.actionRequired === "provider_runtime_incompatible") return "공식 런타임 버전을 확인하세요";
  if (connection.actionRequired === "provider_runtime_crashed") return "공식 런타임이 비정상 종료되었습니다";
  if (connection.actionRequired === "provider_bad_gateway") return "provider 연결을 확인할 수 없습니다";
  if (connection.actionRequired === "runtime_setup_required") return "공식 런타임 설정 필요";
  if (connection.provider === "openai-codex") return connection.status === "login_pending" ? "Codex 로그인 완료 대기 중" : "Codex 로그인";
  if (connection.provider === "claude-cli") return connection.status === "login_pending" ? "Claude 로그인 완료 대기 중" : "Claude 로그인";
  return "설정 열기";
}

async function openProviderSettings(provider) {
  const viewVersion = ++providerViewVersion;
  activeProviderSettings = provider;
  $("providerSettingsTitle").textContent = `${providerLabel(provider)} 설정`;
  $("providerSettingsSheet").classList.add("open");
  const root = $("providerSettingsContent");
  root.classList.remove("provider-connection-list");
  setChildren(root, [el("span", { className: "meta", text: "연결 상태를 확인하는 중…" })]);
  try {
    const connection = await api(`/api/provider-connections/${encodeURIComponent(provider)}`);
    if (!isCurrentProviderView(provider, viewVersion)) return;
    renderProviderSettings(connection);
  } catch (err) {
    if (!isCurrentProviderView(provider, viewVersion)) return;
    setChildren(root, [el("span", { className: "meta", text: "설정을 불러오지 못했습니다." })]);
    toast(`설정 조회 실패: ${providerFailureMessage(err)}`);
  }
}

function renderProviderSettings(connection) {
  if (activeProviderSettings !== connection.provider || !$("providerSettingsSheet").classList.contains("open")) return;
  renderedProviderConnections.set(connection.provider, providerConnectionSignature(connection));
  renderedProviderStatuses.set(connection.provider, connection.status);
  const root = $("providerSettingsContent");
  const children = [];
  if (connection.runtimeVersion) children.push(el("span", { className: "meta", text: `런타임: ${runtimeLabel(connection.runtimeVersion)}` }));
  if (connection.accountLabel) children.push(el("span", { className: "meta", text: `계정: ${connection.accountLabel}` }));
  if (connection.plan) children.push(el("span", { className: "meta", text: `플랜: ${connection.plan}` }));
  if (connection.status === "error") children.push(el("span", { className: "connection-status error", text: providerActionText(connection) }));
  if (connection.provider === "openai-codex") {
    const connected = connection.status === "connected";
    const pending = { ...pendingProviderLogins.get(connection.provider), verificationUrl: connection.verificationUrl || pendingProviderLogins.get(connection.provider)?.verificationUrl, userCode: connection.userCode || pendingProviderLogins.get(connection.provider)?.userCode };
    const button = el("button", {
      type: "button",
      className: connected ? "danger" : "primary",
      text: connected ? "로그아웃" : connection.status === "login_pending" && pending.verificationUrl ? "Codex 인증 페이지 열기" : "Codex 로그인",
    });
    button.onclick = () => connected ? logoutCodexConnection(button) : startCodexAuthorization();
    children.push(button);
    if (pending && !connected && pending.userCode && pending.verificationUrl) {
      children.push(el("div", { className: "device-code" }, [
        el("strong", { text: `Codex 인증 코드: ${pending.userCode}` }),
        el("a", { text: "인증 페이지 열기", attrs: { href: pending.verificationUrl, target: "_blank", rel: "noopener noreferrer" } }),
        el("span", { className: "meta", text: "인증 페이지에서 위 코드를 입력한 뒤 로그인을 완료하세요." }),
      ]));
    }
    if (connection.status === "login_pending") {
      const cancel = el("button", { type: "button", className: "danger", text: "로그인 취소" });
      cancel.onclick = () => cancelProviderLogin("openai-codex", cancel);
      children.push(cancel);
    }
    if (connection.status === "login_pending") scheduleProviderLoginRefresh("openai-codex");
  } else if (connection.provider === "claude-cli") {
    const connected = connection.status === "connected";
    const pending = {
      ...pendingProviderLogins.get(connection.provider),
      verificationUrl: connection.verificationUrl || pendingProviderLogins.get(connection.provider)?.verificationUrl,
    };
    const loginPending = connection.status === "login_pending";
    const button = el("button", {
      type: "button",
      className: connected ? "danger" : "primary",
      text: connected ? "로그아웃" : loginPending && pending.verificationUrl ? "Claude 인증 페이지 열기" : "Claude 로그인",
    });
    button.onclick = () => {
      if (!connected) {
        startClaudeAuthorization();
        return;
      }
      logoutClaudeConnection(button);
    };
    children.push(button);
    if (connection.status === "login_pending") {
      const codeInput = el("input", {
        type: "password",
        attrs: { autocomplete: "one-time-code", placeholder: "Claude 인증 페이지의 코드를 붙여넣기" },
      });
      const submitCode = el("button", { type: "button", text: "인증 코드 제출" });
      submitCode.onclick = () => submitClaudeLoginCode(codeInput, submitCode);
      children.push(el("div", { className: "device-code" }, [
        el("span", { className: "meta", text: "인증 페이지가 표시한 코드를 붙여넣고 제출하세요." }),
        codeInput,
        submitCode,
      ]));
      children.push(el("span", { className: "meta", text: "브라우저 인증 완료를 확인하는 중입니다…" }));
      const cancel = el("button", { type: "button", className: "danger", text: "로그인 취소" });
      cancel.onclick = () => cancelProviderLogin("claude-cli", cancel);
      children.push(cancel);
      scheduleProviderLoginRefresh("claude-cli");
    } else if (!connected) children.push(el("span", { className: "meta", text: "로그인 창 또는 인증 URL에서 Claude Code 계정으로 인증하세요." }));
  } else if (connection.actionRequired === "api_key_required") {
    children.push(el("span", { className: "meta", text: "이 앱은 API 키를 저장하지 않습니다. Docker 환경변수에 API 키를 설정한 뒤 다시 확인하세요." }));
  } else if (connection.provider !== "ollama") {
    children.push(el("span", { className: "meta", text: providerActionText(connection) }));
  }
  if (connection.provider !== "local-stub") {
    const test = el("button", { type: "button", text: "연결 테스트" });
    test.onclick = () => testProviderConnection(connection.provider, test);
    children.push(test);
  }
  setChildren(root, children);
}

function runtimeLabel(version) {
  return version
    .replace(/^codex-cli\s+/i, "Codex CLI ")
    .replace(/^claude code\s*/i, "Claude CLI ");
}

function scheduleProviderLoginRefresh(provider) {
  clearTimeout(providerLoginPoll);
  const viewVersion = providerViewVersion;
  providerLoginPoll = setTimeout(async () => {
    if (!isCurrentProviderView(provider, viewVersion)) return;
    try {
      const connection = await api(`/api/provider-connections/${encodeURIComponent(provider)}`);
      if (!isCurrentProviderView(provider, viewVersion)) return;
      if (renderedProviderConnections.get(provider) === providerConnectionSignature(connection)) {
        if (connection.status === "login_pending") scheduleProviderLoginRefresh(provider);
        return;
      }
      renderProviderSettings(connection);
    } catch {
      if (isCurrentProviderView(provider, viewVersion) && renderedProviderStatuses.get(provider) === "login_pending") scheduleProviderLoginRefresh(provider);
    }
  }, 2000);
}

function closeProviderSettings() {
  providerViewVersion += 1;
  activeProviderSettings = null;
  clearTimeout(providerLoginPoll);
  $("providerSettingsSheet").classList.remove("open");
}

function isCurrentProviderView(provider, viewVersion) {
  return viewVersion === providerViewVersion
    && activeProviderSettings === provider
    && $("providerSettingsSheet").classList.contains("open");
}

function providerConnectionSignature(connection) {
  return JSON.stringify([
    connection.status, connection.actionRequired, connection.runtimeVersion, connection.resolvedAuthMode,
    connection.accountLabel, connection.plan, connection.verificationUrl, connection.userCode,
  ]);
}

async function testProviderConnection(provider, button) {
  button.disabled = true;
  toast("연결을 확인하는 중…");
  try {
    const result = await api(`/api/provider-connections/${encodeURIComponent(provider)}/test`, { method: "POST" });
    toast(result.ok ? "연결 성공" : `연결 확인 실패: ${providerTestMessage(result.code)}`);
  } catch (err) {
    toast(`연결 확인 실패: ${providerFailureMessage(err)}`);
  } finally {
    button.disabled = false;
  }
}

function providerTestMessage(code) {
  return providerErrorMessage(code);
}

function providerFailureMessage(error) {
  return providerErrorMessage(error);
}

async function logoutCodexConnection(button = null) {
  if (button) button.disabled = true;
  try {
    if (!(await confirmDialog("Codex 연결을 해제할까요?", { danger: true }))) return;
    await api("/api/provider-connections/openai-codex", { method: "DELETE" });
    pendingProviderLogins.delete("openai-codex");
    await openProviderSettings("openai-codex");
  } catch (err) {
    toast(`Codex 연결 실패: ${providerFailureMessage(err)}`);
  } finally {
    if (button?.isConnected) button.disabled = false;
  }
}

async function logoutClaudeConnection(button = null) {
  if (button) button.disabled = true;
  try {
    if (!(await confirmDialog("Claude Code 연결을 해제할까요?", { danger: true }))) return;
    await api("/api/provider-connections/claude-cli", { method: "DELETE" });
    pendingProviderLogins.delete("claude-cli");
    await openProviderSettings("claude-cli");
  } catch (err) {
    toast(`Claude 연결 실패: ${providerFailureMessage(err)}`);
  } finally {
    if (button?.isConnected) button.disabled = false;
  }
}

async function cancelProviderLogin(provider, button = null) {
  if (button) button.disabled = true;
  try {
    if (!(await confirmDialog("진행 중인 로그인을 취소할까요?", { danger: true }))) return;
    await api(`/api/provider-connections/${encodeURIComponent(provider)}`, { method: "DELETE" });
    pendingProviderLogins.delete(provider);
    toast("로그인을 취소했습니다.");
    await openProviderSettings(provider);
  } catch (err) {
    toast(`로그인 취소 실패: ${err.message}`);
  } finally {
    if (button?.isConnected) button.disabled = false;
  }
}

function startClaudeAuthorization() {
  const target = window.open("/claude-auth.html?v=20260724-1", "claude-authorization");
  if (!target) {
    toast("브라우저에서 로그인 팝업을 허용하세요.");
    return;
  }
}

function startCodexAuthorization() {
  const target = window.open("/codex-auth.html?v=20260724-1", "codex-authorization");
  if (!target) toast("브라우저에서 로그인 팝업을 허용하세요.");
}

function handleProviderAuthMessage(event) {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
  if (event.data.type === "pinballchat:claude-login-error" || event.data.type === "pinballchat:codex-login-error") {
    toast(event.data.message || "로그인을 시작하지 못했습니다.");
    return;
  }
  const provider = {
    "pinballchat:claude-login-started": "claude-cli",
    "pinballchat:codex-login-started": "openai-codex",
  }[event.data.type];
  if (!provider) return;
  if (event.data.connection) pendingProviderLogins.set(provider, event.data.connection);
  if ($("providerSettingsSheet").classList.contains("open") && (activeProviderSettings === provider || activeProviderSettings === null)) {
    openProviderSettings(provider);
  }
}

async function submitClaudeLoginCode(input, button) {
  const code = input.value.trim();
  if (!code) {
    toast("인증 코드를 붙여넣으세요.");
    return;
  }
  button.disabled = true;
  try {
    await api("/api/provider-connections/claude-cli/login/code", {
      method: "POST",
      body: JSON.stringify({ code }),
    });
    input.value = "";
    toast("인증 코드를 전달했습니다.");
    scheduleProviderLoginRefresh("claude-cli");
  } catch (err) {
    toast(`인증 코드 전달 실패: ${err.message}`);
  } finally {
    button.disabled = false;
  }
}

function canEditConversationSettings() {
  return state.route === "chat" && Boolean(activeConversation());
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
    state.settings.model = fallbackModels(value)[0] || "";
    Object.assign(state.settings, generationDefaults(value));
    syncSettingsForm();
    refreshModelOptions(true);
  }
  if (id === "modelSelect") state.settings.model = value;
}

function setSelectValue(id, value, label = null) {
  $(id).value = value || "";
  $(`${id}Button`).querySelector(".select-button-label").textContent = label || labels[id]?.[value] || value || "모델 없음";
}

function selectOption(id, value, label) {
  return el("button", { type: "button", text: label, dataset: { selectOption: id, value, label } });
}

function resetGenerationSettings() {
  Object.assign(state.settings, defaultGenerationSettings);
}
