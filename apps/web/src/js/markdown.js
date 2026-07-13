import { el } from "./dom.js";

const BYTE_DECODER = new TextDecoder("utf-8", { fatal: true });
const HEX_BYTE_RUN = /(?:<0x[0-9a-fA-F]{2}>){2,}/g;

export function renderMarkdown(text) {
  const lines = normalizeGeneratedText(text).split("\n");
  const nodes = [];

  for (let i = 0; i < lines.length;) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      nodes.push(el("pre", {}, [el("code", { text: code.join("\n") })]));
      i += i < lines.length ? 1 : 0;
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      nodes.push(el(`h${Math.min(heading[1].length + 2, 5)}`, {}, inlineNodes(heading[2])));
      i += 1;
      continue;
    }

    if (/^[-*_]{3,}\s*$/.test(line)) {
      nodes.push(el("hr"));
      i += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      nodes.push(el("blockquote", {}, [paragraph(quote.join("\n"))]));
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(el("li", {}, inlineNodes(lines[i].replace(/^[-*]\s+/, ""))));
        i += 1;
      }
      nodes.push(el("ul", {}, items));
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(el("li", {}, inlineNodes(lines[i].replace(/^\d+\.\s+/, ""))));
        i += 1;
      }
      nodes.push(el("ol", {}, items));
      continue;
    }

    const para = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      para.push(lines[i]);
      i += 1;
    }
    nodes.push(paragraph(para.join("\n")));
  }

  return el("div", { className: "markdown" }, nodes);
}

function normalizeGeneratedText(text) {
  return String(text || "").replace(HEX_BYTE_RUN, decodeHexByteRun);
}

function decodeHexByteRun(run) {
  const bytes = [...run.matchAll(/0x([0-9a-fA-F]{2})/g)].map((match) => parseInt(match[1], 16));
  try {
    return BYTE_DECODER.decode(new Uint8Array(bytes));
  } catch {
    return run;
  }
}

function isBlockStart(line) {
  return line.startsWith("```")
    || /^(#{1,3})\s+/.test(line)
    || /^[-*_]{3,}\s*$/.test(line)
    || /^>\s?/.test(line)
    || /^[-*]\s+/.test(line)
    || /^\d+\.\s+/.test(line);
}

function paragraph(text) {
  return el("p", {}, inlineNodes(text));
}

function inlineNodes(text) {
  const nodes = [];
  const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) nodes.push(document.createTextNode(text.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("`")) nodes.push(el("code", { text: token.slice(1, -1) }));
    else if (token.startsWith("**")) nodes.push(el("strong", { text: token.slice(2, -2) }));
    else nodes.push(el("em", { text: token.slice(1, -1) }));
    cursor = match.index + token.length;
  }
  if (cursor < text.length) nodes.push(document.createTextNode(text.slice(cursor)));
  return nodes;
}
