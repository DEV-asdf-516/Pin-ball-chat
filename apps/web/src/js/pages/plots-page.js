import { mainTabs, refreshButton, searchField } from "../components/common.js";
import { el } from "../dom.js";

export function plotsPage() {
  return el("section", { id: "plotsScreen", className: "screen active" }, [
    el("div", { className: "toolbar" }, [
      el("div", { id: "mainTabs" }, [mainTabs("plots")]),
      el("div", { className: "row" }, [
        searchField("searchInput"),
        refreshButton("reloadBtn"),
      ]),
      el("div", { id: "filterSeg", className: "seg one" }, [
        el("button", { className: "active", text: "전체", dataset: { filter: "all" } }),
      ]),
      el("div", { id: "apiStatus", className: "status", text: "API 확인 중..." }),
    ]),
    el("div", { id: "plotList", className: "list" }),
    el("button", {
      id: "newPlotFab",
      className: "fab",
      type: "button",
      attrs: { title: "플롯 제작", "aria-label": "플롯 제작" },
    }, [el("span", { className: "fab-icon", text: "+" })]),
    el("div", { id: "plotFabMenu", className: "dropdown fab-menu" }, [
      el("button", { id: "fabManagePlotsBtn", type: "button", text: "플롯 관리" }),
    ]),
  ]);
}
