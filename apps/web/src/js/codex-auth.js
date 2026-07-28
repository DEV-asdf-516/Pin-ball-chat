import { api } from "./api.js";

const status = document.getElementById("codexAuthStatus");

try {
  const connection = await api("/api/provider-connections/openai-codex/login", { method: "POST" });
  if (!connection?.verificationUrl || !connection?.userCode) throw new Error("Codex 인증 정보를 받지 못했습니다.");
  notifyOpener("pinballchat:codex-login-started", { connection });
  window.opener = null;
  window.location.replace(connection.verificationUrl);
} catch (error) {
  notifyOpener("pinballchat:codex-login-error", { message: error.message || "Codex 로그인을 시작하지 못했습니다." });
  status.textContent = error.message || "Codex 로그인을 시작하지 못했습니다.";
}

function notifyOpener(type, detail) {
  if (window.opener && window.opener !== window) {
    window.opener.postMessage({ type, ...detail }, window.location.origin);
  }
}
