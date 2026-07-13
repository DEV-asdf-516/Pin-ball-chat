import { deletePlot, findPlot, loadMorePlots, updatePlot } from "./catalog.js";
import { $, confirmDialog, el, parseJson, setChildren, toast } from "./dom.js";
import { bindGenrePicker, renderGenrePicker, selectedGenres } from "./genres.js";
import { state } from "./state.js";

export function bindPlotManager() {
  $("plotManageSearchInput").oninput = renderPlotManager;
  $("plotManageMoreBtn").onclick = async () => {
    await loadMorePlots();
    renderPlotManager();
  };
  $("plotManageList").onclick = (event) => {
    const item = event.target.closest("[data-manage-plot]");
    if (!item) return;
    selectManagePlot(item.dataset.managePlot);
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
  const plots = state.plots.filter((plot) => !query || plotText(plot).includes(query));
  $("plotManageStatus").textContent = `${state.plots.length}개 plot${state.catalogPages.plots.hasMore ? " · 더 있음" : ""}`;
  $("plotManageMoreBtn").hidden = !state.catalogPages.plots.hasMore;
  setChildren(
    $("plotManageList"),
    plots.length ? plots.map(plotRow) : [el("div", { className: "empty", text: "플롯이 없습니다." })],
  );
}

function plotRow(plot) {
  return el("button", { type: "button", className: "plot-manage-row", dataset: { managePlot: plot.id } }, [
    plotThumb(plot),
    el("div", { className: "plot-manage-info" }, [
      el("strong", { text: plot.title || plot.id }),
      el("span", { className: "meta", text: plot.id }),
    ]),
    el("span", { className: "plot-manage-edit-icon", text: "✎" }),
  ]);
}

function selectManagePlot(id) {
  state.managedPlotId = id;
  showPlotManageEdit();
}

function showPlotManageList() {
  $("plotManageListView").hidden = false;
  setChildren($("plotManageEditMount"), []);
  state.managedPlotId = null;
}

function showPlotManageEdit() {
  $("plotManageListView").hidden = true;
  renderPlotEditForm(state.managedPlotId);
}

async function saveManagedPlot() {
  const id = $("plotManageId").value.trim();
  if (!id) {
    toast("수정할 플롯을 선택하세요");
    return;
  }
  try {
    const plot = await updatePlot(id, {
      type: "plot",
      title: $("plotManageTitle").value.trim(),
      characterId: findPlot(id)?.character_id || state.chars.values().next().value?.id || "",
      genre: selectedGenres("plotManageGenreList"),
      sourceText: $("plotManageSource").value,
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
  const id = $("plotManageId").value.trim();
  if (!id || !(await confirmDialog(`${id} 플롯을 삭제할까요?`, { danger: true }))) return;
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
  setChildren($("plotManageEditMount"), [
    el("form", { id: "plotManageForm", className: "form-page plot-manage-edit" }, [
      field("plotManageId", "ID", el("input", { id: "plotManageId", value: plot?.id || "", attrs: { disabled: "true" } })),
      field("plotManageTitle", "제목", el("input", { id: "plotManageTitle", value: plot?.title || "", attrs: { autocomplete: "off" } })),
      field("plotManageGenreList", "장르", el("div", { id: "plotManageGenreList", className: "genre-picker" })),
      field("plotManageSource", "본문", el("textarea", { id: "plotManageSource", text: plot?.source_text || "", attrs: { rows: "12" } })),
      el("div", { className: "row" }, [
        el("button", { id: "deletePlotBtn", className: "danger", type: "button", text: "삭제" }),
        el("button", { className: "primary", type: "submit", text: "저장" }),
      ]),
    ]),
  ]);
  $("plotManageSource").value = plot?.source_text || "";
  renderGenrePicker("plotManageGenreList", plot ? (parseJson(plot.plot_json).genre || []) : []);
  bindGenrePicker("plotManageGenreList");
}

function field(inputId, label, control) {
  return el("div", { className: "field" }, [
    el("label", { text: label, attrs: { for: inputId } }),
    control,
  ]);
}

function plotThumb(plot) {
  const char = state.chars.get(plot.character_id);
  const src = safeImageUrl(parseJson(char?.profile_json).avatarUrl);
  if (src) return el("img", { className: "plot-manage-thumb", attrs: { src, alt: "" } });
  return el("div", { className: "plot-manage-thumb", text: (char?.name || plot.title || "?").trim().slice(0, 1) });
}

function safeImageUrl(value) {
  if (!value) return "";
  if (value.startsWith("data:image/")) return value;
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}
