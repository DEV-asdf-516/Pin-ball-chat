import { keys } from "./config.js";

export function apiBase() {
  return localStorage.getItem(keys.apiBase) || (location.port === "8080" ? location.origin : "http://localhost:8080");
}

export async function api(path, options = {}) {
  const res = await fetch(apiBase() + path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let body = {};
    try {
      body = await res.json();
    } catch {}
    throw new Error(errorMessage(body, res.statusText));
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
    throw new Error(errorMessage(body, res.statusText));
  }
  return res.json();
}

export async function streamSse(path, body, onEvent) {
  const res = await fetch(apiBase() + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    let body = {};
    try {
      body = JSON.parse(text);
    } catch {}
    throw new Error(errorMessage(body, text || res.statusText));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop();

    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      const dataLine = lines.find((line) => line.startsWith("data: "));
      const eventLine = lines.find((line) => line.startsWith("event: "));
      if (eventLine) eventName = eventLine.slice(7);
      if (dataLine) onEvent(eventName, JSON.parse(dataLine.slice(6)));
    }
  }
}

function errorMessage(body, fallback) {
  if (body.message || body.error || body.detail) return body.message || body.error || body.detail;
  return fallback;
}
