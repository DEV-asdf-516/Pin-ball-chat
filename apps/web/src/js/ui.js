import { appShell } from "./components/layout.js";
import { activeConversation } from "./actions.js";
import { keys } from "./config.js";
import { $, closeDropdowns, setChildren } from "./dom.js";
import { state } from "./state.js";

export function mountApp() {
  setChildren($("app"), appShell());
}

export function setHeader(title, sub, back = false) {
  $("headerTitle").textContent = title;
  $("headerSub").textContent = sub || "";
  $("backBtn").style.visibility = back ? "visible" : "hidden";
}

export function setChatHeader(title, sub) {
  $("chatHeaderTitle").textContent = title;
  $("chatHeaderSub").textContent = sub || "";
}

export function showScreen(name) {
  state.route = name;
  closeDropdowns();
  $("settingsSheet")?.classList.remove("open");
  $("userProfileSheet")?.classList.remove("open");
  $("appHeader").hidden = name === "chat";
  for (const el of document.querySelectorAll(".screen")) el.classList.remove("active");
  $(name + "Screen").classList.add("active");
  if (name === "plots") setHeader("Pinballchat", "내 플롯");
  if (name === "plotCreate") setHeader("플롯 제작", "새 플롯", true);
  if (name === "plotManage") setHeader("플롯 관리", "수정 및 삭제", true);
  if (name === "conversations") setHeader("Pinballchat", "대화 내역");
  if (name === "detail") setHeader(state.selectedPlot?.title || "플롯", "", true);
  if (name === "chat") setChatHeader(chatTitle(), state.selectedPlot?.title || "");
  updateSettingsButton(name);
  localStorage.setItem(keys.route, JSON.stringify({
    route: name,
    plotId: state.selectedPlot?.id || null,
    managedPlotId: state.managedPlotId || null,
    conversationId: state.activeConversationId || null,
  }));
}

export function chatTitle() {
  const conv = activeConversation();
  if (conv?.title) return conv.title;
  const plot = state.selectedPlot;
  if (!plot) return "채팅";
  return plot.title || "채팅";
}

function updateSettingsButton(route) {
  $("settingsBtn").setAttribute("title", "UI 설정");
  $("settingsBtn").setAttribute("aria-label", "UI 설정");
}
