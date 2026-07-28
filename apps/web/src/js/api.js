import { keys } from "./config.js";

export function apiBase() {
  const saved = localStorage.getItem(keys.apiBase)?.trim();
  if (saved) return saved.replace(/\/$/, "");
  const current = new URL(location.href);
  current.port = "8080";
  current.pathname = "";
  current.search = "";
  current.hash = "";
  return current.origin;
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body != null && !(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(apiBase() + path, {
    ...options,
    headers,
  });
  if (!res.ok) {
    let body = {};
    try {
      body = await res.json();
    } catch {}
    throw responseError(body, res.statusText, res.status);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function uploadFile(path, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(apiBase() + path, { method: "POST", body: form });
  if (!res.ok) {
    let body = {};
    try {
      body = await res.json();
    } catch {}
    throw responseError(body, res.statusText, res.status);
  }
  return res.json();
}

export async function streamSse(path, body, onEvent, signal) {
  const res = await fetch(apiBase() + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const text = await res.text();
    let body = {};
    try {
      body = JSON.parse(text);
    } catch {}
    throw responseError(body, text || res.statusText, res.status);
  }

  if (!res.body) throw new Error("스트림 응답 본문이 없습니다.");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminalCount = 0;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();

      for (const chunk of chunks) {
        terminalCount = dispatchSseChunk(chunk, terminalCount, onEvent);
      }
    }
    if (buffer.trim()) terminalCount = dispatchSseChunk(buffer, terminalCount, onEvent);
    if (terminalCount !== 1) throw new Error(terminalCount ? "스트림 terminal 이벤트가 중복되었습니다." : "스트림이 완료 이벤트 없이 종료되었습니다.");
  } finally {
    if (terminalCount !== 1) await reader.cancel().catch(() => {});
  }
}

function dispatchSseChunk(chunk, terminalCount, onEvent) {
  const lines = chunk.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event: "));
  const name = eventLine ? eventLine.slice(7) : "message";
  const dataLines = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart());
  if (!dataLines.length) return terminalCount;
  if (terminalCount) throw new Error("스트림 terminal 이벤트 이후 데이터가 도착했습니다.");
  const nextTerminalCount = terminalCount + (name === "done" || name === "error" ? 1 : 0);
  if (nextTerminalCount > 1) throw new Error("스트림 terminal 이벤트가 중복되었습니다.");
  onEvent(name, JSON.parse(dataLines.join("\n")));
  return nextTerminalCount;
}

function errorMessage(body, fallback) {
  if (body.message || body.error || body.detail) return body.message || body.error || body.detail;
  return fallback;
}

function responseError(body, fallback, status) {
  const error = new Error(errorMessage(body, fallback));
  error.code = body.code || body.error || null;
  error.provider = body.provider || null;
  error.phase = body.phase || null;
  error.retryable = body.retryable === true;
  error.status = status;
  return error;
}

export function sseError(body) {
  return responseError(body, body.message || body.error || "스트림 처리에 실패했습니다.", null);
}
