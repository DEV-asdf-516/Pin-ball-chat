import { icon } from "../components/icons.js";
import { el } from "../dom.js";

export function chatPage() {
  return el("section", { id: "chatScreen", className: "screen" }, [
    el("div", { className: "chat-header" }, [
      el("button", {
        id: "chatBackBtn",
        className: "icon-btn",
        type: "button",
        attrs: { title: "뒤로가기", "aria-label": "뒤로가기" },
      }, [icon("chevronLeft")]),
      el("div", { className: "chat-head-title" }, [
        el("strong", { id: "chatHeaderTitle", text: "채팅" }),
        el("span", { id: "chatHeaderSub" }),
      ]),
      el("div", { className: "header-actions" }, [
        el("button", {
          id: "chatUserProfileBtn",
          className: "icon-btn",
          type: "button",
          attrs: { title: "유저 프로필", "aria-label": "유저 프로필" },
        }, [icon("user")]),
        el("button", {
          id: "chatSettingsBtn",
          className: "icon-btn",
          type: "button",
          attrs: { title: "대화 설정", "aria-label": "대화 설정" },
        }, [icon("settings")]),
      ]),
    ]),
    el("div", { id: "messages", className: "messages" }),
    el("form", { id: "composer", className: "composer" }, [
      el("div", {
        id: "composerHandle",
        className: "composer-handle",
        attrs: { title: "입력창 크기 조절", "aria-label": "입력창 크기 조절" },
      }, [
        el("span"),
      ]),
      el("div", { className: "composer-input-wrap" }, [
        el("textarea", { id: "messageInput", attrs: { rows: "1" } }),
        el("button", {
          id: "insertMentionBtn",
          className: "composer-symbol composer-symbol-start",
          type: "button",
          text: "@",
          attrs: { title: "@ 입력", "aria-label": "@ 입력" },
        }),
        el("button", {
          id: "insertAsteriskBtn",
          className: "composer-symbol composer-symbol-end",
          type: "button",
          text: "*",
          attrs: { title: "* 입력", "aria-label": "* 입력" },
        }),
      ]),
      el("button", {
        id: "sendBtn",
        className: "icon-btn primary",
        text: "↑",
        attrs: { title: "전송", "aria-label": "전송" },
      }),
    ]),
    el("div", { id: "messageBatchBar", className: "batch-bar is-hidden" }, [
      el("button", { id: "cancelMessageBatchBtn", type: "button", text: "취소" }),
      el("button", { id: "deleteSelectedMessagesBtn", className: "danger", type: "button", text: "선택 삭제" }),
    ]),
  ]);
}
