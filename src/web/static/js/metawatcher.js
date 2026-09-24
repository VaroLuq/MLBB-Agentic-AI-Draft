import { api } from "./api.js";
import { $, el, clear, icon } from "./ui.js";

// Six categorical slots, validated against this app's panel surface #16212d
// (dark mode, adjacent pairs): worst CVD deltaE 8.4, worst normal-vision
// deltaE 19.3, all >= 3:1 contrast. Six is the cap on purpose — a seventh
// series would mean cycling or inventing a hue, so the picker stops at six.
// Gold is deliberately absent: this design system reserves it for the primary
// action and the lead pick, and a series wearing it would impersonate that.
const MAX_SERIES = 6;
const METRIC_LABEL = { win_rate: "Win rate", pick_rate: "Pick rate", ban_rate: "Ban rate" };

const VIEW_W = 760;
const VIEW_H = 330;
const PAD = { top: 18, right: 18, bottom: 42, left: 52 }; // bottom fits the x-axis band

let data = null;
let loadError = null;
let metric = "win_rate";
let selected = [];              // hero names, selection order
const slots = new Map();        // hero -> colour slot, held for as long as it is selected
let hoverIndex = null;

export function initMetaWatcher() {
  load();
}

export function showMetaWatcher() {
  if (!data && !loadError) load();
}

async function load() {
  loadError = null;
  render();
  try {
    data = await api.snapshots();
    // Open on the heroes that actually moved; the server ranks by win-rate span.
    selected = data.movers.slice(0, MAX_SERIES).map((m) => m.name);
    selected.forEach(assignSlot);
  } catch (error) {
    loadError = error;
  }
  render();
}

// Colour follows the entity, not its position. Removing a hero frees only its
// own slot, so the survivors never repaint.
function assignSlot(hero) {
  if (slots.has(hero)) return slots.get(hero);
  const taken = new Set(slots.values());
  let slot = 0;
  while (taken.has(slot)) slot += 1;
  slots.set(hero, slot);
  return slot;
}

function toggleHero(hero) {
  if (selected.includes(hero)) {
    selected = selected.filter((h) => h !== hero);
    slots.delete(hero);
  } else {
    if (selected.length >= MAX_SERIES) return;
    selected = [...selected, hero];
    assignSlot(hero);
  }
  render();
}

// ------------------------------------------------------------------ scales
function seriesValues(hero) {
  return data.series[hero]?.[metric] ?? [];
}

function domain() {
  const values = selected.flatMap((h) => seriesValues(h)).filter((v) => v != null);
  if (!values.length) return [0, 1];
  let [lo, hi] = [Math.min(...values), Math.max(...values)];
  // Line charts read change, so the domain hugs the data. A zero baseline
  // would flatten win rates that live inside a few points of each other.
  const pad = (hi - lo) * 0.18 || 0.01;
  return [Math.max(0, lo - pad), Math.min(1, hi + pad)];
}

// Time-proportional, NOT one step per snapshot. Snapshots are irregular — the
// history has 2- and 3-day gaps alongside consecutive days — and spacing them
// evenly would make a 3-day drift look exactly as steep as a 1-day drift. On a
// view whose whole job is judging how fast these numbers move, that would be
// an actively misleading axis.
function makeX(days) {
  const t = days.map((d) => Date.parse(`${d}T00:00:00Z`));
  const span = t.at(-1) - t[0] || 1;
  const fn = (i) => PAD.left + ((t[i] - t[0]) / span) * (VIEW_W - PAD.left - PAD.right);
  fn.times = t;
  return fn;
}

const yAt = (v, [lo, hi]) =>
  PAD.top + (1 - (v - lo) / (hi - lo || 1)) * (VIEW_H - PAD.top - PAD.bottom);

// Round tick values (52%, 54%, ...) rather than even divisions of the data
// range, which produce unreadable labels like 58.3% / 56.1% / 53.9%.
function ticks([lo, hi], target = 4) {
  const raw = (hi - lo) / target;
  const mag = 10 ** Math.floor(Math.log10(raw || 1e-6));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

const pct = (v, digits = 1) => `${(v * 100).toFixed(digits)}%`;
const shortDay = (iso) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });

// --------------------------------------------------------------- rendering
const NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  children.filter(Boolean).forEach((c) => node.append(c));
  return node;
}

function render() {
  const host = $("#mw-body");
  if (!host) return;
  clear(host);

  if (loadError) {
    host.append(el("div", { class: "banner banner-warn bevel", role: "alert" }, icon("alert"),
      el("div", { class: "banner-body" },
        el("strong", { text: loadError.message }),
        loadError.hint && el("p", { text: loadError.hint }),
        el("div", { class: "banner-actions" },
          el("button", { class: "btn bevel", type: "button", onclick: load }, icon("refresh"), "Retry")))));
    return;
  }
  if (!data) {
    host.append(el("p", { class: "muted", text: "Reading snapshot history..." }));
    return;
  }
  if (data.days.length < 2) {
    host.append(el("div", { class: "empty" }, icon("hex", "empty-mark"),
      el("h3", { text: "Not enough history yet" }),
      el("p", { text: `There ${data.days.length === 1 ? "is 1 snapshot" : "are no snapshots"} on record. A trend needs at least two days.` })));
    return;
  }

  host.append(filterRow(), chartCard(), tableCard());
}

// Filters sit above the chart card, never inside it.
function filterRow() {
  const row = el("div", { class: "mw-filters" });

  const metrics = el("div", { class: "seg", role: "radiogroup", "aria-label": "Metric" });
  for (const m of data.metrics) {
    metrics.append(el("label", {},
      el("input", {
        type: "radio", name: "mw-metric", value: m, checked: m === metric,
        onchange: () => { metric = m; render(); },
      }),
      el("span", { class: "seg-face bevel", text: METRIC_LABEL[m] ?? m })));
  }

  row.append(
    el("div", { class: "mw-field" }, el("div", { class: "group-label", text: "Metric" }), metrics),
    el("div", { class: "mw-field mw-field-grow" },
      el("div", { class: "group-label" },
        `Heroes (${selected.length}/${MAX_SERIES})`,
        selected.length >= MAX_SERIES
          ? el("span", { class: "mw-hint", text: " — remove one to add another" })
          : null),
      heroPicker()),
  );
  return row;
}

function heroPicker() {
  const list = el("div", { class: "mw-heroes" });
  // Ordered by how much each hero moved: the reason to look at this view.
  for (const mover of data.movers) {
    const on = selected.includes(mover.name);
    const full = !on && selected.length >= MAX_SERIES;
    const chip = el("button", {
      class: "chip-btn bevel mw-hero", type: "button",
      "aria-pressed": String(on), disabled: full,
      title: full ? `Showing the maximum of ${MAX_SERIES} heroes` : `${pct(mover.span, 1)} swing across the window`,
      onclick: () => toggleHero(mover.name),
    });
    if (on) chip.append(el("span", { class: "mw-dot", dataset: { slot: slots.get(mover.name) }, "aria-hidden": "true" }));
    chip.append(el("span", { text: mover.name }),
      el("span", { class: "mw-swing num", text: pct(mover.span, 1) }));
    list.append(chip);
  }
  return list;
}

function chartCard() {
  const card = el("section", { class: "panel bevel mw-chart", "aria-labelledby": "mw-chart-h" });
  card.append(
    el("div", { class: "mw-chart-head" },
      el("h3", { id: "mw-chart-h", class: "panel-title", text: `${METRIC_LABEL[metric]} over time` }),
      el("span", { class: "muted small num", text: `${data.days.length} days · ${shortDay(data.days[0])} to ${shortDay(data.days.at(-1))}` })),
  );

  if (!selected.length) {
    card.append(el("p", { class: "muted mw-empty", text: "Pick a hero above to plot it." }));
    return card;
  }
  card.append(plot(), legend());
  return card;
}

function plot() {
  const dom = domain();
  const n = data.days.length;
  const x = makeX(data.days);
  const svg = s("svg", {
    class: "mw-svg", viewBox: `0 0 ${VIEW_W} ${VIEW_H}`, role: "img",
    "aria-label": `${METRIC_LABEL[metric]} over ${n} days for ${selected.join(", ")}. The table below lists every value.`,
  });

  // Recessive chrome: solid hairlines, never dashed.
  for (const t of ticks(dom)) {
    const y = yAt(t, dom);
    svg.append(s("line", { class: "mw-grid", x1: PAD.left, x2: VIEW_W - PAD.right, y1: y, y2: y }));
    svg.append(s("text", { class: "mw-axis mw-axis-y", x: PAD.left - 10, y: y + 4, "text-anchor": "end" }, text(pct(t, 1))));
  }
  svg.append(s("line", { class: "mw-baseline", x1: PAD.left, x2: VIEW_W - PAD.right,
    y1: VIEW_H - PAD.bottom, y2: VIEW_H - PAD.bottom }));

  // Drop a label only when it would physically collide with the previous one;
  // an irregular time axis makes fixed every-nth thinning wrong.
  let lastLabelX = -Infinity;
  data.days.forEach((day, i) => {
    const px = x(i);
    if (px - lastLabelX < 58 && i !== n - 1) return;
    lastLabelX = px;
    svg.append(s("text", { class: "mw-axis", x: px, y: VIEW_H - PAD.bottom + 20, "text-anchor": "middle" },
      text(shortDay(day))));
  });

  const crosshair = s("line", { class: "mw-crosshair", x1: 0, x2: 0,
    y1: PAD.top, y2: VIEW_H - PAD.bottom, visibility: "hidden" });
  svg.append(crosshair);

  for (const hero of selected) {
    const values = seriesValues(hero);
    const slot = slots.get(hero);
    // A hero outside the top 50 that day is missing, not zero: break the line
    // into segments rather than drawing through the gap.
    let run = [];
    const flush = () => {
      if (run.length > 1) {
        svg.append(s("path", { class: "mw-line", "data-slot": slot,
          d: run.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") }));
      } else if (run.length === 1) {
        svg.append(s("circle", { class: "mw-dot-mark", "data-slot": slot, cx: run[0].x, cy: run[0].y, r: 4 }));
      }
      run = [];
    };
    values.forEach((v, i) => {
      if (v == null) { flush(); return; }
      run.push({ x: x(i), y: yAt(v, dom) });
    });
    flush();
    values.forEach((v, i) => {
      if (v == null) return;
      svg.append(s("circle", { class: "mw-point", "data-slot": slot, cx: x(i), cy: yAt(v, dom), r: 4 }));
    });
  }

  const wrap = el("div", { class: "mw-plot" }, svg);
  const tip = el("div", { class: "mw-tip bevel", hidden: true });
  wrap.append(tip);

  // Hover mutates the crosshair and tooltip in place rather than re-rendering.
  // A re-render would destroy the very rect the pointer is inside, which
  // fires mouseleave, which re-renders again — a flicker loop.
  const setHover = (i) => {
    hoverIndex = i;
    if (i == null) { crosshair.setAttribute("visibility", "hidden"); tip.hidden = true; return; }
    crosshair.setAttribute("x1", x(i));
    crosshair.setAttribute("x2", x(i));
    crosshair.setAttribute("visibility", "visible");
    fillTooltip(tip, i, x);
    tip.hidden = false;
  };

  // Hit bands reach to the midpoint of each neighbour, so every pixel of the
  // plot belongs to its nearest day and hovering never needs a 4px dot.
  data.days.forEach((_, i) => {
    const left = i === 0 ? PAD.left : (x(i - 1) + x(i)) / 2;
    const right = i === n - 1 ? VIEW_W - PAD.right : (x(i) + x(i + 1)) / 2;
    const band = s("rect", { class: "mw-hit", x: left, y: PAD.top,
      width: Math.max(1, right - left), height: VIEW_H - PAD.top - PAD.bottom });
    band.addEventListener("mouseenter", () => setHover(i));
    svg.append(band);
  });
  wrap.addEventListener("mouseleave", () => setHover(null));
  return wrap;
}

function text(value) {
  return document.createTextNode(value);
}

function fillTooltip(tip, index, x) {
  clear(tip);
  // Ranked by value so the reading order matches the lines on screen.
  const rows = selected
    .map((hero) => ({ hero, value: seriesValues(hero)[index] }))
    .sort((a, b) => (b.value ?? -1) - (a.value ?? -1));
  tip.dataset.side = x(index) > VIEW_W / 2 ? "left" : "right";
  tip.style.setProperty("--x", `${(x(index) / VIEW_W) * 100}%`);
  tip.append(
    el("div", { class: "mw-tip-day", text: shortDay(data.days[index]) }),
    ...rows.map(({ hero, value }) => el("div", { class: "mw-tip-row" },
      el("span", { class: "mw-dot", dataset: { slot: slots.get(hero) }, "aria-hidden": "true" }),
      el("span", { class: "mw-tip-name", text: hero }),
      el("span", { class: "mw-tip-val num", text: value == null ? "—" : pct(value, 2) }))));
}

function legend() {
  return el("div", { class: "mw-legend" }, ...selected.map((hero) => el("span", { class: "mw-key" },
    el("span", { class: "mw-dot", dataset: { slot: slots.get(hero) }, "aria-hidden": "true" }),
    el("span", { text: hero }))));
}

// A tooltip must never be the only way to read a value.
function tableCard() {
  const card = el("section", { class: "panel bevel mw-table-card", "aria-labelledby": "mw-table-h" });
  card.append(el("h3", { id: "mw-table-h", class: "panel-title", text: `${METRIC_LABEL[metric]} by day` }));
  if (!selected.length) return card;

  const table = el("table", { class: "mw-table" });
  table.append(el("thead", {}, el("tr", {},
    el("th", { scope: "col", text: "Day" }),
    ...selected.map((hero) => el("th", { scope: "col" },
      el("span", { class: "mw-dot", dataset: { slot: slots.get(hero) }, "aria-hidden": "true" }),
      hero)))));
  table.append(el("tbody", {}, ...data.days.map((day, i) => el("tr", {},
    el("th", { scope: "row", class: "num", text: shortDay(day) }),
    ...selected.map((hero) => {
      const v = seriesValues(hero)[i];
      return el("td", { class: "num", text: v == null ? "—" : pct(v, 2),
        title: v == null ? "Outside the tracked top 50 that day" : "" });
    })))));
  card.append(el("div", { class: "mw-table-wrap", tabindex: "0" }, table));
  return card;
}
