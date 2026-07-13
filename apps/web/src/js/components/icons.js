const svgNs = "http://www.w3.org/2000/svg";

const iconShapes = {
  chevronLeft: [
    ["path", { d: "M14.8 5.2a1.2 1.2 0 0 1 0 1.7L9.7 12l5.1 5.1a1.2 1.2 0 1 1-1.7 1.7l-6-6a1.2 1.2 0 0 1 0-1.7l6-6a1.2 1.2 0 0 1 1.7.1Z" }],
  ],
  settings: [
    ["rect", { x: "4", y: "5.4", width: "16", height: "2.2", rx: "1.1" }],
    ["circle", { cx: "9", cy: "6.5", r: "2.55" }],
    ["rect", { x: "4", y: "10.9", width: "16", height: "2.2", rx: "1.1" }],
    ["circle", { cx: "15", cy: "12", r: "2.55" }],
    ["rect", { x: "4", y: "16.4", width: "16", height: "2.2", rx: "1.1" }],
    ["circle", { cx: "11", cy: "17.5", r: "2.55" }],
  ],
  user: [
    ["path", { d: "M12 12.1a4.6 4.6 0 1 0 0-9.2 4.6 4.6 0 0 0 0 9.2ZM4 20.25c0-3.86 3.58-6.55 8-6.55s8 2.69 8 6.55c0 .47-.38.85-.85.85H4.85a.85.85 0 0 1-.85-.85Z" }],
  ],
};

export function icon(name) {
  const svg = document.createElementNS(svgNs, "svg");
  setAttrs(svg, {
    class: "ui-icon",
    viewBox: "0 0 24 24",
    fill: "currentColor",
    "aria-hidden": "true",
    focusable: "false",
  });
  for (const [tag, attrs] of iconShapes[name] || []) {
    const node = document.createElementNS(svgNs, tag);
    setAttrs(node, attrs);
    svg.appendChild(node);
  }
  return svg;
}

function setAttrs(node, attrs) {
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
}
