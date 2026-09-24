import { el } from "./ui.js";

// Hero portraits. Real art comes from the Rone Arena API's own `head` field,
// downloaded locally by `python -m src.web.fetch_hero_images` (nothing loads
// from a CDN at runtime). Underneath every portrait is a generated initials
// badge — a chamfered tile on one of eight muted stage tones, picked
// deterministically from the name so a hero always looks the same everywhere.
// The badge is not a placeholder that gets replaced; the image is layered over
// it, so a hero with no downloaded art, or an image that fails to load, simply
// shows the badge. Run the app without fetching and everything still works.
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

// slug -> filename, written by fetch_hero_images.py. Empty until loaded, and
// staying empty is a supported state, not an error.
let images = {};

export async function loadPortraits() {
  try {
    const response = await fetch("heroes/manifest.json", { cache: "no-cache" });
    if (response.ok) images = await response.json();
  } catch {
    images = {}; // no art downloaded yet; initials badges carry the UI
  }
}

export function portrait(name, { size = 40, gold = false } = {}) {
  const [a, b] = TONES[hash(name) % TONES.length];
  // Initials live in their own element so the image can hide them without
  // removing them: if the image fails, dropping the `has-img` class brings the
  // badge straight back, with nothing to re-render.
  const badge = el("span", {
    class: `portrait bevel${gold ? " gold" : ""}`,
    style: `--size:${size}px;--tone-a:${a};--tone-b:${b}`,
    "aria-hidden": "true",
  }, el("span", { class: "p-ini", text: initials(name) }));

  const file = images[norm(name)];
  if (file) {
    badge.classList.add("has-img");
    badge.append(el("img", {
      class: "p-img", src: `heroes/${file}`, alt: "", loading: "lazy", decoding: "async",
      onerror: (event) => { event.target.remove(); badge.classList.remove("has-img"); },
    }));
  }
  return badge;
}

/** Case- and punctuation-insensitive key for matching a typed query to hero names. */
export const norm = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
