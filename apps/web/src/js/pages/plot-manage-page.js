import { searchField } from "../components/common.js";
import { el } from "../dom.js";

export function plotManagePage() {
  return el("section", { id: "plotManageScreen", className: "screen" }, [
    el("div", { id: "plotManageToolbar", className: "toolbar" }, [
      el("div", { className: "row" }, [
        searchField("plotManageSearchInput"),
        el("button", { id: "plotManageMoreBtn", type: "button", text: "더 보기" }),
      ]),
      el("div", { id: "plotManageStatus", className: "status" }),
    ]),
    el("div", { className: "detail plot-manage-detail" }, [
      el("div", { id: "plotManageListView", className: "plot-manage-list-view" }, [
        el("div", { id: "plotManageList", className: "plot-manage-list" }),
      ]),
      el("div", { id: "plotManageEditMount" }),
    ]),
  ]);
}
