import { api } from "./api.js";
import { $, $$, icon } from "./ui.js";
import { loadPortraits } from "./heroes.js";
import { initDraft } from "./draft.js";
import { initIntel } from "./intel.js";
import { initNotebook, showNotebook } from "./notebook.js";
import { initMetaWatcher, showMetaWatcher } from "./metawatcher.js";

const TITLES = { draft: "Draft", notebook: "Notebook", metawatcher: "Meta-Watcher" };

// Static markup declares icons as data-icon="name"; drawn here so the icon
// family stays defined in one place (icons.js).
$$("[data-icon]").forEach((node) => node.prepend(icon(node.dataset.icon)));

// ---------------------------------------------------------------- routing
function route(initial = false) {
  const view = location.hash === "#/notebook" ? "notebook"
    : location.hash === "#/meta-watcher" ? "metawatcher"
    : "draft";
  for (const name of Object.keys(TITLES)) {
    $(`#view-${name}`).hidden = name !== view;
    const link = $(`#nav-${name}`);
    if (name === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${TITLES[view]} · Draft Copilot`;
  if (view === "notebook") showNotebook();
  if (view === "metawatcher") showMetaWatcher();
  if (!initial) {
    window.scrollTo(0, 0);
    $(`#view-${view} h1`).focus({ preventScroll: true }); // land keyboard/screen-reader users on the new view
  }
}
window.addEventListener("hashchange", () => route());

// ----------------------------------------------------------- header status
function setModel(tone, text, title) {
  $("#chip-llm .lamp").dataset.tone = tone;
  $("#llm-text").textContent = text;
  $("#chip-llm").title = title;
}

// The chip reports warm-up, not a local model. Loading the note index and
// pre-fetching the current stats takes ~20s after launch, and a recommendation
// requested before that finishes blocks on it — so the state has to be visible
// rather than something the user discovers by waiting.
async function pollHealth() {
  let ready = false;
  try {
    const health = await api.health();
    ready = health.ready;
    if (!health.jev_configured) {
      setModel("warn", "No API key",
        "OPEN_JEV_KEY is missing from .env. Recommendations can't run without it.");
    } else if (ready) {
      setModel("ok", "Ready", `Notes indexed and current stats loaded. Ranking model: ${health.model}.`);
    } else {
      const waiting = [!health.notes_ready && "note index", !health.stats_ready && "live stats"]
        .filter(Boolean).join(" and ");
      setModel("busy", "Warming up", `Loading the ${waiting}. This takes about 20 seconds after launch.`);
    }
    document.dispatchEvent(new CustomEvent("agent-state",
      { detail: { ready: ready && health.jev_configured } }));
  } catch {
    setModel("warn", "Server unreachable", "The Draft Copilot server isn't responding. Restart run_dashboard.bat.");
    document.dispatchEvent(new CustomEvent("agent-state", { detail: { ready: false } }));
  }
  // Poll tightly while warming so the UI unlocks promptly, then back off.
  setTimeout(pollHealth, ready ? 30000 : 1500);
}

document.addEventListener("kb-state", (event) => { $("#chip-kb").hidden = !event.detail.stale; });
$("#chip-kb").addEventListener("click", () => { location.hash = "#/notebook"; });

// Learn the knowledge-base state up front so the header can flag it from any view.
api.notes().then((data) => { $("#chip-kb").hidden = !data.kb.stale; }).catch(() => {});

// ------------------------------------------------------------------- boot
// Portraits first: the manifest is a local file, and having it in hand before
// the first render avoids every portrait painting as initials and then
// swapping. `finally` so a missing manifest still boots the app.
loadPortraits().finally(() => {
  initDraft();
  initIntel();
  initNotebook();
  initMetaWatcher();
  route(true);
  pollHealth();
});
