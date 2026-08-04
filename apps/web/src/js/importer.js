import { activeConversation } from "./actions.js";
import { api } from "./api.js";
import { plotCharacters } from "./catalog.js";
import { loadMessages } from "./chat.js";
import { $, confirmDestructive, confirmDialog, el, parseJson, setChildren, toast } from "./dom.js";
import { state } from "./state.js";

let selection = null;
let session = null;
let uploading = false;

export function bindZetaImport() {
  $("openZetaImportBtn").onclick = openImport;
  $("chooseZetaImportFilesBtn").onclick = () => $("zetaImportFiles").click();
  $("zetaImportFiles").onchange = readSelectedFiles;
  $("commitZetaImportBtn").onclick = uploadSelection;
  $("closeZetaImportBtn").onclick = cancelImport;
  $("zetaImportDialog").onpointerdown = (event) => {
    if (event.target === $("zetaImportDialog") && !uploading) closeImport();
  };
}

async function openImport() {
  const conv = activeConversation();
  if (!conv?.userProfileId || !isEmptyConversation(conv.id)) {
    toast("유저 프로필을 선택한 비어 있는 대화에서만 불러올 수 있습니다.");
    return;
  }
  $("settingsSheet").classList.remove("open");
  resetDialog();
  $("zetaImportDialog").classList.add("open");
  try {
    session = await api(`/api/conversations/${encodeURIComponent(conv.id)}/session`);
  } catch (err) {
    if (err.status !== 404) {
      setStatus(`세션 확인 실패: ${err.message}`);
      return;
    }
  }
  if (session?.state === "committing") {
    setStatus("서버에서 이전 불러오기를 마무리하고 있습니다.");
    return;
  }
  if (session) {
    const resume = await confirmDialog("완료되지 않은 불러오기 세션이 있습니다. 이어하려면 확인, 폐기하고 새로 시작하려면 폐기를 누르세요.", {
      title: "불러오기 이어하기",
      okText: "이어하기",
      cancelText: "폐기",
    });
    if (!resume) {
      const discard = await confirmDestructive("기존 불러오기 세션을 폐기하고 새로 시작할까요?", {
        title: "세션 폐기",
        okText: "폐기",
      });
      if (!discard) {
        closeImport();
        return;
      }
      await api(importSessionPath(conv.id, session.sessionId), { method: "DELETE" });
      session = null;
    }
  }
  setStatus(session ? `기존 세션을 이어갑니다. 파일을 다시 선택하세요. (${session.receivedParts.length}/${session.expectedParts}파트 수신)` : "제타 JSON 파일을 선택하세요.");
  $("zetaImportFiles").click();
}

function isEmptyConversation(conversationId) {
  const introPrefix = `intro_${conversationId}_`;
  return state.activeMessages.list.every((message) => !message.turn_id && String(message.id || "").startsWith(introPrefix));
}

async function readSelectedFiles() {
  const files = [...$("zetaImportFiles").files];
  if (!files.length) return;
  try {
    selection = await parseFiles(files);
    if (session && (
      session.roomId !== selection.roomId
      || session.expectedParts !== selection.parts.length
      || session.expectedMessages !== selection.messageCount
    )) throw new Error("선택한 파일이 진행 중인 세션과 일치하지 않습니다.");
    renderPreview(selection);
    setPhase("ready");
    $("chooseZetaImportFilesBtn").textContent = "파일 바꾸기";
    $("commitZetaImportBtn").disabled = false;
    $("commitZetaImportBtn").textContent = session ? "이어서 불러오기" : "대화 불러오기";
    setStatus("가져올 준비가 끝났어요");
  } catch (err) {
    selection = null;
    setPhase("error");
    $("commitZetaImportBtn").disabled = true;
    renderEmptyState("파일을 다시 확인해 주세요", "JSON 형식과 파트 구성이 맞는지 확인한 뒤 다시 선택해 주세요.");
    setStatus(err.message);
  } finally {
    $("zetaImportFiles").value = "";
  }
}

async function parseFiles(files) {
  if (files.some((file) => file.name.toLowerCase().endsWith(".txt"))) {
    throw new Error("TXT export는 지원하지 않습니다. 제타 JSON export를 선택하세요.");
  }
  const parsed = await Promise.all(files.map(async (file) => {
    if (!file.name.toLowerCase().endsWith(".json")) throw new Error(`${file.name}: JSON 파일이 아닙니다.`);
    let value;
    try {
      value = JSON.parse((await file.text()).replace(/^﻿/, ""));
    } catch {
      throw new Error(`${file.name}: JSON을 읽을 수 없습니다.`);
    }
    return { file, value };
  }));
  const manifests = parsed.filter(({ file, value }) => /_manifest\.json$/i.test(file.name) || (!Array.isArray(value?.messages) && Array.isArray(value?.parts)));
  if (manifests.length > 1) throw new Error("매니페스트는 하나만 선택할 수 있습니다.");
  const manifest = manifests[0]?.value || null;
  const partFiles = parsed.filter((item) => item !== manifests[0]);
  if (!partFiles.length || partFiles.some(({ value }) => !Array.isArray(value?.messages))) {
    throw new Error("각 파트는 messages 배열을 가진 JSON이어야 합니다.");
  }
  const ordered = orderParts(partFiles, manifest);
  validateManifest(ordered, manifest);
  const messages = ordered.flatMap(({ value }) => value.messages);
  if (manifest?.format && String(manifest.format).toLowerCase() !== "json") {
    throw new Error("TXT export는 지원하지 않습니다. JSON 매니페스트를 선택하세요.");
  }
  if (manifest?.totalMessages !== undefined && manifest.totalMessages !== messages.length) {
    throw new Error("매니페스트의 총 메시지 수와 선택한 파일이 다릅니다.");
  }
  const roomIds = new Set(messages.map((message) => message?.roomId).filter((id) => typeof id === "string" && id));
  if (roomIds.size !== 1 || messages.some((message) => !message || !roomIds.has(message.roomId))) {
    throw new Error("모든 메시지의 roomId가 하나로 일치해야 합니다.");
  }
  if (manifest?.roomId !== undefined && manifest.roomId !== [...roomIds][0]) {
    throw new Error("매니페스트와 메시지의 roomId가 다릅니다.");
  }
  const times = messages.map((message) => message.messageTime).filter((value) => typeof value === "string").sort();
  const speakers = [...new Set(messages.flatMap((message) => Array.isArray(message.contents)
    ? message.contents.filter((block) => block?.type === "TEXT" && typeof block.speakerName === "string").map((block) => block.speakerName)
    : []))].sort((a, b) => a.localeCompare(b, "ko"));
  return {
    manifest,
    parts: ordered.map(({ value }) => value),
    roomId: [...roomIds][0],
    messageCount: messages.length,
    firstTime: times[0] || "확인 불가",
    lastTime: times.at(-1) || "확인 불가",
    speakers,
    warning: !manifest && ordered.length > 1 ? "매니페스트 없이 분할 파일을 불러옵니다." : "",
  };
}

function orderParts(parts, manifest) {
  const byName = new Map(parts.map((item) => [item.file.name, item]));
  if (Array.isArray(manifest?.parts)) {
    const ordered = manifest.parts.map((part, index) => {
      const name = part.fileName || part.filename || part.name;
      if (name && !byName.has(name)) throw new Error(`누락된 파트: ${name}`);
      return name ? byName.get(name) : parts.find((item) => partNumber(item.file.name) === manifestPartNumber(part, index + 1));
    });
    if (ordered.some((item) => !item) || ordered.length !== parts.length) throw new Error("매니페스트와 선택한 파트 구성이 일치하지 않습니다.");
    return ordered;
  }
  if (parts.length === 1) return parts;
  if (parts.some(({ file }) => partNumber(file.name) === null)) throw new Error("분할 파일명에 part-NNN 번호가 필요합니다.");
  const ordered = [...parts].sort((a, b) => partNumber(a.file.name) - partNumber(b.file.name));
  const numbers = ordered.map(({ file }) => partNumber(file.name));
  if (new Set(numbers).size !== numbers.length) throw new Error("같은 파트 번호의 파일이 중복되었습니다.");
  return ordered;
}

function partNumber(name) {
  const match = name.match(/part-(\d+)/i);
  return match ? Number(match[1]) : null;
}

function manifestPartNumber(part, fallback) {
  return part.partNumber ?? part.partNo ?? part.part ?? partNumber(part.fileName || part.filename || part.name || "") ?? fallback;
}

function validateManifest(parts, manifest) {
  if (!manifest) return;
  if (Array.isArray(manifest.parts) && manifest.parts.length !== parts.length) throw new Error("매니페스트의 파트 수와 선택한 파일 수가 다릅니다.");
  parts.forEach(({ value }, index) => {
    const expected = manifest.parts?.[index];
    if (!expected) return;
    const messages = value.messages;
    if (expected.messageCount !== undefined && expected.messageCount !== messages.length) throw new Error(`${index + 1}번 파트의 메시지 수가 매니페스트와 다릅니다.`);
    if (expected.firstMessageId !== undefined && expected.firstMessageId !== messages[0]?.id) throw new Error(`${index + 1}번 파트의 첫 메시지가 매니페스트와 다릅니다.`);
    if (expected.lastMessageId !== undefined && expected.lastMessageId !== messages.at(-1)?.id) throw new Error(`${index + 1}번 파트의 마지막 메시지가 매니페스트와 다릅니다.`);
  });
}

function renderPreview(data) {
  const matches = currentSpeakerMatches();
  const speakers = data.speakers.map((name) => {
    const normalized = normalizeName(name);
    const match = matches.characterNames.has(normalized)
      ? "캐릭터 일치"
      : matches.userNames.has(normalized) ? "유저 프로필 일치" : "일치 없음";
    return { name, match };
  });
  const matched = speakers.filter((speaker) => speaker.match !== "일치 없음");
  const others = speakers.filter((speaker) => speaker.match === "일치 없음");
  setChildren($("zetaImportPreview"), [
    el("section", { className: "zeta-import-overview" }, [
      el("div", { className: "zeta-import-stat zeta-import-stat-primary" }, [
        el("strong", { text: data.messageCount.toLocaleString() }),
        el("span", { text: "메시지" }),
      ]),
      el("div", { className: "zeta-import-stat" }, [
        el("strong", { text: String(data.parts.length) }),
        el("span", { text: "파일 파트" }),
      ]),
      el("div", { className: "zeta-import-stat" }, [
        el("strong", { text: String(data.speakers.length) }),
        el("span", { text: "감지된 화자" }),
      ]),
    ]),
    el("section", { className: "zeta-import-period" }, [
      el("span", { className: "zeta-import-section-label", text: "대화 기간" }),
      el("strong", { text: formatPeriod(data.firstTime, data.lastTime) }),
    ]),
    data.warning ? el("div", { className: "zeta-import-notice", text: data.warning }) : null,
    el("section", { className: "zeta-import-identities" }, [
      el("div", { className: "zeta-import-section-head" }, [
        el("div", {}, [
          el("span", { className: "zeta-import-section-label", text: "이름 매칭" }),
          el("strong", { text: matched.length ? `${matched.length}명 연결됨` : "연결된 화자 없음" }),
        ]),
        el("span", { className: `zeta-import-match-count${matched.length ? " is-ok" : ""}`, text: `${matched.length}/${data.speakers.length}` }),
      ]),
      matched.length ? el("div", { className: "zeta-import-speaker-summary" }, matched.map((speaker) => speakerMatchCard(speaker)))
        : el("span", { className: "meta", text: "이름이 일치하지 않아도 원본 화자명은 그대로 보존돼요." }),
    ]),
    others.length ? el("details", { className: "zeta-import-other-speakers" }, [
      el("summary", {}, [
        el("span", { text: `기타 화자 ${others.length}명` }),
        el("span", { className: "meta", text: "원본 이름으로 보존" }),
      ]),
      el("div", { className: "zeta-import-other-list" }, others.map((speaker) => el("span", { text: speaker.name }))),
    ]) : null,
  ]);
}

function renderEmptyState(title = "제타 export를 선택하세요", description = "단일 JSON 또는 분할 part 파일과 manifest를 한 번에 선택할 수 있어요.") {
  setChildren($("zetaImportPreview"), [
    el("section", { className: "zeta-import-empty" }, [
      el("span", { className: "zeta-import-empty-mark", text: "JSON" }),
      el("strong", { text: title }),
      el("span", { className: "meta", text: description }),
    ]),
  ]);
}

function speakerMatchCard(speaker) {
  const role = speaker.match === "캐릭터 일치" ? "캐릭터" : "나";
  return el("div", { className: "zeta-import-speaker-card" }, [
    el("span", { className: "zeta-import-speaker-avatar", text: speaker.name.slice(0, 1) || "?" }),
    el("div", { className: "zeta-import-speaker-copy" }, [
      el("strong", { text: speaker.name }),
      el("span", { text: speaker.match }),
    ]),
    el("span", { className: "zeta-import-role-chip", text: role }),
  ]);
}

function formatPeriod(first, last) {
  const start = formatImportDate(first);
  const end = formatImportDate(last);
  return start === end ? start : `${start} ~ ${end}`;
}

function formatImportDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "short", day: "numeric" }).format(date);
}

function currentSpeakerMatches() {
  const conv = activeConversation();
  const plot = state.catalog.plots.byId.get(conv?.plotId);
  const user = state.catalog.users.byId.get(conv?.userProfileId);
  const characters = plotCharacters(plot);
  const characterNames = new Set(
    characters.flatMap((character) => [
      character?.id,
      character?.name,
      parseJson(character?.profile_json).name,
      parseJson(character?.profile_json).displayName,
      parseJson(character?.profile_json).display_name,
    ]).filter(Boolean).map(normalizeName),
  );
  const userNames = new Set([user?.id, user?.name].filter(Boolean).map(normalizeName));
  try {
    const profile = JSON.parse(user?.profile_json || "{}");
    [profile.name, profile.displayName, profile.display_name].filter(Boolean).forEach((name) => userNames.add(normalizeName(name)));
  } catch {}
  return { characterNames, userNames };
}

function normalizeName(name) {
  return String(name || "").trim().toLowerCase();
}

async function uploadSelection() {
  if (!selection || uploading) return;
  const conv = activeConversation();
  if (!conv) return;
  uploading = true;
  setPhase("uploading");
  setControlsDisabled(true);
  try {
    if (!session) {
      session = await api(`/api/conversations/${encodeURIComponent(conv.id)}/sessions`, {
        method: "POST",
        body: JSON.stringify({
          roomId: selection.roomId,
          expectedParts: selection.parts.length,
          expectedMessages: selection.messageCount,
          manifest: selection.manifest,
        }),
      });
    }
    const received = new Set(session.receivedParts || []);
    for (let index = 0; index < selection.parts.length; index += 1) {
      const _partNumber = index + 1;
      if (!received.has(_partNumber)) {
        setStatus(`${_partNumber}/${selection.parts.length} 파트 업로드 중…`);
        session = await api(`${importSessionPath(conv.id, session.sessionId)}/parts/${_partNumber}`, {
          method: "PUT",
          body: JSON.stringify(selection.parts[index]),
        });
      }
      updateProgress(_partNumber, selection.parts.length);
    }
    setStatus("대화에 반영하는 중…");
    const result = await api(`${importSessionPath(conv.id, session.sessionId)}/commit`, { method: "POST" });
    session = null;
    await loadMessages();
    setPhase("done");
    setStatus("대화를 성공적으로 가져왔어요");
    setChildren($("zetaImportPreview"), (result.warnings || []).length
      ? [el("section", { className: "zeta-import-result" }, [
        el("span", { className: "zeta-import-result-mark", text: "✓" }),
        el("strong", { text: `${result.messageCount.toLocaleString()}개 메시지 완료` }),
        el("span", { className: "meta", text: `${result.turnCount.toLocaleString()}개 turn · 경고 ${result.warnings.length}건` }),
        el("details", { className: "zeta-import-other-speakers" }, [
          el("summary", { text: "경고 확인" }),
          el("div", { className: "zeta-import-warning-list" }, result.warnings.map((warning) => el("span", { text: warning }))),
        ]),
      ])]
      : [el("section", { className: "zeta-import-result" }, [
        el("span", { className: "zeta-import-result-mark", text: "✓" }),
        el("strong", { text: `${result.messageCount.toLocaleString()}개 메시지 완료` }),
        el("span", { className: "meta", text: `${result.turnCount.toLocaleString()}개 turn · 경고 없이 깔끔하게 가져왔어요` }),
      ])]);
    $("commitZetaImportBtn").disabled = true;
    $("chooseZetaImportFilesBtn").disabled = true;
    $("chooseZetaImportFilesBtn").hidden = true;
    $("commitZetaImportBtn").hidden = true;
  } catch (err) {
    setPhase("error");
    setStatus(`불러오기 실패: ${err.message}`);
    $("commitZetaImportBtn").textContent = "다시 시도";
  } finally {
    uploading = false;
    if (session) setControlsDisabled(false);
  }
}

async function cancelImport() {
  if (uploading || session) {
    const discard = await confirmDestructive("업로드한 파트를 폐기할까요?", { okText: "폐기" });
    if (!discard) return;
    if (session) {
      try {
        await api(importSessionPath(activeConversation().id, session.sessionId), { method: "DELETE" });
      } catch (err) {
        if (err.status !== 404) {
          setStatus(`세션 폐기 실패: ${err.message}`);
          return;
        }
      }
    }
  }
  closeImport();
}

function importSessionPath(conversationId, sessionId) {
  return `/api/conversations/${encodeURIComponent(conversationId)}/sessions/${encodeURIComponent(sessionId)}`;
}

function resetDialog() {
  selection = null;
  session = null;
  uploading = false;
  renderEmptyState();
  setStatus("단일 파일과 분할 export를 모두 지원해요");
  updateProgress(0, 1);
  $("chooseZetaImportFilesBtn").disabled = false;
  $("commitZetaImportBtn").disabled = true;
  $("commitZetaImportBtn").textContent = "대화 불러오기";
  $("chooseZetaImportFilesBtn").hidden = false;
  $("chooseZetaImportFilesBtn").textContent = "JSON 파일 선택";
  $("commitZetaImportBtn").hidden = false;
  setPhase("idle");
}

function setControlsDisabled(disabled) {
  $("chooseZetaImportFilesBtn").disabled = disabled;
  $("commitZetaImportBtn").disabled = disabled;
}

function updateProgress(value, max) {
  $("zetaImportProgress").max = max;
  $("zetaImportProgress").value = value;
}

function setStatus(message) {
  $("zetaImportStatus").textContent = message;
}

function setPhase(phase) {
  $("zetaImportPanel").dataset.phase = phase;
}

function closeImport() {
  $("zetaImportDialog").classList.remove("open");
  resetDialog();
}
