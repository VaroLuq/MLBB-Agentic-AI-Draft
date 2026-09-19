import { api } from "./api.js";
import { $, $$, icon } from "./ui.js";
import { initDraft } from "./draft.js";
import { initIntel } from "./intel.js";
import { initNotebook, showNotebook } from "./notebook.js";

const TITLES = { draft: "Draft", notebook: "Notebook" };

// Static markup declares icons as data-icon="name"; drawn here so the icon
// family stays defined in one place (icons.js).
$$("[data-icon]").forEach((node) => node.prepend(icon(node.dataset.icon)));

// ---------------------------------------------------------------- routing
function route(initial = false) {
  const view = location.hash === "#/notebook" ? "notebook" : "draft";
  for (const name of Object.keys(TITLES)) {
    $(`#view-${name}`).hidden = name !== view;
    const link = $(`#nav-${name}`);
    if (name === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${TITLES[view]} · Draft Copilot`;
  if (view === "notebook") showNotebook();
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

async function pollHealth() {
  let online = false;
  try {
    const health = await api.health();
    online = health.ollama;
    setModel(online ? "ok" : "warn", online ? "Ollama ready" : "Ollama offline",
      online ? `Model: ${health.model}` : "Start Ollama and this reconnects on its own. Recommendations need it.");
  } catch {
    setModel("warn", "Server unreachable", "The Draft Copilot server isn't responding. Restart run_dashboard.bat.");
  }
  setTimeout(pollHealth, online ? 20000 : 5000);
}

document.addEventListener("kb-state", (event) => { $("#chip-kb").hidden = !event.detail.stale; });
$("#chip-kb").addEventListener("click", () => { location.hash = "#/notebook"; });

// Learn the knowledge-base state up front so the header can flag it from any view.
api.notes().then((data) => { $("#chip-kb").hidden = !data.kb.stale; }).catch(() => {});

// ------------------------------------------------------------------- boot
initDraft();
initIntel();
initNotebook();
route(true);
pollHealth();
