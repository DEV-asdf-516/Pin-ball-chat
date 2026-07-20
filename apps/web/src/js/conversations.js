import { api, apiBase } from "./api.js";
import { conversationDeleted, conversationsLoaded, conversationTitleChanged } from "./actions.js";
import { $, el, parseJson, setChildren } from "./dom.js";
import { loadCursorPage } from "./paging.js";
import { state, subscribe } from "./state.js";

let subscriptionsBound = false;

export function bindConversationSubscriptions() {
  if (subscriptionsBound) return;
  subscriptionsBound = true;
  subscribe("conversations", renderConversations);
  subscribe("catalog.users", renderConversations);
  subscribe("catalog.plots", renderConversations);
}

export async function loadConversations(reset = true) {
  $("conversationStatus").textContent = "대화 불러오는 중...";
  try {
    await loadCursorPage(state.conversations.page, {
      path: "/api/conversations",
      itemKey: "conversations",
      reset,
      apply: conversationsLoaded,
    });
    $("conversationStatus").textContent = `${state.conversations.order.length}개 대화${state.conversations.page.hasMore ? " · 더 있음" : ""}`;
  } catch (err) {
    $("conversationStatus").textContent = "대화 목록을 불러오지 못했습니다.";
    setChildren($("conversationList"), [el("div", { className: "empty", text: err.message })]);
  }
}

export async function loadMoreConversations() {
  await loadConversations(false);
}

export function renderConversations() {
  const q = $("conversationSearchInput").value.trim().toLowerCase();
  const conversations = conversationList().filter((conv) => conversationText(conv).includes(q));
  setChildren(
    $("conversationList"),
    conversations.length ? conversations.map(conversationCard) : [el("div", { className: "empty", text: "아직 대화가 없습니다." })],
  );
}

export function findConversation(conversationId) {
  return state.conversations.byId.get(conversationId) || null;
}

export async function deleteConversation(conversationId) {
  const result = await api(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
  conversationDeleted(conversationId);
  return result;
}

export async function updateConversationTitle(conversationId, title) {
  const result = await api(`/api/conversations/${encodeURIComponent(conversationId)}/title`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
  const nextTitle = result?.title || title;
  conversationTitleChanged(conversationId, nextTitle);
  return nextTitle;
}

function conversationText(conv) {
  const plot = state.catalog.plots.byId.get(conv.plotId);
  const user = state.catalog.users.byId.get(conv.userProfileId);
  return [conv.title, conv.id, conv.plotId, conv.userProfileId, plot?.title, userProfileName(user)].filter(Boolean).join(" ").toLowerCase();
}

function conversationCard(conv) {
  const plot = state.catalog.plots.byId.get(conv.plotId);
  const character = state.catalog.chars.byId.get(plot?.character_id);
  const user = state.catalog.users.byId.get(conv.userProfileId);
  const title = conv.title || plot?.title || "제목 없는 대화";
  return el("article", { className: "card conversation-card", dataset: { conversation: conv.id } }, [
    el("div", { className: "card-head" }, [
      el("div", { className: "conversation-title" }, [
        conversationAvatar(character, title),
        el("h2", { text: title, dataset: { conversationTitleMenu: conv.id } }),
      ]),
      el("div", { className: "menu-wrap" }, [
        el("button", {
          type: "button",
          className: "icon-btn menu-btn",
          text: "⋮",
          dataset: { conversationMenu: conv.id },
          attrs: { title: "대화 메뉴", "aria-label": "대화 메뉴" },
        }),
        el("div", { className: "dropdown", dataset: { menuFor: conv.id } }, [
          el("button", { type: "button", text: "제목 변경", dataset: { editConversationTitle: conv.id } }),
          el("button", { type: "button", className: "danger", text: "삭제", dataset: { deleteConversation: conv.id } }),
        ]),
      ]),
    ]),
    el("div", { className: "conversation-meta-list" }, [
      conversationMeta("사용자 프로필", userProfileName(user) || "미선택"),
      conversationMeta("대화 시작일시", formatConversationTime(conv.createdAt)),
    ]),
  ]);
}

function conversationList() {
  return state.conversations.order.map((id) => state.conversations.byId.get(id)).filter(Boolean);
}

function conversationMeta(label, value) {
  return el("div", { className: "conversation-meta-row" }, [
    el("span", { text: label }),
    el("strong", { text: value || "-" }),
  ]);
}

function userProfileName(user) {
  if (!user) return "";
  const profile = parseJson(user.profile_json);
  return profile.displayName || profile.display_name || user.name || profile.name || user.id;
}

function conversationAvatar(character, fallback) {
  const src = safeImageUrl(parseJson(character?.profile_json).avatarUrl);
  if (src) return el("img", { className: "conversation-avatar", attrs: { src, alt: "" } });
  return el("div", { className: "conversation-avatar", text: characterName(character, fallback) });
}

function characterName(character, fallback) {
  const profile = parseJson(character?.profile_json);
  return (profile.displayName || profile.display_name || character?.name || fallback || "?").trim().slice(0, 1) || "?";
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

function formatConversationTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace("T", " ").replace(/Z$/, "");
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
