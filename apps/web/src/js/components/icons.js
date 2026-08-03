const svgNs = "http://www.w3.org/2000/svg";

const iconShapes = {
  chevronLeft: [
    ["path", { d: "M14.8 5.2a1.2 1.2 0 0 1 0 1.7L9.7 12l5.1 5.1a1.2 1.2 0 1 1-1.7 1.7l-6-6a1.2 1.2 0 0 1 0-1.7l6-6a1.2 1.2 0 0 1 1.7.1Z" }],
  ],
  chevronDown: [
    ["path", { d: "m7.5 9.5 4.5 4.5 4.5-4.5", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }],
  ],
  link: [
    ["path", { d: "M10.1 13.9a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 0 0-5.7-5.7l-1.3 1.3", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }],
    ["path", { d: "M13.9 10.1a4 4 0 0 0-5.7 0l-2.8 2.8a4 4 0 0 0 5.7 5.7l1.3-1.3", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }],
  ],
  gear: [
    ["path", { d: "M19.43 12.98c.04-.32.07-.65.07-.98s-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.5 7.5 0 0 0-1.69-.98L14.5 2.42A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.5.42l-.38 2.65a7.5 7.5 0 0 0-1.69.98l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46c-.12.22-.07.49.12.64l2.11 1.65c-.04.32-.07.65-.07.98s.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.12.22.37.31.6.22l2.49-1c.51.4 1.08.73 1.69.98l.38 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.38-2.65c.61-.25 1.17-.58 1.69-.98l2.49 1c.23.09.48 0 .6-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.65ZM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7Z" }],
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
  refresh: [
    ["path", { d: "M19.2 7.1A8 8 0 1 0 20 14h-2.5a5.6 5.6 0 1 1-.7-5.1l-2.6 2.6H21V4.7l-1.8 2.4Z" }],
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
