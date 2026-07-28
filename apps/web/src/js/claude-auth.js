import { api } from "./api.js";

const status = document.getElementById("claudeAuthStatus");

try {
  const connection = await api("/api/provider-connections/claude-cli/login", { method: "POST" });
  if (!connection?.verificationUrl) throw new Error("Claude 인증 URL을 받지 못했습니다. 로그인 상태를 다시 확인하세요.");
  notifyOpener("pinballchat:claude-login-started", { connection });
  window.opener = null;
  window.location.replace(connection.verificationUrl);
} catch (error) {
  notifyOpener("pinballchat:claude-login-error", { message: error.message || "Claude 로그인을 시작하지 못했습니다." });
  status.textContent = error.message || "Claude 로그인을 시작하지 못했습니다.";
}

function notifyOpener(type, detail) {
  if (window.opener && window.opener !== window) {
    window.opener.postMessage({ type, ...detail }, window.location.origin);
  }
}
