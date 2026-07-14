import { api, streamSse } from "./api.js";
import { $, closeDropdowns, confirmDialog, el, parseJson, setChildren, toast, toggleDropdown } from "./dom.js";
import { renderMarkdown } from "./markdown.js";
import { generationBody } from "./settings.js";
import { state } from "./state.js";

const NO_USER_PROFILE = "conversation has no user_profile set";

export async function loadMessages(before) {
  const convId = state.conversation.conversationId;
  const query = before ? `?before=${encodeURIComponent(before)}&limit=30` : "?limit=30";
  const page = await api(`/api/conversations/${convId}/messages${query}`);
  state.nextCursor = page.nextCursor;
  state.hasMore = page.hasMore;
  renderMessages(page.messages || []);
}

export function hydrateTurnGenerations(root = $("messages")) {
  root.querySelectorAll(".message-group.assistant[data-turn]").forEach((node) => {
    if (node.dataset.variantsLoaded || !node.dataset.turn) return;
    node.dataset.variantsLoaded = "true";
    loadTurnGenerations(node);
  });
}

export async function sendMessage(message, options = {}) {
  if (state.streaming) return;
  if (needsUserProfileSelection()) {
    openUserProfileSheet();
    return;
  }
  state.pendingUserResend = null;
  state.streaming = true;
  updateComposer();
  const user = options.silentUser ? null : appendUserMessage(message);
  const assistant = appendAssistantStream();
  try {
    await stream("/api/chat/stream", generationBody({ conversationId: state.conversation.conversationId, message }), assistant, user);
  } catch (err) {
    if (isUserProfileError(err)) {
      assistant.remove();
      openUserProfileSheet();
      return;
    }
    renderAssistantError(assistant, "응답 생성에 실패했습니다.\n" + err.message);
  } finally {
    state.streaming = false;
    updateComposer();
  }
}

export function canResendEditedUserMessage() {
  return Boolean(resendCandidate()?.turnId);
}

export async function resendEditedUserMessage() {
  const resend = resendCandidate();
  if (!resend?.turnId || state.streaming) return false;
  state.pendingUserResend = null;
  const assistant = document.querySelector(`#messages .message-group.assistant[data-turn="${CSS.escape(resend.turnId)}"]`);
  await regenerate(resend.turnId, assistant);
  updateComposer();
  return true;
}

function resendCandidate() {
  if (state.pendingUserResend?.turnId) return state.pendingUserResend;
  const last = [...document.querySelectorAll("#messages .message-group")].at(-1);
  if (!last?.classList.contains("user") || !last.dataset.turn) return null;
  return { messageId: last.dataset.message || "", turnId: last.dataset.turn, content: last.dataset.content || "" };
}

export async function regenerate(turnId, targetNode = null) {
  if (needsUserProfileSelection()) {
    openUserProfileSheet();
    return;
  }
  state.streaming = true;
  updateComposer();
  const assistant = targetNode || appendAssistantStream();
  const variants = assistantVariants(assistant);
  if (targetNode) renderAssistantStream(assistant, "", "", turnId, variants);
  try {
    await stream(`/api/turns/${turnId}/regenerate/stream`, generationBody(), assistant, null, variants);
  } catch (err) {
    if (isUserProfileError(err)) {
      if (!targetNode) assistant.remove();
      else renderAssistantVariant(assistant, variants.length - 1);
      openUserProfileSheet();
      return;
    }
    renderAssistantError(assistant, "재생성에 실패했습니다.\n" + err.message);
  } finally {
    state.streaming = false;
    updateComposer();
  }
}

export function editGeneration(genId) {
  state.pendingUserResend = null;
  const currentNode = document.querySelector(`[data-gen="${CSS.escape(genId)}"]`);
  const current = currentNode?.dataset.content || currentNode?.childNodes[0]?.textContent || "";
  startComposerEdit({ kind: "generation", id: genId, content: current });
}

export function editUserMessage(messageId) {
  state.pendingUserResend = null;
  const currentNode = document.querySelector(`[data-message="${CSS.escape(messageId)}"]`);
  const current = currentNode?.dataset.content || currentNode?.childNodes[0]?.textContent || "";
  startComposerEdit({ kind: "user", id: messageId, content: current });
}

export async function saveComposerEdit() {
  const edit = state.composerEdit;
  if (!edit || state.streaming) return false;
  const editedText = $("messageInput").value;
  if (!editedText.trim()) {
    toast("수정할 내용을 입력하세요");
    return true;
  }

  if (edit.kind === "generation") await saveGenerationEdit(edit.id, editedText);
  if (edit.kind === "user") await saveUserMessageEdit(edit.id, editedText);
  clearComposerEdit();
  toast("편집 저장 완료");
  return true;
}

export function cancelComposerEdit() {
  if (!state.composerEdit) return;
  clearComposerEdit();
}

async function saveGenerationEdit(genId, editedText) {
  state.pendingUserResend = null;
  await api(`/api/generations/${genId}/edit`, { method: "POST", body: JSON.stringify({ editedText }) });
  const node = document.querySelector(`[data-gen="${CSS.escape(genId)}"]`);
  if (!node) return;
  node.after(messageNode({
    id: node.dataset.message || "",
    role: "assistant",
    content: editedText,
    generation_id: genId,
    turn_id: node.dataset.turn,
  }));
  node.remove();
}

async function saveUserMessageEdit(messageId, editedText) {
  await api(`/api/messages/${messageId}/edit`, { method: "POST", body: JSON.stringify({ editedText }) });
  const node = document.querySelector(`[data-message="${CSS.escape(messageId)}"]`);
  if (!node) return;
  const turnId = node.dataset.turn || "";
  const nextNode = messageNode({ id: messageId, role: "user", content: editedText, turn_id: turnId });
  node.after(nextNode);
  node.remove();
  markLastUserMessage();
  state.pendingUserResend = nextNode?.classList.contains("last-user-message") && turnId
    ? { messageId, turnId, content: editedText }
    : null;
  updateComposer();
}

function startComposerEdit(edit) {
  if (!edit.id || state.streaming) return;
  state.composerEdit = edit;
  $("messageInput").value = edit.content || "";
  $("messageInput").focus();
  $("messageInput").select();
  $("messageInput").dispatchEvent(new Event("input"));
  updateComposer();
}

function clearComposerEdit() {
  state.composerEdit = null;
  $("messageInput").value = "";
  $("messageInput").dispatchEvent(new Event("input"));
  updateComposer();
}

export async function deleteMessage(messageId) {
  if (!messageId) return;
  const node = document.querySelector(`[data-message="${CSS.escape(messageId)}"]`);
  const result = await api(`/api/messages/${messageId}`, { method: "DELETE" });
  if (node?.classList.contains("user") && result.turnId) {
    document.querySelectorAll(`[data-turn="${CSS.escape(result.turnId)}"]`).forEach((item) => item.remove());
  } else {
    node?.remove();
  }
  markLastUserMessage();
  toast("삭제 완료");
}

export function updateComposer() {
  const editing = Boolean(state.composerEdit);
  const needsProfile = needsUserProfileSelection();
  const canSend = editing
    ? Boolean($("messageInput").value.trim())
    : Boolean($("messageInput").value.trim() || canSendEmptyMessage() || canResendEditedUserMessage());
  $("messageInput").disabled = state.streaming || needsProfile;
  $("composer").classList.toggle("busy", state.streaming);
  $("composer").classList.toggle("editing", editing);
  $("composer").classList.toggle("profile-required", needsProfile);
  $("sendBtn").textContent = editing ? "✓" : "↑";
  $("sendBtn").setAttribute("title", editing ? "편집 저장" : "전송");
  $("sendBtn").setAttribute("aria-label", editing ? "편집 저장" : "전송");
  $("sendBtn").disabled = state.streaming || needsProfile || !canSend;
}

export function bindUserProfileSheet() {
  $("closeUserProfileBtn").onclick = closeUserProfileSheet;
  $("userProfileSheet").onclick = (event) => {
    const add = event.target.closest("#addUserProfileBtn");
    if (add) {
      event.preventDefault();
      showUserProfileEdit();
      return;
    }
    const edit = event.target.closest("[data-edit-user-profile]");
    if (edit) {
      event.preventDefault();
      event.stopPropagation();
      showUserProfileEdit(edit.dataset.editUserProfile);
      return;
    }
    const item = event.target.closest("[data-user-profile]");
    if (item) {
      event.preventDefault();
      selectConversationUserProfile(item.dataset.userProfile);
      return;
    }
    if (event.target === $("userProfileSheet")) {
      closeDropdowns();
      closeUserProfileSheet();
      return;
    }
    if (!event.target.closest(".dropdown")) closeDropdowns();
  };
  $("userProfileEditForm").onsubmit = async (event) => {
    event.preventDefault();
    await saveUserProfileEdit();
  };
  $("deleteUserProfileBtn").onclick = async () => {
    await deleteUserProfileEdit();
  };
}

function closeUserProfileSheet() {
  $("userProfileSheet").classList.remove("open");
  if (!needsUserProfileSelection()) return;
  state.composerHeight = null;
  state.composerMaxHeight = 136;
  $("messageInput").value = "";
  $("messageInput").blur();
  $("messageInput").dispatchEvent(new Event("input"));
  updateComposer();
}

export function promptUserProfileIfNeeded() {
  if (needsUserProfileSelection()) openUserProfileSheet();
}

export function needsUserProfileSelection() {
  return Boolean(state.conversation && !state.conversation.userProfileId);
}

export function messageNode(m) {
  const role = m.role === "user" ? "user" : "assistant";
  if (role === "user" && isControlMessage(m.content)) return null;
  const id = m.generation_id || "";
  const turn = m.turn_id || "";
  if (role === "assistant") return assistantMessageNode(m.content, id, turn, m.id || "");
  return userMessageNode(m.content, m.id || "", turn);
}

function renderMessages(messages) {
  setChildren($("messages"), [
    el("div", { className: "notice", text: "AI가 생성한 내용입니다." }),
    ...messages.map(messageNode).filter(Boolean),
  ]);
  markLastUserMessage();
  hydrateTurnGenerations();
  $("messages").scrollTop = $("messages").scrollHeight;
}

function appendUserMessage(content = "") {
  const node = userMessageNode(content);
  $("messages").appendChild(node);
  markLastUserMessage();
  $("messages").scrollTop = $("messages").scrollHeight;
  return node;
}

function appendAssistantStream() {
  const node = el("div", { className: "message-group assistant streaming", dataset: { content: "" } });
  renderAssistantStream(node, "");
  $("messages").appendChild(node);
  $("messages").scrollTop = $("messages").scrollHeight;
  return node;
}

export function openUserProfileSheet() {
  showUserProfileList();
  $("userProfileSheet").classList.add("open");
}

function showUserProfileList() {
  $("userProfileSheetTitle").textContent = "내 대화 프로필";
  $("userProfileListView").classList.remove("is-hidden");
  $("userProfileEditForm").classList.add("is-hidden");
  renderUserProfileList();
}

function renderUserProfileList() {
  const users = [...state.users.values()];
  setChildren($("userProfileList"), users.length
    ? users.map(userProfileRow)
    : [el("div", { className: "empty", text: "프로필이 없습니다." })]);
}

function userProfileRow(user) {
  const selected = user.id === state.conversation?.userProfileId;
  return el("div", {
    className: `user-profile-row${selected ? " selected" : ""}`,
    dataset: { userProfile: user.id },
    attrs: { role: "button", tabindex: "0" },
  }, [
    profileAvatar(user, selected),
    el("div", { className: "user-profile-info" }, [
      el("strong", { text: userProfileName(user) }),
      el("span", { text: userProfilePreview(user) }),
    ]),
    el("button", {
      className: "icon-btn user-profile-edit-btn",
      type: "button",
      text: "✎",
      dataset: { editUserProfile: user.id },
      attrs: { title: "편집", "aria-label": "편집" },
    }),
  ]);
}

function showUserProfileEdit(userProfileId = "") {
  const user = userProfileId ? state.users.get(userProfileId) : null;
  $("userProfileSheetTitle").textContent = user ? "대화 프로필 편집" : "대화 프로필 추가";
  $("userProfileListView").classList.add("is-hidden");
  $("userProfileEditForm").classList.remove("is-hidden");
  $("editUserProfileId").value = user?.id || "";
  $("editUserProfileName").value = userProfileName(user) || "";
  $("editUserProfileSource").value = user?.source_text || "";
  $("deleteUserProfileBtn").hidden = !user;
  $("editUserProfileName").focus();
}

async function selectConversationUserProfile(userProfileId) {
  if (!state.conversation || !userProfileId) return;
  try {
    const detail = await api(`/api/conversations/${state.conversation.conversationId}/user-profile`, {
      method: "PUT",
      body: JSON.stringify({ userProfileId }),
    });
    state.conversation.userProfileId = detail.user_profile_id || null;
    state.selectedUserProfileId = state.conversation.userProfileId;
    const conv = state.conversations.find((item) => item.id === state.conversation.conversationId);
    if (conv) conv.user_profile_id = state.conversation.userProfileId;
    $("userProfileSheet").classList.remove("open");
    updateComposer();
    toast("프로필 변경 완료");
  } catch (err) {
    toast(err.message);
  }
}

async function saveUserProfileEdit() {
  const id = $("editUserProfileId").value.trim();
  const name = $("editUserProfileName").value.trim();
  const sourceText = $("editUserProfileSource").value.trim();
  if (!name || !sourceText) {
    toast("프로필 이름과 내용을 입력하세요");
    return;
  }
  try {
    const body = { type: "user_profile", name, displayName: name, sourceText };
    const user = id
      ? await api(`/api/user-profiles/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) })
      : await api("/api/user-profiles", { method: "POST", body: JSON.stringify({ id: makeUserProfileId(), ...body }) });
    state.users.set(user.id, user);
    showUserProfileList();
    toast("프로필 저장 완료");
  } catch (err) {
    toast(err.message);
  }
}

async function deleteUserProfileEdit() {
  const id = $("editUserProfileId").value.trim();
  if (!id || !(await confirmDialog(`${userProfileName(state.users.get(id))} 프로필을 삭제할까요?`, { danger: true }))) return;
  try {
    await api(`/api/user-profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.users.delete(id);
    if (state.conversation?.userProfileId === id) {
      state.conversation.userProfileId = null;
      state.selectedUserProfileId = null;
      const conv = state.conversations.find((item) => item.id === state.conversation.conversationId);
      if (conv) conv.user_profile_id = null;
    }
    showUserProfileList();
    toast("프로필 삭제 완료");
  } catch (err) {
    toast(err.message);
  }
}

function userProfileName(user) {
  if (!user) return "";
  const profile = parseJson(user.profile_json);
  return profile.displayName || profile.display_name || user.name || profile.name || user.id;
}

function userProfilePreview(user) {
  return (user.source_text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean).slice(0, 2).join(" ");
}

function profileAvatar(user, selected) {
  const src = safeProfileImage(parseJson(user.profile_json).avatarUrl);
  const content = src
    ? [el("img", { attrs: { src, alt: "" } })]
    : [el("span", { text: userProfileName(user).slice(0, 1) || "U" })];
  return el("span", { className: `profile-avatar${selected ? " selected" : ""}` }, [
    ...content,
    selected ? el("span", { className: "profile-selected-mark", text: "✓" }) : null,
  ]);
}

function safeProfileImage(value) {
  if (!value) return "";
  if (value.startsWith("data:image/")) return value;
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function makeUserProfileId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `user-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function isUserProfileError(err) {
  return String(err?.message || err).includes(NO_USER_PROFILE);
}

async function stream(path, body, bubble, userNode = null, variants = []) {
  await streamSse(path, body, (eventName, data) => {
    if (eventName === "start" && userNode && data.messageId) {
      userNode.replaceWith(userMessageNode(userNode.dataset.content || "", data.messageId, data.turnId || ""));
      markLastUserMessage();
    }
    if (eventName === "token") {
      const content = (bubble.dataset.content || "") + data.content;
      renderAssistantStream(bubble, content);
      $("messages").scrollTop = $("messages").scrollHeight;
    }
    if (eventName === "done") {
      if (variants.length) {
        variants.push({ gen: data.generationId, content: bubble.dataset.content || "" });
        bubble.dataset.variants = JSON.stringify(variants);
        bubble.dataset.variantIndex = String(variants.length - 1);
      }
      bubble.dataset.message = data.messageId || "";
      renderAssistantStream(bubble, bubble.dataset.content || "", data.generationId, data.turnId, variants, data.messageId || "");
      bubble.classList.remove("streaming");
    }
    if (eventName === "error") throw new Error(data.message || data.error);
  });
}

function renderAssistantStream(node, content, id = "", turn = "", variants = assistantVariants(node), messageId = node.dataset.message || "") {
  node.dataset.content = content;
  node.dataset.gen = id;
  node.dataset.message = messageId;
  node.dataset.turn = turn;
  if (variants.length) node.dataset.variants = JSON.stringify(variants);
  const parts = parseSpeakerParts(content);
  node.classList.toggle("mixed-speakers", hasUserSpeaker(parts));
  const children = !content
    ? [loadingBubbleNode()]
    : parts.length === 1 && parts[0].speaker == null
    ? [bubbleNode("assistant", content)]
    : parts.flatMap(speakerPartNodes);
  const variantIndex = Number(node.dataset.variantIndex || Math.max(0, variants.length - 1));
  setChildren(node, [...children, actionNode(id, turn, variants, variantIndex, messageId)]);
}

function renderAssistantError(node, message) {
  node.dataset.content = message;
  setChildren(node, [bubbleNode("assistant danger", message)]);
}

function assistantMessageNode(content, id, turn, messageId = "") {
  const parts = parseSpeakerParts(content);
  const node = el("div", {
    className: `message-group assistant${hasUserSpeaker(parts) ? " mixed-speakers" : ""}`,
    dataset: { gen: id, message: messageId, turn, content },
  });
  if (parts.length === 1 && parts[0].speaker == null) {
    setChildren(node, [bubbleNode("assistant", content), actionNode(id, turn, [], 0, messageId)]);
    return node;
  }

  setChildren(node, [
    ...parts.flatMap(speakerPartNodes),
    actionNode(id, turn, [], 0, messageId),
  ]);
  return node;
}

async function loadTurnGenerations(node) {
  try {
    const data = await api(`/api/turns/${encodeURIComponent(node.dataset.turn)}/generations`);
    const variants = (data.generations || []).map((item) => ({ gen: item.generationId, content: item.content }));
    if (variants.length < 2) return;
    const selected = Math.max(0, data.generations.findIndex((item) => item.selected || item.generationId === data.selectedGenerationId));
    node.dataset.variants = JSON.stringify(variants);
    renderAssistantVariant(node, selected);
  } catch {}
}

function userMessageNode(content, messageId = "", turn = "") {
  const parts = parseSpeakerParts(content);
  const explicitSpeaker = hasExplicitSpeaker(parts);
  const node = el("div", {
    className: `message-group user${explicitSpeaker ? " mixed-speakers" : ""}`,
    dataset: { message: messageId, turn, content },
  });
  setChildren(node, [
    ...(explicitSpeaker ? parts.flatMap(speakerPartNodes) : [bubbleNode("user", content)]),
    userActionNode(messageId),
  ]);
  return node;
}

export function markLastUserMessage() {
  const messages = [...document.querySelectorAll("#messages .message-group.user")];
  messages.forEach((node) => node.classList.remove("last-user-message"));
  messages.at(-1)?.classList.add("last-user-message");
  updateComposer();
}

export function lastUserMessageContent() {
  return document.querySelector("#messages .last-user-message")?.dataset.content || "";
}

export function canSendEmptyMessage() {
  const last = [...document.querySelectorAll("#messages .message-group")].at(-1);
  return Boolean(last?.classList.contains("assistant"));
}

function isControlMessage(content) {
  return !String(content || "").trim();
}

function speakerPartNodes(part) {
  if (isNarrationSpeaker(part.speaker)) return [narrationNode(part.text)];
  if (isUserSpeaker(part.speaker)) return [bubbleNode("user", part.text)];
  return [
    part.speaker ? el("div", { className: "speaker-name", text: part.speaker }) : null,
    bubbleNode("assistant", part.text),
  ];
}

function bubbleNode(className, content) {
  return el("div", { className: `bubble ${className}` }, [renderMarkdown(content)]);
}

function narrationNode(content) {
  return el("div", { className: "narration" }, [
    el("span", { className: "narration-mark", text: "◇" }),
    el("div", { className: "narration-body" }, [renderMarkdown(content)]),
  ]);
}

function isNarrationSpeaker(speaker) {
  return speaker === "" || speaker === "관찰자";
}

function isUserSpeaker(speaker) {
  if (!speaker) return false;
  const user = state.conversation?.userProfileId ? state.users.get(state.conversation.userProfileId) : null;
  const normalized = normalizeSpeakerName(speaker);
  return userSpeakerNames(user).some((name) => normalizeSpeakerName(name) === normalized);
}

function hasUserSpeaker(parts) {
  return parts.some((part) => isUserSpeaker(part.speaker));
}

function hasExplicitSpeaker(parts) {
  return parts.some((part) => part.speaker !== null);
}

function userSpeakerNames(user) {
  if (!user) return [];
  const profile = parseJson(user.profile_json);
  return [userProfileName(user), user.id, user.name, profile.name, profile.displayName, profile.display_name].filter(Boolean);
}

function normalizeSpeakerName(name) {
  return String(name || "").trim().toLowerCase();
}

function loadingBubbleNode() {
  return el("div", { className: "bubble assistant loading" }, [
    el("span", { className: "loading-dots" }, [
      el("span", { text: "." }),
      el("span", { text: "." }),
      el("span", { text: "." }),
    ]),
  ]);
}

function actionNode(id, turn, variants = [], variantIndex = Math.max(0, variants.length - 1), messageId = "") {
  if (!id && !turn) return null;
  const variantNav = currentVariantMeta(id, variants, variantIndex);
  return el("div", { className: "actions" }, [
    variantNav,
    turn ? iconAction("regen", "↻", "다시 생성", { turn }, "regen-action") : null,
    id ? actionMenu([
      id ? menuAction("edit-generation", "편집", { gen: id }) : null,
      menuAction("copy", "복사"),
      messageId ? menuAction("delete-message", "삭제", { message: messageId }, "danger") : null,
    ]) : null,
  ]);
}

function currentVariantMeta(id, variants, index) {
  return id && variants.length > 1 ? el("div", { className: "variant-nav" }, [
    iconAction("variant-prev", "‹", "이전 응답"),
    el("span", { text: `${index + 1}/${variants.length}` }),
    iconAction("variant-next", "›", "다음 응답"),
  ]) : null;
}

function userActionNode(messageId) {
  return el("div", { className: "actions" }, [
    actionMenu([
      messageId ? menuAction("edit-user", "편집", { message: messageId }) : null,
      menuAction("copy", "복사"),
      messageId ? menuAction("delete-message", "삭제", { message: messageId }, "danger") : null,
    ]),
  ]);
}

function actionMenu(items) {
  return el("div", { className: "action-menu" }, [
    el("button", {
      className: "icon-action menu-trigger",
      text: "⋯",
      dataset: { actionMenu: "true" },
      attrs: { type: "button", title: "메뉴", "aria-label": "메뉴" },
    }),
    el("div", { className: "dropdown action-dropdown" }, items),
  ]);
}

function menuAction(action, label, dataset = {}, className = "") {
  return el("button", { className, text: label, dataset: { action, ...dataset }, attrs: { type: "button" } });
}

function iconAction(action, icon, label, dataset = {}, className = "") {
  return el("button", {
    className: `icon-action ${className}`.trim(),
    text: icon,
    dataset: { action, ...dataset },
    attrs: { type: "button", title: label, "aria-label": label },
  });
}

export async function showAssistantVariant(node, direction) {
  const variants = assistantVariants(node);
  if (variants.length < 2) return;
  const current = Number(node.dataset.variantIndex || variants.length - 1);
  const next = Math.max(0, Math.min(variants.length - 1, current + direction));
  if (next === current) return;
  renderAssistantVariant(node, next);
  await api(`/api/generations/${variants[next].gen}/select`, { method: "POST", body: "{}" });
}

function renderAssistantVariant(node, index) {
  const variants = assistantVariants(node);
  const item = variants[index];
  if (!item) return;
  node.dataset.variantIndex = String(index);
  renderAssistantStream(node, item.content, item.gen, node.dataset.turn, variants);
  const label = node.querySelector(".variant-nav span");
  if (label) label.textContent = `${index + 1}/${variants.length}`;
}

function assistantVariants(node) {
  try {
    const parsed = JSON.parse(node.dataset.variants || "[]");
    if (Array.isArray(parsed) && parsed.length) return parsed;
  } catch {}
  return node.dataset.gen ? [{ gen: node.dataset.gen, content: node.dataset.content || "" }] : [];
}

function parseSpeakerParts(content) {
  const text = String(content || "");
  const matches = [...text.matchAll(/^@([^:\n]{0,40}):[ \t]*/gm)];
  if (!matches.length) return [{ speaker: null, text }];

  const parts = [];
  if (matches[0].index > 0) parts.push({ speaker: null, text: text.slice(0, matches[0].index).trim() });

  matches.forEach((match, index) => {
    const start = match.index + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : text.length;
    parts.push({ speaker: match[1].trim(), text: text.slice(start, end).trim() });
  });

  return parts.filter((part) => part.text);
}
