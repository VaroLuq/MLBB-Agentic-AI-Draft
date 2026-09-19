import { api, ApiError } from "./api.js";
import { $, $$, el, clear, icon, announce, toast, reducedMotion } from "./ui.js";
import { portrait, norm } from "./heroes.js";
import * as state from "./state.js";
import { LIMITS, LANES } from "./state.js";

const TEAM_LABEL = { ally: "Ally", enemy: "Enemy", ban: "Ban" };
const USED_MARK = { ally: "A", enemy: "E", ban: "B" };
const EVIDENCE_ICON = { tier: "trend", counter: "target", synergy: "link", note: "book" };

let heroes = [];
let heroesError = null;
let running = false;
let lastResult = null; // { kind: "result" | "error", ... }
let diagOpen = false;
let diagTab = "live";

// ---------------------------------------------------------------- setup
export function initDraft() {
  buildAssign();
  buildLane();
  $("#hero-search").addEventListener("input", renderPool);
  $("#hero-search").addEventListener("keydown", onSearchKey);
  $("#btn-recommend").addEventListener("click", requestRecommendation);
  $("#btn-clear").addEventListener("click", clearDraft);
  document.addEventListener("keydown", onGlobalKey);
  renderAll();
  renderResults();
  loadHeroes();
}

export function getHeroes() { return heroes; }

async function loadHeroes() {
  heroesError = null;
  renderPool();
  try {
    heroes = (await api.heroes()).heroes;
  } catch (error) {
    heroesError = error;
  }
  renderPool();
  document.dispatchEvent(new CustomEvent("heroes-loaded"));
}

function buildAssign() {
  const group = $("#assign");
  clear(group);
  const faces = { ally: "shield", enemy: "swords", ban: "ban" };
  for (const team of ["ally", "enemy", "ban"]) {
    group.append(el("label", { class: `seg-${team}` },
      el("input", { type: "radio", name: "assign", value: team, checked: state.draft.target === team, onchange: () => setTarget(team) }),
      el("span", { class: "seg-face bevel" }, icon(faces[team]), TEAM_LABEL[team] === "Ban" ? "Bans" : `${TEAM_LABEL[team]} picks`),
    ));
  }
  group.classList.add("seg");
}

function buildLane() {
  const group = $("#lane");
  clear(group);
  for (const lane of LANES) {
    group.append(el("label", {},
      el("input", { type: "radio", name: "lane", value: lane.value, checked: state.draft.lane === lane.value, onchange: () => { state.setLane(lane.value); renderSummary(); } }),
      el("span", { class: "seg-face bevel", text: lane.label }),
    ));
  }
}

function setTarget(team) {
  state.setTarget(team);
  $$('input[name="assign"]').forEach((input) => { input.checked = input.value === team; });
  renderTeams();
  renderBans();
}

// ------------------------------------------------------------ rendering
function renderAll() {
  renderTeams();
  renderBans();
  renderPool();
  renderSummary();
}

function renderTeams() {
  for (const team of ["ally", "enemy"]) {
    const list = $(`#slots-${team}`);
    clear(list);
    $(`#count-${team}`).textContent = `${state.draft[team].length}/${LIMITS[team]}`;
    for (let i = 0; i < LIMITS[team]; i++) {
      const name = state.draft[team][i];
      list.append(el("li", {}, name ? filledSlot(team, name) : emptySlot(team, i)));
    }
  }
}

function filledSlot(team, name) {
  return el("button", {
    class: "slot bevel", type: "button",
    "aria-label": `${name}, ${TEAM_LABEL[team].toLowerCase()} pick. Remove`,
    onclick: () => removeHero(team, name),
  },
    portrait(name, { size: 52 }),
    el("span", { class: "slot-name", text: name }),
    icon("x", "remove"),
  );
}

function emptySlot(team, index) {
  const active = state.draft.target === team;
  return el("button", {
    class: "slot slot-empty bevel", type: "button", dataset: { active },
    "aria-label": `Empty ${TEAM_LABEL[team].toLowerCase()} slot ${index + 1}. Choose a hero`,
    onclick: () => { setTarget(team); $("#hero-search").focus(); },
  },
    el("span", { class: "slot-num", text: index + 1 }),
    el("span", { class: "slot-text", text: active ? "Choose from the pool" : "Empty" }),
  );
}

function renderBans() {
  const list = $("#slots-ban");
  clear(list);
  $("#count-ban").textContent = `${state.draft.ban.length}/${LIMITS.ban}`;
  for (let i = 0; i < LIMITS.ban; i++) {
    const name = state.draft.ban[i];
    list.append(el("li", {}, name ? filledBan(name) : emptyBan(i)));
  }
}

function filledBan(name) {
  const face = portrait(name, { size: 38 });
  face.append(el("span", { class: "strike" }));
  return el("button", {
    class: "ban ban-filled bevel", type: "button", title: `${name} (banned). Remove`,
    "aria-label": `${name}, banned. Remove`, onclick: () => removeHero("ban", name),
  }, face, el("span", { class: "b-name", text: name }));
}

function emptyBan(index) {
  const active = state.draft.target === "ban";
  const face = el("span", { class: "portrait bevel", style: "--size:38px", "aria-hidden": "true" }, icon("plus"));
  return el("button", {
    class: "ban ban-empty bevel", type: "button", dataset: { active },
    "aria-label": `Empty ban slot ${index + 1}. Choose a hero`,
    onclick: () => { setTarget("ban"); $("#hero-search").focus(); },
  }, face, el("span", { class: "b-name", text: `${index + 1}` }));
}

function renderPool() {
  const grid = $("#pool-grid");
  clear(grid);

  if (heroesError) {
    grid.append(el("div", { class: "pool-empty" },
      el("p", { text: heroesError.message }),
      heroesError.hint && el("p", { class: "small", text: heroesError.hint }),
      el("button", { class: "btn bevel", type: "button", style: "margin-top:12px", onclick: loadHeroes }, icon("refresh"), "Retry"),
    ));
    return;
  }
  if (!heroes.length) {
    for (let i = 0; i < 18; i++) grid.append(el("div", { class: "hero bevel skel", "aria-hidden": "true", style: "min-height:84px" }));
    return;
  }

  const query = norm($("#hero-search").value);
  const matches = heroes.filter((name) => !query || norm(name).includes(query));
  if (!matches.length) {
    grid.append(el("p", { class: "pool-empty", text: `No hero matches "${$("#hero-search").value.trim()}".` }));
    return;
  }

  for (const name of matches) {
    const used = state.usedBy(name);
    const chip = el("button", {
      class: "hero bevel", type: "button", disabled: !!used, dataset: used ? { used } : {},
      "aria-label": used ? `${name}, already ${used === "ban" ? "banned" : used + " pick"}` : `${name}. Add to ${TEAM_LABEL[state.draft.target].toLowerCase()}`,
      onclick: () => addHero(name),
    }, portrait(name, { size: 44 }), el("span", { class: "h-name", text: name }));
    if (used) chip.append(el("span", { class: "used-mark", "aria-hidden": "true", text: USED_MARK[used] }));
    grid.append(chip);
  }
}

function renderSummary() {
  // Counts already live in each panel header; the only summary state left is
  // whether there is a draft to clear.
  $("#btn-clear").hidden = state.isEmpty();
}

// -------------------------------------------------------------- actions
function addHero(name, team = state.draft.target) {
  if (state.usedBy(name)) return;
  if (!state.add(team, name)) {
    toast(`${TEAM_LABEL[team]} is full (${LIMITS[team]}). Remove a hero to make room.`, { tone: "error" });
    return;
  }
  announce(`${name} added to ${TEAM_LABEL[team].toLowerCase()}`);
  renderAll();
}

function removeHero(team, name) {
  state.remove(team, name);
  announce(`${name} removed`);
  renderAll();
}

function clearDraft() {
  const previous = state.snapshot();
  state.clearAll();
  renderAll();
  toast("Draft cleared.", { action: "Undo", onAction: () => { state.restore(previous); buildAssign(); renderAll(); } });
}

function onSearchKey(event) {
  if (event.key === "Enter") {
    const first = $$(".hero:not(:disabled)", $("#pool-grid"))[0];
    if (first) { first.click(); $("#hero-search").select(); }
  } else if (event.key === "Escape") {
    event.target.value = "";
    renderPool();
  }
}

function onGlobalKey(event) {
  if (document.querySelector("#view-draft")?.hidden) return;
  const typing = /^(input|textarea|select)$/i.test(event.target.tagName) || event.target.isContentEditable;
  if (event.key === "/" && !typing) { event.preventDefault(); $("#hero-search").focus(); }
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); requestRecommendation(); }
}

// ------------------------------------------------------ recommendation
async function requestRecommendation() {
  if (running) return;
  running = true;
  const button = $("#btn-recommend");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  lastResult = { kind: "loading", startedAt: Date.now() };
  renderResults();
  $("#results").scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });

  const tick = setInterval(updateLoading, 1000);
  try {
    const data = await api.recommend(state.payload());
    lastResult = { kind: "result", data };
    announce(data.recommendation
      ? `Recommendation ready. Top pick ${data.recommendation.recommendations[0]?.hero ?? "none"}.`
      : "The agent could not produce a valid recommendation.");
  } catch (error) {
    lastResult = { kind: "error", error: error instanceof ApiError ? error : new ApiError(0, { message: String(error) }) };
    announce(`Recommendation failed. ${lastResult.error.message}`);
  } finally {
    clearInterval(tick);
    running = false;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    diagOpen = lastResult.kind === "result" && !lastResult.data.recommendation;
    diagTab = diagOpen ? "raw" : "live";
    renderResults(true);
  }
}

const TYPICAL_SECONDS = 30;

function updateLoading() {
  const node = $("#loading-ring");
  if (!node || lastResult?.kind !== "loading") return;
  const elapsed = Math.floor((Date.now() - lastResult.startedAt) / 1000);
  const circumference = 2 * Math.PI * 16;
  node.querySelector(".arc").style.strokeDashoffset = String(circumference * (1 - Math.min(elapsed / TYPICAL_SECONDS, 1)));
  node.querySelector("text").textContent = `${elapsed}s`;
  $("#loading-note").textContent = elapsed > TYPICAL_SECONDS
    ? "Taking longer than usual. The first request after a quiet spell loads the model, which can take a minute or more."
    : "A local model reads the live stats and your notes. This usually takes 15 to 30 seconds.";
}

function renderResults(justFinished = false) {
  const host = $("#results-body");
  const region = $("#results");
  clear(host);
  region.setAttribute("aria-busy", String(lastResult?.kind === "loading"));

  if (!lastResult) { host.append(emptyResults()); return; }
  if (lastResult.kind === "loading") { host.append(loadingView()); updateLoading(); return; }
  if (lastResult.kind === "error") { host.append(errorView(lastResult.error)); return; }
  host.append(resultView(lastResult.data, justFinished));
}

function emptyResults() {
  return el("div", { class: "empty" },
    icon("hex", "empty-mark"),
    el("h3", { text: "Ready when you are" }),
    el("p", { text: "Add the heroes already picked and banned, choose the lane you need, then request a recommendation. The agent reads live stats and your own notes, and shows you the evidence behind each pick." }),
    el("p", { class: "muted small" }, "Tip: type a name in the pool and press ", el("kbd", { text: "Enter" }), " to add it. ", el("kbd", { text: "Ctrl" }), " + ", el("kbd", { text: "Enter" }), " requests a recommendation."),
  );
}

function loadingView() {
  const circumference = 2 * Math.PI * 16;
  const ring = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  ring.setAttribute("viewBox", "0 0 40 40");
  ring.setAttribute("class", "ring");
  ring.setAttribute("id", "loading-ring");
  ring.setAttribute("aria-hidden", "true");
  ring.innerHTML = `<circle class="track" cx="20" cy="20" r="16"/><circle class="arc" cx="20" cy="20" r="16" stroke-dasharray="${circumference}" stroke-dashoffset="${circumference}"/><text x="20" y="24" text-anchor="middle">0s</text>`;

  return el("div", {},
    el("div", { class: "loading-row" }, ring,
      el("div", { class: "loading-copy" }, el("b", { text: "Working on your recommendation" }), el("span", { id: "loading-note", class: "muted small" }))),
    ...[1, 2].map((n) => el("div", { class: "skel-card bevel", "aria-hidden": "true" },
      el("div", { class: "skel skel-line", style: `width:${n === 1 ? 34 : 26}%;height:22px` }),
      el("div", { class: "skel skel-line", style: "width:90%" }),
      el("div", { class: "skel skel-line", style: "width:62%" }))),
  );
}

function errorView(error) {
  const actions = el("div", { class: "banner-actions" },
    el("button", { class: "btn bevel", type: "button", onclick: requestRecommendation }, icon("refresh"), "Try again"),
  );
  return el("div", {},
    el("div", { class: "banner banner-error bevel", role: "alert" },
      icon("alert"),
      el("div", { class: "banner-body" },
        el("strong", { text: error.message }),
        error.hint && el("p", { text: error.hint }),
        actions)),
    error.detail ? el("div", { class: "diag" }, el("pre", { tabindex: "0", text: error.detail })) : null,
  );
}

function resultView(data, justFinished) {
  const wrap = el("div", { class: justFinished ? "lock-in" : "" });
  const recommendation = data.recommendation;

  if (!recommendation) {
    wrap.append(el("div", { class: "banner banner-error bevel", role: "alert" },
      icon("alert"),
      el("div", { class: "banner-body" },
        el("strong", { text: "The agent couldn't produce a valid recommendation." }),
        el("p", { text: `It retried ${data.repair_attempts} time${data.repair_attempts === 1 ? "" : "s"}, but the model's output kept failing validation. That happens with small local models under load. Try again, or open the diagnostics to see what it returned.` }),
        el("div", { class: "banner-actions" },
          el("button", { class: "btn bevel", type: "button", onclick: requestRecommendation }, icon("refresh"), "Try again")))));
    wrap.append(diagnostics(data));
    return wrap;
  }

  const laneLabel = LANES.find((l) => l.value === data.role_needed)?.label ?? data.role_needed;
  const attempt = data.repair_attempts === 0 ? "valid on the first try" : `repaired after ${data.repair_attempts} ${data.repair_attempts === 1 ? "retry" : "retries"}`;

  wrap.append(
    el("div", { class: "results-head" },
      el("h2", { class: "panel-title", text: "Recommended picks" }),
      el("span", { class: "results-meta num", text: `${laneLabel} lane · ${data.elapsed_seconds}s · ${attempt}` })),
    recommendation.summary && el("p", { class: "results-summary", text: recommendation.summary }),
  );

  if (data.filtered_out.length) {
    wrap.append(el("div", { class: "banner banner-info bevel" },
      icon("info"),
      el("div", { class: "banner-body" },
        el("strong", { text: "Removed from the model's answer" }),
        el("p", { text: data.filtered_out.map((f) => `${f.hero} (${f.reason.toLowerCase()})`).join(", ") + ". These were caught by the draft rules, not shown as picks." }))));
  }

  if (!recommendation.recommendations.length) {
    wrap.append(el("div", { class: "banner banner-warn bevel" }, icon("alert"),
      el("div", { class: "banner-body" }, el("strong", { text: "Nothing left after the draft rules were applied." }),
        el("p", { text: "Every hero the model suggested was already used or ineligible for this lane. Try again." }))));
  }

  recommendation.recommendations.forEach((rec, index) => {
    wrap.append(index === 0 ? leadCard(rec, justFinished) : pickRow(rec, index + 1, justFinished));
  });
  wrap.append(diagnostics(data));
  return wrap;
}

function meter(score) {
  const filled = Math.round(score * 10);
  return el("span", {
    class: "meter-wrap", role: "img", "aria-label": `Priority ${Math.round(score * 100)} percent`,
    title: "The model's own ranking score for this pick. It is not a win probability.",
  },
    el("span", { class: "meter-label", "aria-hidden": "true", text: "Priority" }),
    el("span", { class: "meter", "aria-hidden": "true" }, ...Array.from({ length: 10 }, (_, i) => el("i", { class: i < filled ? "on" : "" }))),
    el("span", { class: "meter-pct num", "aria-hidden": "true", text: `${Math.round(score * 100)}%` }),
  );
}

function evidenceTags(rec) {
  if (!rec.evidence?.length) {
    return el("div", { class: "tags" }, el("span", { class: "tag tag-warn bevel" }, icon("alert"), "Model knowledge only. No live data or note backs this pick."));
  }
  return el("div", { class: "tags" }, ...rec.evidence.map((e) =>
    el("span", { class: "tag bevel" }, icon(EVIDENCE_ICON[e.kind] || "info"), e.label)));
}

function leadCard(rec, animate) {
  return el("article", { class: `lead bevel`, "aria-label": `Top pick: ${rec.hero}` },
    portrait(rec.hero, { size: 96, gold: true }),
    el("div", {},
      el("div", { class: "lead-top" }, el("h3", { class: "lead-name", text: rec.hero }), meter(rec.priority_score)),
      evidenceTags(rec),
      el("p", { class: "lead-rationale", text: rec.rationale })),
  );
}

function pickRow(rec, rank, animate) {
  return el("article", { class: `pick bevel`, "aria-label": `Pick ${rank}: ${rec.hero}` },
    el("span", { class: "rank-n", "aria-hidden": "true", text: rank }),
    portrait(rec.hero, { size: 48 }),
    el("div", { class: "pick-body" },
      el("div", { class: "pick-top" }, el("h3", { class: "pick-name", style: "margin:0", text: rec.hero }), meter(rec.priority_score)),
      evidenceTags(rec)),
    el("p", { class: "pick-rationale", text: rec.rationale }),
  );
}

// ---------------------------------------------------------- diagnostics
function diagnostics(data, forceOpen = false) {
  const open = diagOpen || forceOpen;
  const tabs = [
    { id: "live", label: "Live stats", text: [data.live_stats_summary, data.lane_filtered_stats && `\nLane-filtered:\n${data.lane_filtered_stats}`].filter(Boolean).join("\n") || "No live stats were gathered." },
    { id: "notes", label: "Notes retrieved", text: data.retrieved_notes || "No notes were retrieved." },
    { id: "raw", label: "Model output", text: [data.parse_error && `Validation error:\n${data.parse_error}\n`, data.raw_llm_output || "No output."].filter(Boolean).join("\n") },
  ];
  const active = tabs.find((t) => t.id === diagTab) || tabs[0];

  const panel = el("div", { class: "diag", id: "diag" });
  const toggle = el("button", {
    class: "diag-toggle", type: "button", "aria-expanded": String(open), "aria-controls": "diag-panel",
    onclick: () => { diagOpen = !diagOpen; renderResults(); },
  }, icon("eye"), "What the agent saw", icon("chevron", "chev"));
  panel.append(toggle);

  if (open) {
    const body = el("div", { id: "diag-panel" },
      el("div", { class: "diag-tabs", role: "group", "aria-label": "Diagnostics section" },
        ...tabs.map((t) => el("button", {
          class: "chip-btn bevel", type: "button", "aria-pressed": String(t.id === active.id),
          onclick: () => { diagTab = t.id; renderResults(); },
        }, t.label))),
      el("pre", { tabindex: "0", text: active.text }));
    panel.append(body);
  }
  return panel;
}
