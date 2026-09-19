import { el } from "./ui.js";

// Placeholder portraits. No hero art exists in this project (and real MLBB
// art is Moonton's, so it isn't scraped or generated): each hero gets a
// chamfered initials badge on one of eight muted tones that sit inside the
// stage palette, chosen deterministically from the name so a hero always
// looks the same everywhere.
const TONES = [
  ["#17474f", "#2a7480"], // teal
  ["#25337a", "#3d50a8"], // indigo
  ["#48347f", "#6a50a8"], // violet
  ["#7a2a38", "#a63d4b"], // crimson
  ["#7a5219", "#a8752a"], // amber
  ["#25603e", "#3a8558"], // forest
  ["#34465a", "#506a84"], // slate
  ["#6c2a62", "#96408a"], // plum
];

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function initials(name) {
  // "Popol and Kupa" -> PK, "X.Borg" -> XB, "Yi Sun-shin" -> YS, "Chang'e" -> CH
  const words = name.replace(/[.\-]/g, " ").split(/\s+/).filter((w) => w && w.toLowerCase() !== "and");
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return name.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase();
}

export function portrait(name, { size = 40, gold = false } = {}) {
  const [a, b] = TONES[hash(name) % TONES.length];
  return el("span", {
    class: `portrait bevel${gold ? " gold" : ""}`,
    style: `--size:${size}px;--tone-a:${a};--tone-b:${b}`,
    "aria-hidden": "true",
  }, initials(name));
}

/** Case- and punctuation-insensitive key for matching a typed query to hero names. */
export const norm = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
