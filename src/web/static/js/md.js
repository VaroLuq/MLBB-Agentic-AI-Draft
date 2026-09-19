import { el } from "./ui.js";

// Just enough Markdown for hand-written strategy notes: headings, paragraphs,
// bullet/numbered lists, **bold**, *italic*, `code`. Built as DOM nodes (never
// an HTML string), so note text can't inject markup.

function inline(text) {
  const nodes = [];
  let last = 0;
  for (const match of text.matchAll(/(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g)) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) nodes.push(el("strong", {}, token.slice(2, -2)));
    else if (token.startsWith("`")) nodes.push(el("code", {}, token.slice(1, -1)));
    else nodes.push(el("em", {}, token.slice(1, -1)));
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/**
 * `hideHeadings`: lowercase heading texts to drop when they lead the note
 * (the reader already shows the title above, so repeating it is noise).
 */
export function renderMarkdown(source, { hideHeadings = [], hideGeneric = false } = {}) {
  const root = el("div", { class: "prose" });
  const hide = new Set(hideHeadings.map((h) => h.toLowerCase()));
  let paragraph = [];
  let list = null;
  let leading = true;

  const flushParagraph = () => {
    if (paragraph.length) root.append(el("p", {}, inline(paragraph.join(" "))));
    paragraph = [];
  };
  const flushList = () => { list = null; };

  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();

    if (!line.trim()) { flushParagraph(); flushList(); continue; }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      flushParagraph(); flushList();
      if (leading && (hide.has(heading[2].toLowerCase()) || (hideGeneric && /\bnote$/i.test(heading[2])))) continue;
      const level = Math.min(heading[1].length + 2, 5); // h1 = page, h2 = note title
      root.append(el(`h${level}`, {}, inline(heading[2])));
      continue;
    }
    leading = false;

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== kind) {
        list = el(kind);
        root.append(list);
      }
      list.append(el("li", {}, inline((bullet || numbered)[1])));
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  return root;
}
