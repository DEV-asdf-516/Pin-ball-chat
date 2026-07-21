import { api, apiBase } from "./api.js";
import { activeConversation, conversationActivated, messagesLoaded } from "./actions.js";
import { createCharacter, createPlot, loadCatalog, loadMorePlots, openPlot, renderPlots, uploadCharacterAvatar } from "./catalog.js";
import { bindUserProfileSheet, cancelChatStream, cancelComposerEdit, canResendEditedUserMessage, canSendEmptyMessage, deleteMessage, deleteMessagesFrom, editGeneration, editUserMessage, hydrateTurnGenerations, loadMessages, markLastUserMessage, messageNode, needsUserProfileSelection, openUserProfileSheet, promptUserProfileIfNeeded, regenerate, resendEditedUserMessage, saveComposerEdit, sendMessage, showAssistantVariant, updateComposer } from "./chat.js";
import { keys } from "./config.js";
import * as conversations from "./conversations.js";
import { $, closeDropdowns, confirmDialog, el, openDropdown, parseJson, toast, toggleDropdown } from "./dom.js";
import { activateFormTab, bindFormTabs } from "./form-tabs.js";
import { bindGenrePicker, renderGenrePicker, selectedGenres } from "./genres.js";
import { bindIntroEditor, introValue, renderIntroEditor } from "./intro-editor.js";
import { bindPlotManager, closePlotManagerEdit, openManagedPlot, openPlotManager } from "./plot-manager.js";
import { applyTheme, bindSettings, loadConversationSettings, loadSettings } from "./settings.js";
import { state } from "./state.js";
import { mountApp, showScreen } from "./ui.js";

let cancelInlineTitleEdit = null;

async function startChat() {
  try {
    const title = state.selectedPlot.title || state.selectedPlot.id;
    const conv = conversationActivated(await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ plotId: state.selectedPlot.id, title }),
    }), false);
    if (!conv.title) conv.title = title;
    const recent = parseJson(localStorage.getItem(keys.recent));
    recent[state.selectedPlot.id] = Date.now();
    localStorage.setItem(keys.recent, JSON.stringify(recent));
    await loadConversationSettings();
    await loadMessages();
    showScreen("chat");
    promptUserProfileIfNeeded();
    conversations.loadConversations();
  } catch (err) {
    toast(err.message);
  }
}

function showPlots() {
  setTab("plots");
  showScreen("plots");
}

function showConversations() {
  setTab("conversations");
  showScreen("conversations");
  conversations.loadConversations();
}

function setTab(tab) {
  document.querySelectorAll("[data-tab]").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
}

function bindCatalog() {
  $("reloadBtn").onclick = loadCatalog;
  $("searchInput").oninput = renderPlots;
  document.querySelectorAll("[data-tab='plots']").forEach((btn) => {
    btn.onclick = showPlots;
  });
  document.querySelectorAll("[data-tab='conversations']").forEach((btn) => {
    btn.onclick = showConversations;
  });
  $("plotList").onclick = async (event) => {
    const card = event.target.closest("[data-plot]");
    if (!card) return;
    await openPlot(card.dataset.plot);
    showScreen("detail");
  };
  $("plotList").onscroll = async () => {
    if (nearBottom($("plotList"))) await loadMorePlots();
  };
  bindPlotFab();
  $("fabManagePlotsBtn").onclick = () => {
    closeDropdowns();
    openPlotManager();
    showScreen("plotManage");
  };
  $("startChatBtn").onclick = startChat;
  $("reloadConversationsBtn").onclick = conversations.loadConversations;
  $("conversationSearchInput").oninput = conversations.renderConversations;
  $("conversationList").onscroll = async () => {
    if (nearBottom($("conversationList"))) await conversations.loadMoreConversations();
  };
  let titleEditTimer = null;
  let titleEditOpened = false;
  $("conversationList").onpointerdown = (event) => {
    if (event.target.closest(".title-inline-input")) return;
    const target = event.target.closest("[data-conversation-title-menu]");
    if (!target || event.target.closest("button")) return;
    titleEditTimer = setTimeout(() => {
      titleEditOpened = true;
      editConversationTitleById(target.dataset.conversationTitleMenu, target.textContent.trim(), target);
    }, 520);
  };
  $("conversationList").onpointerup = () => clearTimeout(titleEditTimer);
  $("conversationList").onpointercancel = () => clearTimeout(titleEditTimer);
  $("conversationList").onpointerleave = () => clearTimeout(titleEditTimer);
  $("conversationList").oncontextmenu = (event) => {
    const target = event.target.closest("[data-conversation-title-menu]");
    if (!target) return;
    event.preventDefault();
    editConversationTitleById(target.dataset.conversationTitleMenu, target.textContent.trim(), target);
  };
  $("conversationList").onclick = async (event) => {
    if (event.target.closest(".title-inline-input")) return;
    if (titleEditOpened) {
      titleEditOpened = false;
      event.preventDefault();
      return;
    }
    const menuBtn = event.target.closest("button[data-conversation-menu]");
    if (menuBtn) {
      event.stopPropagation();
      const menu = menuBtn.closest(".menu-wrap")?.querySelector(".dropdown");
      toggleDropdown(menu, menuBtn);
      return;
    }

    const editTitleBtn = event.target.closest("button[data-edit-conversation-title]");
    if (editTitleBtn) {
      event.stopPropagation();
      closeDropdowns();
      editConversationTitleById(editTitleBtn.dataset.editConversationTitle);
      return;
    }

    const deleteBtn = event.target.closest("button[data-delete-conversation]");
    if (deleteBtn) {
      event.stopPropagation();
      const conversationId = deleteBtn.dataset.deleteConversation;
      if (!(await confirmDialog("이 대화를 삭제할까요? 메시지와 생성 기록도 함께 삭제됩니다.", { danger: true }))) return;
      try {
        await conversations.deleteConversation(conversationId);
        toast("대화를 삭제했습니다.");
      } catch (err) {
        toast(err.message);
      }
      return;
    }

    const target = event.target.closest("[data-conversation]");
    if (!target) return;
    closeDropdowns();
    const conversationId = target.dataset.conversation;
    const conv = conversations.findConversation(conversationId);
    if (!conv) return;
    conversationActivated(conv, true);
    await openPlot(conv.plotId, conv.userProfileId);
    await loadConversationSettings();
    await loadMessages();
    showScreen("chat");
    promptUserProfileIfNeeded();
  };
}

function bindPlotCreate() {
  bindFormTabs("plotCreateForm");
  bindGenrePicker("plotCreateGenreList");
  renderGenrePicker("plotCreateGenreList");
  bindIntroEditor("plotCreateIntroEditor");
  renderIntroEditor("plotCreateIntroEditor");
  $("plotCreateCharacterAvatarFile").onchange = readCreateAvatarFile;
  $("plotCreateForm").onsubmit = async (event) => {
    event.preventDefault();
    const title = $("plotCreateTitle").value.trim();
    const sourceText = $("plotCreateSource").value.trim();
    const characterName = $("plotCreateCharacterName").value.trim();
    const characterSource = $("plotCreateCharacterSource").value.trim();
    if (!title || !sourceText || !characterName || !characterSource) {
      toast("제목, 내용, 캐릭터 정보를 입력하세요");
      return;
    }
    const id = makeCatalogId();
    const characterId = makeCatalogId();
    try {
      const character = await createCharacter({
        id: characterId,
        type: "character",
        name: characterName,
        displayName: characterName,
        sourceText: characterSource,
      });
      await uploadCreateAvatarIfNeeded(character.id || characterId);
      const intro = introValue("plotCreateIntroEditor");
      const plot = await createPlot({
        id,
        type: "plot",
        title,
        characterId,
        genre: selectedGenres("plotCreateGenreList"),
        sourceText,
        ...(intro ? { intro } : {}),
      });
      toast("플롯을 저장했습니다");
      $("plotCreateForm").reset();
      clearCreateAvatarPreview();
      renderGenrePicker("plotCreateGenreList");
      renderIntroEditor("plotCreateIntroEditor");
      activateFormTab("plotCreateForm", "prompt");
      await openPlot(plot.id, null, plot);
      showScreen("detail");
    } catch (err) {
      toast(err.message);
    }
  };
}

function bindPlotFab() {
  let longPressTimer = null;
  let longPressOpened = false;
  const openFabMenu = () => {
    longPressOpened = true;
    closeDropdowns();
    $("plotFabMenu").classList.add("open");
  };
  const openCreate = () => {
    closeDropdowns();
    $("plotCreateForm").reset();
    clearCreateAvatarPreview();
    renderGenrePicker("plotCreateGenreList");
    renderIntroEditor("plotCreateIntroEditor");
    activateFormTab("plotCreateForm", "prompt");
    showScreen("plotCreate");
  };
  $("newPlotFab").onpointerdown = () => {
    longPressTimer = setTimeout(openFabMenu, 520);
  };
  $("newPlotFab").onpointerup = () => clearTimeout(longPressTimer);
  $("newPlotFab").onpointercancel = () => clearTimeout(longPressTimer);
  $("newPlotFab").onpointerleave = () => clearTimeout(longPressTimer);
  $("newPlotFab").oncontextmenu = (event) => {
    event.preventDefault();
    openFabMenu();
  };
  $("newPlotFab").onclick = () => {
    if (longPressOpened) {
      longPressOpened = false;
      return;
    }
    openCreate();
  };
  $("plotsScreen").onclick = (event) => {
    if (event.target.closest("#newPlotFab, #plotFabMenu")) return;
    closeDropdowns();
  };
}

function bindChat() {
  bindComposerResize();
  let longPressTimer = null;
  let longPressOpened = false;
  let lastComposerResetTap = 0;
  $("chatBackBtn").onclick = async () => {
    if (cancelActiveTitleEdit()) return;
    cancelChatStream();
    if (state.ui.chatFromList) {
      showScreen("conversations");
      await conversations.loadConversations();
      return;
    }
    showScreen("detail");
  };
  $("chatUserProfileBtn").onclick = () => openUserProfileSheet();
  bindComposerSymbol("insertMentionBtn", "@");
  bindComposerSymbol("insertAsteriskBtn", "*");
  $("composer").onclick = (event) => {
    if (!needsUserProfileSelection()) return;
    event.preventDefault();
    promptUserProfileIfNeeded();
  };
  $("composer").onsubmit = async (event) => {
    event.preventDefault();
    if (state.composerEdit) {
      await saveComposerEdit();
      resizeComposerInput();
      return;
    }
    const inputMessage = $("messageInput").value.trim();
    const hasInput = Boolean(inputMessage);
    if (state.streaming || (!hasInput && !canSendEmptyMessage() && !canResendEditedUserMessage())) return;
    if (needsUserProfileSelection()) {
      promptUserProfileIfNeeded();
      return;
    }
    if (!hasInput && canResendEditedUserMessage()) {
      await resendEditedUserMessage();
      resizeComposerInput();
      return;
    }
    if (inputMessage) $("messageInput").value = "";
    updateComposer();
    sendMessage(hasInput ? inputMessage : "", { silentUser: !hasInput });
  };
  $("messageInput").oninput = () => {
    resizeComposerInput();
    updateComposer();
  };
  $("messageInput").onkeydown = (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape" && state.composerEdit) {
      event.preventDefault();
      cancelComposerEdit();
      resizeComposerInput();
      return;
    }
    if (event.key === "Enter" && (event.shiftKey || event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  };
  $("messages").onpointerdown = (event) => {
    if (event.target.closest("button")) return;
    const message = event.target.closest(".message-group.user");
    if (!message) return;
    longPressTimer = setTimeout(() => {
      longPressOpened = true;
      openMessageMenu(message);
    }, 520);
  };
  $("messages").onpointerup = (event) => {
    clearTimeout(longPressTimer);
    if (longPressOpened || event.target.closest("button, .action-menu")) return;
    const now = Date.now();
    if (state.composerHeight && now - lastComposerResetTap < 320) {
      event.preventDefault();
      resetComposerSize();
      lastComposerResetTap = 0;
      return;
    }
    lastComposerResetTap = now;
  };
  $("messages").onpointercancel = () => clearTimeout(longPressTimer);
  $("messages").onpointerleave = () => clearTimeout(longPressTimer);
  $("messages").oncontextmenu = (event) => {
    if (!event.target.closest(".message-group.user")) return;
    event.preventDefault();
  };
  $("messages").onclick = async (event) => {
    if (longPressOpened) {
      longPressOpened = false;
      event.preventDefault();
      return;
    }
    const menuBtn = event.target.closest("button[data-action-menu]");
    if (menuBtn) {
      event.stopPropagation();
      const menu = menuBtn.closest(".action-menu")?.querySelector(".dropdown");
      toggleDropdown(menu, menuBtn);
      (menuBtn.closest(".message-group") || menuBtn.closest(".bubble"))?.classList.add("active");
      return;
    }

    const btn = event.target.closest("button[data-action]");
    if (!btn) {
      document.querySelectorAll("#messages .active").forEach((node) => node.classList.remove("active"));
      closeDropdowns();
      (event.target.closest(".message-group") || event.target.closest(".bubble"))?.classList.add("active");
      return;
    }
    try {
      if (btn.dataset.action === "regen") await regenerate(btn.dataset.turn, btn.closest(".message-group.assistant"));
      if (btn.dataset.action === "variant-prev") await showAssistantVariant(btn.closest(".message-group.assistant"), -1);
      if (btn.dataset.action === "variant-next") await showAssistantVariant(btn.closest(".message-group.assistant"), 1);
      if (btn.dataset.action === "edit-generation") await editGeneration(btn.dataset.gen);
      if (btn.dataset.action === "edit-user") await editUserMessage(btn.dataset.message);
      if (btn.dataset.action === "delete-message" && await confirmDialog("이 메시지를 삭제할까요?", { danger: true })) await deleteMessage(btn.dataset.message);
      if (btn.dataset.action === "batch-delete-message" && await confirmDialog("이 메시지부터 아래 대화를 삭제할까요?", { danger: true })) await deleteMessagesFrom(btn.dataset.message);
      if (btn.dataset.action === "copy") {
        const message = btn.closest("[data-content]");
        const text = message?.dataset.content || "";
        await navigator.clipboard.writeText(text);
        toast("복사 완료");
      }
      closeDropdowns();
    } catch (err) {
      toast(err.message);
    }
  };
  $("messages").onscroll = async () => {
    if ($("messages").scrollTop >= 40 || !state.activeMessages.hasMore || state.streaming) return;
    const height = $("messages").scrollHeight;
    try {
      const convId = state.activeConversationId;
      const page = await api(`/api/conversations/${convId}/messages?before=${state.activeMessages.nextCursor}&limit=30`);
      messagesLoaded(page, true);
      const nodes = page.messages.map(messageNode).filter(Boolean);
      const notice = $("messages").querySelector(".notice");
      notice ? notice.after(...nodes) : $("messages").prepend(...nodes);
      markLastUserMessage();
      hydrateTurnGenerations($("messages"));
      $("messages").scrollTop = $("messages").scrollHeight - height;
    } catch {}
  };
}

function bindComposerSymbol(id, value) {
  const button = $(id);
  button.onpointerdown = (event) => event.preventDefault();
  button.onclick = () => {
    const input = $("messageInput");
    if (input.disabled) return;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    input.setRangeText(value, start, end, "end");
    input.focus();
    input.dispatchEvent(new Event("input"));
  };
}

function bindHeaderTitleEdit() {
  let timer = null;
  let titleEditOpened = false;
  const title = document.querySelector(".chat-head-title");
  const clear = () => clearTimeout(timer);
  title.onpointerdown = (event) => {
    if (event.target.closest(".title-inline-input")) return;
    if (state.route !== "chat" || !activeConversation()) return;
    timer = setTimeout(() => {
      titleEditOpened = true;
      editConversationTitle($("chatHeaderTitle"));
    }, 520);
  };
  title.onpointerup = clear;
  title.onpointercancel = clear;
  title.onpointerleave = clear;
  title.oncontextmenu = (event) => {
    if (state.route !== "chat") return;
    event.preventDefault();
    editConversationTitle($("chatHeaderTitle"));
  };
  title.onclick = (event) => {
    if (event.target.closest(".dropdown, .title-inline-input")) return;
    if (titleEditOpened) {
      titleEditOpened = false;
      event.preventDefault();
    }
  };
}

function openConversationCardMenu(target) {
  const card = target.closest("[data-conversation]");
  const menu = card?.querySelector(".dropdown");
  const trigger = card?.querySelector("button[data-conversation-menu]") || target;
  toggleDropdown(menu, trigger);
}

function editConversationTitle(target = $("chatHeaderTitle")) {
  const conversationId = state.activeConversationId;
  if (!conversationId) return;
  closeDropdowns();
  const current = activeConversation()?.title || $("chatHeaderTitle").textContent.trim();
  startInlineTitleEdit(conversationId, current, target);
}

function editConversationTitleById(conversationId, current = "", target = null) {
  const node = target || document.querySelector(`[data-conversation="${CSS.escape(conversationId)}"] [data-conversation-title-menu]`);
  if (!node) return;
  closeDropdowns();
  startInlineTitleEdit(conversationId, current || node.textContent.trim(), node);
}

function startInlineTitleEdit(conversationId, current, target) {
  if (!target || target.querySelector(".title-inline-input")) return;
  cancelActiveTitleEdit();
  closeDropdowns();
  const original = target.textContent;
  const input = document.createElement("input");
  input.className = "title-inline-input";
  input.value = current;
  input.setAttribute("aria-label", "대화 제목");
  target.replaceChildren(input);
  input.focus();
  input.select();

  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    cancelInlineTitleEdit = null;
    const title = input.value.trim();
    if (!save || !title || title === current) {
      target.textContent = original;
      return;
    }
    try {
      const nextTitle = await updateConversationTitle(conversationId, title);
      if (state.route === "chat") showScreen("chat");
      else target.textContent = nextTitle;
      toast("제목 변경 완료");
    } catch (err) {
      target.textContent = original;
      toast(err.message);
    }
  };
  const cancel = () => finish(false);
  cancelInlineTitleEdit = cancel;

  input.onkeydown = (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  };
  input.onblur = () => finish(true);
}

function cancelActiveTitleEdit() {
  if (!cancelInlineTitleEdit) return false;
  cancelInlineTitleEdit();
  return true;
}

async function updateConversationTitle(conversationId, title) {
  if (conversations.updateConversationTitle) return conversations.updateConversationTitle(conversationId, title);
  const result = await api(`/api/conversations/${encodeURIComponent(conversationId)}/title`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
  return result?.title || title;
}

function openMessageMenu(message) {
  document.querySelectorAll("#messages .active").forEach((node) => node.classList.remove("active"));
  closeDropdowns();
  message.classList.add("active");
  openDropdown(message.querySelector(".action-dropdown"), message.querySelector("[data-action-menu]"));
}

function bindComposerResize() {
  const input = $("messageInput");
  const handle = $("composerHandle");
  handle.onpointerdown = (event) => {
    event.preventDefault();
    const startY = event.clientY;
    const startMax = state.composerMaxHeight;
    const minHeight = composerMinHeight(input);

    const onMove = (moveEvent) => {
      moveEvent.preventDefault();
      const next = startMax + startY - moveEvent.clientY;
      state.composerHeight = Math.max(minHeight, Math.min(Math.round(window.innerHeight - 120), next));
      state.composerMaxHeight = state.composerHeight;
      resizeComposerInput();
    };
    const onEnd = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
      window.removeEventListener("pointercancel", onEnd);
    };
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onEnd);
    window.addEventListener("pointercancel", onEnd);
  };
  handle.ondblclick = resetComposerSize;
}

function composerMinHeight(input) {
  const previousHeight = input.style.height;
  input.style.height = "";
  const height = Math.ceil(input.getBoundingClientRect().height || input.scrollHeight || 44);
  input.style.height = previousHeight;
  return height;
}

function resetComposerSize() {
  state.composerHeight = null;
  state.composerMaxHeight = 136;
  $("messageInput").style.height = "";
  resizeComposerInput();
}

async function restoreRoute() {
  const saved = parseJson(localStorage.getItem(keys.route));
  if (!saved.route || saved.route === "plots") return;
  try {
    if (saved.route === "detail" && saved.plotId) {
      await openPlot(saved.plotId);
      showScreen("detail");
      return;
    }
    if (saved.route === "plotCreate") {
      showScreen("plotCreate");
      return;
    }
    if (saved.route === "plotManage") {
      openPlotManager();
      showScreen("plotManage");
      if (saved.managedPlotId) await openManagedPlot(saved.managedPlotId);
      return;
    }
    if (saved.route === "conversations") {
      showConversations();
      return;
    }
    if (saved.route === "chat" && saved.conversationId) {
      const conv = conversationActivated(await api(`/api/conversations/${encodeURIComponent(saved.conversationId)}`), true);
      await openPlot(conv.plotId, conv.userProfileId, { id: conv.plotId, title: conv.title || "플롯", character_id: "", source_text: "", plot_json: "{}" });
      await loadConversationSettings();
      await loadMessages();
      showScreen("chat");
      promptUserProfileIfNeeded();
    }
  } catch {
    showScreen("plots");
  }
}

function nearBottom(node) {
  return node.scrollTop + node.clientHeight >= node.scrollHeight - 80;
}

function makeCatalogId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function renderCreateAvatarPreview() {
  const preview = $("plotCreateAvatarPreview");
  if (!preview) return;
  const src = safeImageUrl(getCreateAvatarPreviewUrl());
  preview.replaceChildren();
  preview.classList.toggle("has-image", Boolean(src));
  if (!src) {
    preview.textContent = "+";
    return;
  }
  preview.append(el("img", { attrs: { src, alt: "" } }));
}

function clearCreateAvatarPreview() {
  const preview = $("plotCreateAvatarPreview");
  if (preview) preview.dataset.previewUrl = "";
  const input = $("plotCreateCharacterAvatarFile");
  if (input) input.value = "";
  renderCreateAvatarPreview();
}

function readCreateAvatarFile() {
  const file = $("plotCreateCharacterAvatarFile").files?.[0];
  const preview = $("plotCreateAvatarPreview");
  if (!file || !preview) {
    if (preview) preview.dataset.previewUrl = "";
    renderCreateAvatarPreview();
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    preview.dataset.previewUrl = typeof reader.result === "string" ? reader.result : "";
    renderCreateAvatarPreview();
  };
  reader.onerror = () => {
    preview.dataset.previewUrl = "";
    renderCreateAvatarPreview();
    toast("이미지를 읽지 못했습니다");
  };
  reader.readAsDataURL(file);
}

function getCreateAvatarPreviewUrl() {
  return $("plotCreateAvatarPreview")?.dataset.previewUrl || "";
}

async function uploadCreateAvatarIfNeeded(characterId) {
  const file = $("plotCreateCharacterAvatarFile")?.files?.[0];
  if (!file) return;
  await uploadCharacterAvatar(characterId, file);
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

function resizeComposerInput() {
  const input = $("messageInput");
  input.style.setProperty("--composer-max-height", `${state.composerMaxHeight}px`);
  if (state.composerHeight) {
    input.style.height = `${state.composerHeight}px`;
    return;
  }
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, state.composerMaxHeight) + "px";
}

async function init() {
  mountApp();
  $("backBtn").onclick = () => {
    if (cancelActiveTitleEdit()) return;
    if (state.route === "plotManage" && closePlotManagerEdit()) return;
    else showPlots();
  };
  bindCatalog();
  bindPlotCreate();
  bindPlotManager();
  conversations.bindConversationSubscriptions();
  bindChat();
  bindHeaderTitleEdit();
  bindSettings();
  bindUserProfileSheet();
  applyTheme();
  loadSettings();
  updateComposer();
  try {
    await loadCatalog();
  } catch {}
  await conversations.loadConversations();
  await restoreRoute();
}

init();
