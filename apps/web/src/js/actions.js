import { notify, state } from "./state.js";

export function conversationsLoaded(items, append) {
  if (!append) {
    state.conversations.byId = new Map();
    state.conversations.order = [];
  }
  for (const item of items) upsertConversation(normalizeConversation(item));
  notify("conversations");
}

export function conversationActivated(item, fromList) {
  const conv = typeof item === "string" ? state.conversations.byId.get(item) : normalizeConversation(item);
  if (!conv?.id) return null;
  const changed = state.activeConversationId !== conv.id;
  upsertConversation(conv);
  state.activeConversationId = conv.id;
  state.ui.chatFromList = Boolean(fromList);
  if (changed) state.activeMessages = { list: [], nextCursor: null, hasMore: false };
  notify("conversations", "activeConversation", ...(changed ? ["activeMessages"] : []));
  return conv;
}

export function conversationDeleted(conversationId) {
  state.conversations.byId.delete(conversationId);
  state.conversations.order = state.conversations.order.filter((id) => id !== conversationId);
  if (state.activeConversationId === conversationId) {
    state.activeConversationId = null;
    state.activeMessages = { list: [], nextCursor: null, hasMore: false };
    notify("conversations", "activeConversation", "activeMessages");
    return;
  }
  notify("conversations");
}

export function conversationTitleChanged(conversationId, title) {
  const conv = state.conversations.byId.get(conversationId);
  if (conv) state.conversations.byId.set(conversationId, { ...conv, title });
  notify("conversations", ...(state.activeConversationId === conversationId ? ["activeConversation"] : []));
}

export function conversationProfileChanged(conversationId, userProfileId) {
  const nextId = userProfileId || null;
  const conv = state.conversations.byId.get(conversationId);
  if (conv) state.conversations.byId.set(conversationId, { ...conv, userProfileId: nextId });
  if (state.activeConversationId === conversationId) {
    state.selectedUserProfileId = nextId;
  }
  notify("conversations", ...(state.activeConversationId === conversationId ? ["activeConversation"] : []));
}

export function messagesLoaded(page, prepend = false) {
  const messages = page.messages || [];
  state.activeMessages = {
    list: prepend ? [...messages, ...state.activeMessages.list] : messages,
    nextCursor: page.nextCursor || null,
    hasMore: Boolean(page.hasMore),
  };
  notify("activeMessages");
}

export function userProfileUpdated(user) {
  state.catalog.users.byId.set(user.id, user);
  if (!state.catalog.users.order.includes(user.id)) state.catalog.users.order.push(user.id);
  notify("catalog.users");
}

export function userProfileDeleted(userProfileId) {
  state.catalog.users.byId.delete(userProfileId);
  state.catalog.users.order = state.catalog.users.order.filter((id) => id !== userProfileId);
  let changed = false;
  for (const [id, conv] of state.conversations.byId) {
    if (conv.userProfileId !== userProfileId) continue;
    state.conversations.byId.set(id, { ...conv, userProfileId: null });
    changed = true;
  }
  const active = activeConversation();
  if (active?.userProfileId === userProfileId) {
    conversationProfileChanged(active.id, null);
    return;
  }
  notify("catalog.users", ...(changed ? ["conversations"] : []));
}

export function activeConversation() {
  return state.conversations.byId.get(state.activeConversationId) || null;
}

export function normalizeConversation(item) {
  return {
    id: item.id || item.conversationId,
    plotId: item.plotId ?? item.plot_id,
    userProfileId: item.userProfileId ?? item.user_profile_id ?? null,
    title: item.title || "",
    activeAdapterId: item.activeAdapterId ?? item.active_adapter_id ?? "",
    createdAt: item.createdAt ?? item.created_at ?? "",
    updatedAt: item.updatedAt ?? item.updated_at ?? "",
  };
}

function upsertConversation(conv) {
  if (!conv.id) return;
  state.conversations.byId.set(conv.id, conv);
  if (!state.conversations.order.includes(conv.id)) state.conversations.order.push(conv.id);
}
