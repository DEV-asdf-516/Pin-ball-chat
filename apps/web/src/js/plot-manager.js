import { deletePlot, findPlot, loadCharacter, loadMorePlots, updateCharacter, updatePlot } from "./catalog.js";
import { $, confirmDialog, el, parseJson, setChildren, toast } from "./dom.js";
import { activateFormTab, bindFormTabs } from "./form-tabs.js";
import { bindGenrePicker, renderGenrePicker, selectedGenres } from "./genres.js";
import { bindIntroEditor, introValue, renderIntroEditor } from "./intro-editor.js";
import { state } from "./state.js";

export function bindPlotManager() {
  bindFormTabs("plotManageEditMount");
  $("plotManageSearchInput").oninput = renderPlotManager;
  $("plotManageMoreBtn").onclick = async () => {
    await loadMorePlots();
    renderPlotManager();
  };
  $("plotManageList").onclick = async (event) => {
    const item = event.target.closest("[data-manage-plot]");
    if (!item) return;
    await selectManagePlot(item.dataset.managePlot);
  };
  $("plotManageEditMount").onsubmit = async (event) => {
    if (event.target.id !== "plotManageForm") return;
    event.preventDefault();
    await saveManagedPlot();
  };
  $("plotManageEditMount").onclick = async (event) => {
    if (!event.target.closest("#deletePlotBtn")) return;
    await deleteManagedPlot();
  };
}

export function openPlotManager() {
  state.managedPlotId = null;
  showPlotManageList();
  renderPlotManager();
}

export function closePlotManagerEdit() {
  if (!$("plotManageEditMount").childElementCount) return false;
  showPlotManageList();
  return true;
}

function renderPlotManager() {
  const query = $("plotManageSearchInput").value.trim().toLowerCase();
  const allPlots = plotList();
  const plots = allPlots.filter((plot) => !query || plotText(plot).includes(query));
  $("plotManageStatus").textContent = `${allPlots.length}개 plot${state.catalog.plots.page.hasMore ? " · 더 있음" : ""}`;
  $("plotManageMoreBtn").hidden = !state.catalog.plots.page.hasMore;
  setChildren(
    $("plotManageList"),
    plots.length ? plots.map(plotRow) : [el("div", { className: "empty", text: "플롯이 없습니다." })],
  );
}

function plotRow(plot) {
  return el("button", { type: "button", className: "plot-manage-row", dataset: { managePlot: plot.id } }, [
    plotThumb(plot),
    el("div", { className: "plot-manage-info" }, [
      el("strong", { text: plotTitle(plot) }),
      el("span", { className: "meta", text: plotMeta(plot) }),
    ]),
    el("span", { className: "plot-manage-edit-icon", text: "✎" }),
  ]);
}

export async function openManagedPlot(id) {
  await selectManagePlot(id);
}

async function selectManagePlot(id) {
  state.managedPlotId = id;
  const plot = findPlot(id);
  if (plot?.character_id && !state.catalog.chars.byId.has(plot.character_id)) {
    try {
      await loadCharacter(plot.character_id);
    } catch {}
  }
  showPlotManageEdit();
}

function showPlotManageList() {
  $("plotManageToolbar").hidden = false;
  $("plotManageListView").hidden = false;
  setChildren($("plotManageEditMount"), []);
  state.managedPlotId = null;
}

function showPlotManageEdit() {
  $("plotManageToolbar").hidden = true;
  $("plotManageListView").hidden = true;
  renderPlotEditForm(state.managedPlotId);
}

async function saveManagedPlot() {
  const id = state.managedPlotId;
  if (!id) {
    toast("수정할 플롯을 선택하세요");
    return;
  }
  try {
    const currentPlot = findPlot(id);
    const charId = currentPlot?.character_id || "";
    const characterName = $("plotManageCharacterName").value.trim();
    const characterSource = $("plotManageCharacterSource").value.trim();
    if (!characterName || !characterSource) {
      toast("캐릭터 정보를 입력하세요");
      return;
    }
    if (charId) {
      await updateCharacter(charId, {
        type: "character",
        name: characterName,
        displayName: characterName,
        avatarUrl: getManagedAvatarUrl(),
        sourceText: characterSource,
      });
    }
    const intro = introValue("plotManageIntroEditor");
    const plot = await updatePlot(id, {
      type: "plot",
      title: $("plotManageTitle").value.trim(),
      characterId: charId || state.catalog.chars.byId.values().next().value?.id || "",
      genre: selectedGenres("plotManageGenreList"),
      sourceText: $("plotManageSource").value,
      ...(intro ? { intro } : {}),
    });
    state.managedPlotId = plot.id;
    renderPlotManager();
    showPlotManageList();
    toast("저장 완료");
  } catch (err) {
    toast(err.message);
  }
}

async function deleteManagedPlot() {
  const id = state.managedPlotId;
  const plot = findPlot(id);
  if (!id || !(await confirmDialog(`${plotTitle(plot)} 플롯을 삭제할까요?`, { danger: true }))) return;
  try {
    await deletePlot(id);
    state.managedPlotId = null;
    renderPlotManager();
    showPlotManageList();
    toast("삭제 완료");
  } catch (err) {
    toast(err.message);
  }
}

function plotText(plot) {
  const raw = parseJson(plot.plot_json);
  return [plot.id, plot.title, plot.character_id, plot.source_text, ...(raw.genre || [])].filter(Boolean).join(" ").toLowerCase();
}

function renderPlotEditForm(id) {
  const plot = findPlot(id);
  const plotData = parseJson(plot?.plot_json);
  const char = state.catalog.chars.byId.get(plot?.character_id);
  setChildren($("plotManageEditMount"), [
    el("form", { id: "plotManageForm", className: "form-page plot-manage-edit" }, [
      formTabs("prompt"),
      el("div", { dataset: { formPanel: "prompt" } }, [
        el("section", { className: "form-card plot-manage-main-card" }, [
          el("h2", { text: "플롯" }),
          field("plotManageTitle", "제목", el("input", { id: "plotManageTitle", value: plot?.title || "", attrs: { autocomplete: "off", maxlength: "40", placeholder: "" } })),
          field("plotManageSource", "내용", el("textarea", { id: "plotManageSource", text: plot?.source_text || "", attrs: { rows: "10", placeholder: "" } })),
          field("plotManageGenreList", "장르", el("div", { id: "plotManageGenreList", className: "genre-picker" })),
        ]),
        el("section", { className: "form-card" }, [
          el("h2", { text: "캐릭터" }),
          el("div", { className: "avatar-field" }, [
            el("label", {
              id: "plotManageAvatarPreview",
              className: "avatar-preview avatar-upload-target",
              text: "+",
              attrs: { for: "plotManageCharacterAvatarFile" },
            }),
            el("input", { id: "plotManageCharacterAvatarFile", className: "file-input", type: "file", attrs: { accept: "image/*" } }),
          ]),
          field("plotManageCharacterName", "캐릭터 명", el("input", { id: "plotManageCharacterName", value: characterName(char), attrs: { autocomplete: "off", maxlength: "40", placeholder: "" } })),
          field("plotManageCharacterSource", "캐릭터 설명", el("textarea", { id: "plotManageCharacterSource", text: char?.source_text || "", attrs: { rows: "8", placeholder: "" } })),
        ]),
      ]),
      el("div", { dataset: { formPanel: "intro" }, attrs: { hidden: "" } }, [
        el("section", { className: "form-card" }, [
          el("h2", { text: "인트로" }),
          el("div", { id: "plotManageIntroEditor", className: "intro-editor" }),
        ]),
      ]),
      el("div", { className: "form-actions" }, [
        el("button", { id: "deletePlotBtn", className: "danger", type: "button", text: "삭제" }),
        el("button", { className: "primary", type: "submit", text: "저장" }),
      ]),
    ]),
  ]);
  $("plotManageSource").value = plot?.source_text || "";
  $("plotManageCharacterSource").value = char?.source_text || "";
  $("plotManageAvatarPreview").dataset.avatarUrl = existingAvatarUrl(char);
  $("plotManageCharacterAvatarFile").onchange = readManagedAvatarFile;
  renderManagedAvatarPreview();
  renderGenrePicker("plotManageGenreList", plotData.genre || []);
  bindGenrePicker("plotManageGenreList");
  renderIntroEditor("plotManageIntroEditor", plotData.intro);
  bindIntroEditor("plotManageIntroEditor");
  activateFormTab("plotManageEditMount", "prompt");
}

function formTabs(active) {
  return el("div", { className: "form-tabs" }, [
    tabButton("prompt", "프롬프트", active),
    tabButton("intro", "인트로", active),
  ]);
}

function tabButton(value, label, active) {
  return el("button", {
    type: "button",
    className: value === active ? "active" : "",
    text: label,
    dataset: { formTab: value },
  });
}

function field(inputId, label, control) {
  return el("div", { className: "field" }, [
    el("label", { text: label, attrs: { for: inputId } }),
    control,
  ]);
}

function plotThumb(plot) {
  const char = state.catalog.chars.byId.get(plot.character_id);
  const src = safeImageUrl(parseJson(char?.profile_json).avatarUrl);
  if (src) return el("img", { className: "plot-manage-thumb", attrs: { src, alt: "" } });
  return el("div", { className: "plot-manage-thumb", text: (char?.name || plotTitle(plot) || "?").trim().slice(0, 1) });
}

function plotTitle(plot) {
  return plot?.title || "제목 없는 플롯";
}

function plotMeta(plot) {
  const char = state.catalog.chars.byId.get(plot.character_id);
  const genres = parseJson(plot.plot_json).genre || [];
  return [characterName(char), ...genres].filter(Boolean).join(" · ") || "플롯";
}

function plotList() {
  const bucket = state.catalog.plots;
  return bucket.order.map((id) => bucket.byId.get(id)).filter(Boolean);
}

function characterName(char) {
  if (!char) return "";
  const profile = parseJson(char.profile_json);
  return profile.displayName || profile.display_name || char.name || profile.name || "";
}

function existingAvatarUrl(char) {
  const value = parseJson(char?.profile_json).avatarUrl;
  return typeof value === "string" ? value : "";
}

function getManagedAvatarUrl() {
  return $("plotManageAvatarPreview")?.dataset.avatarUrl || "";
}

function renderManagedAvatarPreview() {
  const preview = $("plotManageAvatarPreview");
  if (!preview) return;
  const src = safeImageUrl(getManagedAvatarUrl());
  preview.replaceChildren();
  preview.classList.toggle("has-image", Boolean(src));
  if (!src) {
    preview.textContent = "+";
    return;
  }
  preview.append(el("img", { attrs: { src, alt: "" } }));
}

function readManagedAvatarFile() {
  const file = $("plotManageCharacterAvatarFile").files?.[0];
  const preview = $("plotManageAvatarPreview");
  if (!file || !preview) return;
  const reader = new FileReader();
  reader.onload = () => {
    preview.dataset.avatarUrl = typeof reader.result === "string" ? reader.result : "";
    renderManagedAvatarPreview();
  };
  reader.onerror = () => {
    toast("이미지를 읽지 못했습니다");
  };
  reader.readAsDataURL(file);
}

function safeImageUrl(value) {
  if (typeof value !== "string" || !value) return "";
  if (value.startsWith("data:image/")) return value;
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}
