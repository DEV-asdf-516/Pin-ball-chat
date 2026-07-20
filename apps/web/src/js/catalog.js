import { api, apiBase, uploadFile } from "./api.js";
import { keys } from "./config.js";
import { $, el, parseJson, setChildren } from "./dom.js";
import { loadCursorPage } from "./paging.js";
import { notify, state } from "./state.js";

const catalogConfig = {
  plots: { path: "/api/plots", key: "plots" },
  chars: { path: "/api/characters", key: "characters" },
  users: { path: "/api/user-profiles", key: "user_profiles" },
};

export async function loadCatalog() {
  $("apiStatus").textContent = "API 확인 중...";
  try {
    const [health] = await Promise.all([
      api("/api/health"),
    ]);
    await Promise.all([
      loadCatalogKind("plots", true),
      loadCatalogKind("chars", true),
      loadCatalogKind("users", true),
    ]);
    $("apiStatus").textContent = health.ok ? `${catalogItems("plots").length}개 plot 로드됨` : "API 상태 확인 실패";
    renderPlots();
  } catch (err) {
    $("apiStatus").textContent = "로컬 API에 연결하지 못했습니다.";
    setChildren($("plotList"), [el("div", { className: "empty", text: err.message })]);
  }
}

export async function loadCatalogKind(kind, reset = false) {
  const config = catalogConfig[kind];
  const pageState = state.catalog[kind]?.page;
  if (!config) return [];
  return loadCursorPage(pageState, {
    path: config.path,
    itemKey: config.key,
    reset,
    apply: (items, append) => {
      writeCatalogItems(kind, items, append);
      if (kind === "plots") {
        $("apiStatus").textContent = `${catalogItems("plots").length}개 plot 로드됨${pageState.hasMore ? " · 더 있음" : ""}`;
        renderPlots();
      }
    },
  });
}

export async function loadMorePlots() {
  await loadCatalogKind("plots");
}

export async function createPlot(data) {
  const plot = await api("/api/plots", {
    method: "POST",
    body: JSON.stringify(data),
  });
  await loadCatalogKind("plots", true);
  return plot;
}

export async function createCharacter(data) {
  const character = await api("/api/characters", {
    method: "POST",
    body: JSON.stringify(data),
  });
  upsertCatalogItem("chars", character);
  return character;
}

export async function loadCharacter(id) {
  if (!id) return null;
  const character = await api(`/api/characters/${encodeURIComponent(id)}`);
  upsertCatalogItem("chars", character);
  return character;
}

export async function updateCharacter(id, data) {
  const character = await api(`/api/characters/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  upsertCatalogItem("chars", character);
  return character;
}

export async function uploadCharacterAvatar(id, file) {
  const character = await uploadFile(`/api/uploads/character/${encodeURIComponent(id)}`, file);
  upsertCatalogItem("chars", character);
  return character;
}

export async function updatePlot(id, data) {
  const plot = await api(`/api/plots/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  await loadCatalogKind("plots", true);
  return plot;
}

export async function deletePlot(id) {
  const result = await api(`/api/plots/${encodeURIComponent(id)}`, { method: "DELETE" });
  state.catalog.plots.byId.delete(id);
  state.catalog.plots.order = state.catalog.plots.order.filter((plotId) => plotId !== id);
  notify("catalog.plots");
  renderPlots();
  return result;
}

export function findPlot(id) {
  return state.catalog.plots.byId.get(id) || null;
}

export function renderPlots() {
  const q = $("searchInput").value.trim().toLowerCase();
  const recent = parseJson(localStorage.getItem(keys.recent));
  const plots = catalogItems("plots")
    .filter((plot) => !q || plotHaystack(plot).includes(q))
    .sort((a, b) => (recent[b.id] || 0) - (recent[a.id] || 0) || a.id.localeCompare(b.id));
  setChildren($("plotList"), plots.length ? plots.map(plotCard) : [el("div", { className: "empty", text: "로드된 플롯이 없습니다." })]);
}

export async function openPlot(plotId, userProfileId = null, fallback = null) {
  state.selectedPlot = findPlot(plotId) || fallback;
  state.selectedUserProfileId = userProfileId || null;
  if (!state.selectedPlot) return;
  renderDetail();
  await ensureSelectedPlotCharacter();
  renderDetail();
}

function plotGenre(plot) {
  return parseJson(plot.plot_json).genre || [];
}

function plotHaystack(plot) {
  const char = state.catalog.chars.byId.get(plot.character_id);
  const genre = plotGenre(plot).join(" ");
  const source = plot.source_text || "";
  return [plot.title, plot.id, char?.name, char?.id, genre, source].filter(Boolean).join(" ").toLowerCase();
}

function plotCard(plot) {
  const char = state.catalog.chars.byId.get(plot.character_id);
  const genres = plotGenre(plot);
  return el("button", { className: "card plot-card", dataset: { plot: plot.id } }, [
    el("div", { className: "plot-card-media" }, [
      characterAvatar(char, "plot-card-image"),
    ]),
    el("div", { className: `plot-card-content${genres.length ? " has-tags" : ""}` }, [
      el("h2", { text: plot.title || "제목 없는 플롯" }),
      el("div", { className: "meta", text: characterName(char) || "캐릭터" }),
      el("div", { className: "tags" }, genres.map((g) => el("span", { className: "tag", text: g }))),
      el("div", { className: "preview", text: sourcePreview(plot.source_text) }),
    ]),
  ]);
}

function renderDetail() {
  const plot = state.selectedPlot;
  const char = state.catalog.chars.byId.get(plot.character_id);
  setChildren($("plotDetail"), [
    el("section", {}, [
      el("h2", { text: plot.title || "제목 없는 플롯" }),
      el("div", { className: "tags" }, plotGenre(plot).map((g) => el("span", { className: "tag", text: g }))),
    ]),
    el("section", {}, [
      el("h3", { text: "캐릭터 정보" }),
      el("div", { className: "card detail-character-card" }, [
        characterAvatar(char, "detail-character-image"),
        el("div", { className: "detail-character-summary" }, [
          el("div", {}, [
            el("strong", { text: characterName(char) || "캐릭터" }),
            el("div", { className: "meta", text: char ? "플롯 캐릭터" : "캐릭터 정보를 불러오는 중..." }),
          ]),
        ]),
        el("div", { className: "source character-source", text: char?.source_text || "캐릭터 정보를 찾지 못했습니다." }),
      ]),
    ]),
    el("section", { className: "plot-source-section" }, [
      el("h3", { text: "플롯 내용" }),
      el("div", { className: "source plot-source", text: plot.source_text || "" }),
    ]),
  ]);
}

async function ensureSelectedPlotCharacter() {
  const characterId = state.selectedPlot?.character_id;
  if (!characterId || state.catalog.chars.byId.has(characterId)) return;
  try {
    await loadCharacter(characterId);
  } catch {
    // 상세 화면에서는 플롯 자체를 막지 않고, 캐릭터 ID fallback만 보여준다.
  }
}

function writeCatalogItems(kind, items, append) {
  const bucket = state.catalog[kind];
  if (!bucket) return;
  if (!append) {
    bucket.byId = new Map();
    bucket.order = [];
  }
  for (const item of items) upsertCatalogItem(kind, item, false);
  notify(`catalog.${kind}`);
}

function upsertCatalogItem(kind, item, notifyChange = true) {
  const bucket = state.catalog[kind];
  if (!bucket || !item?.id) return;
  bucket.byId.set(item.id, item);
  if (!bucket.order.includes(item.id)) bucket.order.push(item.id);
  if (notifyChange) notify(`catalog.${kind}`);
}

function catalogItems(kind) {
  const bucket = state.catalog[kind];
  return bucket ? bucket.order.map((id) => bucket.byId.get(id)).filter(Boolean) : [];
}

function sourcePreview(source) {
  return String(source || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !isPreviewNoise(line))
    .slice(0, 2)
    .join("\n");
}

function characterName(char) {
  if (!char) return "";
  const profile = parseJson(char.profile_json);
  return profile.displayName || profile.display_name || char.name || profile.name || "";
}

function characterAvatar(char, className = "avatar-preview small") {
  const src = safeImageUrl(parseJson(char?.profile_json).avatarUrl);
  if (!src) return el("div", { className, text: characterInitial(char) });
  return el("img", { className, attrs: { src, alt: "" } });
}

function characterInitial(char) {
  return (characterName(char) || "?").trim().slice(0, 1) || "?";
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

function isPreviewNoise(line) {
  return line.startsWith("#")
    || line.startsWith("```")
    || /^[-*_]{3,}$/.test(line)
    || /^[.…]+$/.test(line);
}
