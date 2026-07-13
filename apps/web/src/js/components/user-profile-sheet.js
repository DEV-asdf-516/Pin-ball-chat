import { el } from "../dom.js";

export function userProfileSheet() {
  return el("div", { id: "userProfileSheet", className: "sheet", attrs: { role: "dialog", "aria-modal": "true" } }, [
    el("div", { className: "panel user-profile-panel" }, [
      el("div", { className: "sheet-handle" }),
      el("div", { className: "row" }, [
        el("strong", { id: "userProfileSheetTitle", text: "내 대화 프로필" }),
        el("button", {
          id: "closeUserProfileBtn",
          className: "icon-btn",
          type: "button",
          text: "×",
          attrs: { title: "닫기", "aria-label": "닫기" },
        }),
      ]),
      el("div", { id: "userProfileListView" }, [
        el("button", { id: "addUserProfileBtn", className: "user-profile-add", type: "button" }, [
          el("span", { className: "profile-avatar add", text: "+" }),
          el("strong", { text: "대화 프로필 추가" }),
        ]),
        el("div", { id: "userProfileList", className: "user-profile-list" }),
      ]),
      el("form", { id: "userProfileEditForm", className: "user-profile-edit is-hidden" }, [
        el("input", { id: "editUserProfileId", type: "hidden" }),
        el("div", { className: "field" }, [
          el("label", { text: "프로필 이름", attrs: { for: "editUserProfileName" } }),
          el("input", { id: "editUserProfileName", attrs: { autocomplete: "off", placeholder: "" } }),
        ]),
        el("div", { className: "field" }, [
          el("label", { text: "프로필 내용", attrs: { for: "editUserProfileSource" } }),
          el("textarea", { id: "editUserProfileSource", attrs: { rows: "10", placeholder: "" } }),
        ]),
        el("div", { className: "row" }, [
          el("button", { id: "deleteUserProfileBtn", className: "danger", type: "button", text: "삭제" }),
          el("button", { className: "primary", type: "submit", text: "저장" }),
        ]),
      ]),
    ]),
  ]);
}
