import { settingsSheet } from "./settings-sheet.js";
import { userProfileSheet } from "./user-profile-sheet.js";
import { icon } from "./icons.js";
import { el } from "../dom.js";
import { chatPage } from "../pages/chat-page.js";
import { conversationsPage } from "../pages/conversations-page.js";
import { detailPage } from "../pages/detail-page.js";
import { plotCreatePage } from "../pages/plot-create-page.js";
import { plotManagePage } from "../pages/plot-manage-page.js";
import { plotsPage } from "../pages/plots-page.js";

export function appShell() {
  return [
    el("div", { className: "shell" }, [
      el("header", { id: "appHeader" }, [
        el("button", {
          id: "backBtn",
          className: "icon-btn",
          type: "button",
          attrs: { title: "뒤로가기", "aria-label": "뒤로가기" },
        }, [icon("chevronLeft")]),
        el("div", { className: "head-title" }, [
          el("strong", { id: "headerTitle", text: "Pinballchat" }),
          el("span", { id: "headerSub", text: "내 플롯" }),
        ]),
        el("button", {
          id: "settingsBtn",
          className: "icon-btn",
          type: "button",
          attrs: { title: "UI 설정", "aria-label": "UI 설정" },
        }, [icon("settings")]),
      ]),
      el("main", {}, [
        plotsPage(),
        plotCreatePage(),
        plotManagePage(),
        conversationsPage(),
        detailPage(),
        chatPage(),
      ]),
    ]),
    settingsSheet(),
    userProfileSheet(),
    el("div", { id: "appDialog", className: "dialog" }, [
      el("form", { id: "appDialogPanel", className: "dialog-panel" }),
    ]),
    el("div", { id: "toast", className: "toast" }),
  ];
}
