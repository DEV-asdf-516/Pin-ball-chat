import { $, el, setChildren, toast } from "./dom.js";

export const GENRES = ["로맨스", "힐링", "드라마", "얀데레", "판타지", "액션", "미스터리", "호러"];

const aliases = new Map([
  ["romance", "로맨스"],
  ["healing", "힐링"],
  ["slice_of_life", "힐링"],
  ["drama", "드라마"],
  ["angst", "드라마"],
  ["yandere", "얀데레"],
  ["fantasy", "판타지"],
  ["action", "액션"],
  ["mystery", "미스터리"],
  ["horror", "호러"],
]);

export function bindGenrePicker(id) {
  const picker = $(id);
  picker.onclick = (event) => {
    const button = event.target.closest("[data-genre]");
    if (!button) return;
    const nextActive = !button.classList.contains("active");
    if (nextActive && selectedGenres(id).length >= 2) {
      toast("장르는 최대 2개까지 선택할 수 있습니다");
      return;
    }
    button.classList.toggle("active", nextActive);
  };
}

export function renderGenrePicker(id, selected = []) {
  const selectedSet = new Set(normalizeGenres(selected));
  setChildren($(id), GENRES.map((genre) => (
    el("button", {
      type: "button",
      className: `genre-chip${selectedSet.has(genre) ? " active" : ""}`,
      text: genre,
      dataset: { genre },
    })
  )));
}

export function selectedGenres(id) {
  return [...$(id).querySelectorAll("[data-genre].active")].map((button) => button.dataset.genre);
}

export function normalizeGenres(values) {
  return values
    .map((value) => aliases.get(String(value).trim().toLowerCase()) || String(value).trim())
    .filter((value, index, arr) => GENRES.includes(value) && arr.indexOf(value) === index)
    .slice(0, 2);
}
