import { apiBase } from "./api.js";
import { createCharacter, deleteCharacter, deletePlot, findPlot, firstPlotCharacter, loadCatalogKind, loadMorePlots, plotCharacters, updateCharacter, updatePlot, uploadCharacterAvatar } from "./catalog.js";
import { $, bindGrowingTextarea, confirmDelete, el, parseJson, setChildren, toast } from "./dom.js";
import { bindCharacterEditor, characterValues, renderCharacterEditor } from "./character-editor.js";
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
  if (plot && !plotCharacters(plot).length) {
    try {
      await loadCatalogKind("chars", true);
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
    const currentCharacters = plotCharacters(currentPlot);
    const values = characterValues("plotManageCharacters");
    if (!values.length || values.length > 10 || values.some((character) => !character.name || !character.sourceText)) {
      toast("캐릭터는 1~10명이며 이름과 설명을 모두 입력하세요");
      return;
    }

    const nextIds = new Set(values.map((character) => character.id).filter(Boolean));
    for (const character of currentCharacters) {
      if (!nextIds.has(character.id)) await deleteCharacter(character.id);
    }

    for (const [index, value] of values.entries()) {
      const payload = {
        type: "character",
        plotId: id,
        sortOrder: index,
        name: value.name,
        displayName: value.name,
        sourceText: value.sourceText,
        ...(value.avatarUrl ? { avatarUrl: value.avatarUrl } : {}),
      };
      const character = value.id
        ? await updateCharacter(value.id, payload)
        : await createCharacter({ id: makeCatalogId(), ...payload });
      if (value.avatarFile) await uploadCharacterAvatar(character.id, value.avatarFile);
    }

    const intro = introValue("plotManageIntroEditor");
    const sampleDialogues = introValue("plotManageSampleEditor");
    const plot = await updatePlot(id, {
      type: "plot",
      title: $("plotManageTitle").value.trim(),
      genre: selectedGenres("plotManageGenreList"),
      sourceText: $("plotManageSource").value,
      ...(intro ? { intro } : {}),
      ...(sampleDialogues ? { sampleDialogues } : {}),
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
  if (!id || !(await confirmDelete(`${plotTitle(plot)} 플롯을 삭제할까요?`))) return;
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
  return [
    plot.id,
    plot.title,
    plot.source_text,
    ...plotCharacters(plot).flatMap((character) => [character.id, character.name, character.source_text]),
    ...(raw.genre || []),
  ].filter(Boolean).join(" ").toLowerCase();
}

function renderPlotEditForm(id) {
  const plot = findPlot(id);
  const plotData = parseJson(plot?.plot_json);
  const characters = plotCharacters(plot);
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
          el("h2", { text: "등장인물" }),
          el("div", { id: "plotManageCharacters", className: "character-editor" }),
        ]),
        el("section", { className: "form-card" }, [
          el("h2", { text: "대화 샘플" }),
          el("div", { id: "plotManageSampleEditor", className: "intro-editor" }),
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
  bindGrowingTextarea($("plotManageSource"));
  renderCharacterEditor("plotManageCharacters", characters);
  bindCharacterEditor("plotManageCharacters");
  renderGenrePicker("plotManageGenreList", plotData.genre || []);
  bindGenrePicker("plotManageGenreList");
  renderIntroEditor("plotManageIntroEditor", plotData.intro);
  bindIntroEditor("plotManageIntroEditor");
  renderIntroEditor("plotManageSampleEditor", plotData.sampleDialogues);
  bindIntroEditor("plotManageSampleEditor");
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
  const character = firstPlotCharacter(plot);
  const src = safeImageUrl(parseJson(character?.profile_json).avatarUrl);
  if (src) return el("img", { className: "plot-manage-thumb", attrs: { src, alt: "" } });
  return el("div", { className: "plot-manage-thumb", text: characterName(character, plotTitle(plot)).trim().slice(0, 1) });
}

function plotTitle(plot) {
  return plot?.title || "제목 없는 플롯";
}

function plotMeta(plot) {
  const character = firstPlotCharacter(plot);
  const genres = parseJson(plot.plot_json).genre || [];
  return [characterName(character), ...genres].filter(Boolean).join(" · ") || "플롯";
}

function plotList() {
  const bucket = state.catalog.plots;
  return bucket.order.map((id) => bucket.byId.get(id)).filter(Boolean);
}

function characterName(character, fallback = "") {
  if (!character) return fallback;
  const profile = parseJson(character.profile_json);
  return profile.displayName || profile.display_name || character.name || profile.name || fallback;
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

function makeCatalogId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
