import { mainTabs, refreshButton, searchField } from "../components/common.js";
import { el } from "../dom.js";

export function conversationsPage() {
  return el("section", { id: "conversationsScreen", className: "screen" }, [
    el("div", { className: "toolbar" }, [
      el("div", { id: "conversationTabs" }, [mainTabs("conversations")]),
      el("div", { className: "row" }, [
        searchField("conversationSearchInput"),
        refreshButton("reloadConversationsBtn"),
      ]),
      el("div", { id: "conversationStatus", className: "status", text: "대화 불러오는 중..." }),
    ]),
    el("div", { id: "conversationList", className: "list" }),
  ]);
}
