import { el } from "../dom.js";

export function detailPage() {
  return el("section", { id: "detailScreen", className: "screen" }, [
    el("div", { id: "plotDetail", className: "detail" }),
    el("div"),
    el("div", { className: "bottom" }, [
      el("button", { id: "startChatBtn", className: "primary full-width", text: "이 플롯으로 시작" }),
    ]),
  ]);
}
