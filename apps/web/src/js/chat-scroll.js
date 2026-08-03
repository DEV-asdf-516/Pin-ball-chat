import { $ } from "./dom.js";

const LATEST_MESSAGE_THRESHOLD = 80;

export function messagesNearLatest() {
  const messages = $("messages");
  return messages.scrollTop + messages.clientHeight >= messages.scrollHeight - LATEST_MESSAGE_THRESHOLD;
}

export function settleMessagesAtLatest() {
  jumpMessagesToLatest();
  syncLatestMessageButton();
  requestAnimationFrame(() => {
    jumpMessagesToLatest();
    syncLatestMessageButton();
  });
}

export function scrollMessagesToLatest() {
  const messages = $("messages");
  messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
}

export function syncLatestMessageButton() {
  const input = $("messageInput");
  const composer = $("composer");
  const composing = Boolean(
    input?.value
    || document.activeElement === input
    || composer?.classList.contains("expanded"),
  );
  $("latestMessageBtn").hidden = composing || messagesNearLatest();
}

function jumpMessagesToLatest() {
  const messages = $("messages");
  const previousBehavior = messages.style.scrollBehavior;
  messages.style.scrollBehavior = "auto";
  messages.scrollTop = messages.scrollHeight;
  messages.style.scrollBehavior = previousBehavior;
}
