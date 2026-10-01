import { api } from "./api.js";
import { $, $$, icon, toast } from "./ui.js";
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
// ------------------------------------------------------------ boot curtain
// Covers the app until warm-up finishes. Pointer events are blocked by the
// overlay itself; `inert` is what stops a keyboard user tabbing underneath it,
// which a full-bleed div alone does not prevent.
const boot = $("#boot");
let bootVisible = true;

function setBoot({ message, hint, notes, stats, tone }) {
  if (!bootVisible) return;
  if (message != null) $("#boot-msg").textContent = message;
  if (hint != null) $("#boot-hint").textContent = hint;
  if (tone != null) boot.dataset.tone = tone; else delete boot.dataset.tone;
  const step = (name, done) => {
    const node = boot.querySelector(`[data-step="${name}"]`);
    if (node) node.dataset.state = done ? "done" : "busy";
  };
  if (notes != null) step("notes", notes);
  if (stats != null) step("stats", stats);
}

function showBoot({ message, hint, steps = true, tone = null }) {
  bootVisible = true;
  boot.hidden = false;
  boot.classList.remove("is-done");
  $("#boot-steps").hidden = !steps;
  for (const node of document.querySelectorAll(".topbar, #main")) node.inert = true;
  setBoot({ message, hint, tone });
}

function hideBoot() {
  if (!bootVisible) return;
  bootVisible = false;
  for (const node of document.querySelectorAll(".topbar, #main")) node.inert = false;
  boot.classList.add("is-done");
  // `hidden` is what removes it from the layout and the a11y tree; the class
  // only fades it. Guarded on the event target because a child's own
  // transition would otherwise hide the curtain early.
  boot.addEventListener("transitionend", function done(event) {
    if (event.target !== boot) return;
    boot.removeEventListener("transitionend", done);
    boot.hidden = true;
  });
  // transitionend never fires if the element is already at the target opacity
  // (reduced-motion shortens transitions to 1ms), so do not rely on it alone.
  setTimeout(() => { if (!bootVisible) boot.hidden = true; }, 400);
}

for (const node of document.querySelectorAll(".topbar, #main")) node.inert = true;

let serverInstance = null;
// Set once the user deliberately shuts the server down. Without it the poll
// below would keep firing against a socket that is gone and report the
// intended outcome as "Server unreachable — restart run_dashboard.bat", which
// is both alarming and wrong advice for someone who just chose to stop it.
let stopped = false;

async function pollHealth() {
  if (stopped) return;
  let ready = false;
  try {
    const health = await api.health();
    serverInstance = health.instance ?? serverInstance;
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
    // The curtain tracks the same two flags the chip does, so it names what is
    // still outstanding instead of spinning anonymously.
    setBoot({
      message: ready ? "Ready" : "Warming up",
      notes: health.notes_ready,
      stats: health.stats_ready,
    });
    // Lifted on warm-up alone, deliberately NOT on jev_configured: a missing
    // API key is a permanent condition, and holding the curtain up for it
    // would lock the user out of the notebook and Meta-Watcher, which work
    // without Jev. The header chip reports the key separately.
    if (ready) hideBoot();
    document.dispatchEvent(new CustomEvent("agent-state",
      { detail: { ready: ready && health.jev_configured } }));
  } catch {
    setModel("warn", "Server unreachable", "The Draft Copilot server isn't responding. Restart run_dashboard.bat.");
    // Only while booting. Once the app is up, a transient health failure is
    // already reported by the chip and should not throw a curtain over work
    // in progress.
    setBoot({
      message: "Can't reach the app server",
      hint: "It may still be starting. If this persists, run run_dashboard.bat again.",
      tone: "error",
    });
    document.dispatchEvent(new CustomEvent("agent-state", { detail: { ready: false } }));
  }
  // Poll tightly while warming so the UI unlocks promptly, then back off.
  setTimeout(pollHealth, ready ? 30000 : 1500);
}

// ---------------------------------------------------------------- restart
// The old process must release the port before the replacement can take it,
// so the server exits itself and the child waits. From here that means the
// server goes away for a few seconds: poll until it answers again, then
// reload so the page is running the code that just started.
async function restartApp() {
  const button = $("#btn-restart");
  if (button.disabled) return;
  if (!confirm("Restart the app server? Any recommendation in progress will be lost.")) return;

  const previousInstance = serverInstance;
  button.disabled = true;
  setModel("busy", "Restarting", "Waiting for the app server to come back up.");
  // Curtain goes up immediately. The reload below lands on a server that is
  // still warming, so without this the board would be interactive for the
  // several seconds it takes the replacement to become usable. Steps are
  // hidden until the new process starts reporting them.
  showBoot({
    message: "Restarting the app server",
    hint: "The replacement waits for this one to release the port.",
    steps: false,
  });
  document.dispatchEvent(new CustomEvent("agent-state", { detail: { ready: false } }));
  try {
    await api.restart();
  } catch (error) {
    // A dropped connection here is expected — the server may exit before the
    // response lands. Only a real refusal (409 busy) should stop us.
    if (error?.status === 409) {
      button.disabled = false;
      hideBoot();  // refused, so the app is still live and must stay usable
      toast(`${error.message} ${error.hint ?? ""}`.trim(), { tone: "error" });
      pollHealth();
      return;
    }
  }
  // Wait for a DIFFERENT server, not merely a reachable one. The outgoing
  // process keeps answering for a moment after it accepts the request, so
  // "health responds" would reload us onto a socket that is about to close.
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    try {
      const health = await api.health();
      if (!previousInstance || health.instance !== previousInstance) {
        location.reload();
        return;
      }
    } catch { /* down between the two processes; keep waiting */ }
  }
  button.disabled = false;
  setModel("warn", "Restart timed out", "The server didn't come back. Check data/restart.log.");
  // Left the curtain up here on the first pass, which stranded the user behind
  // a "Restarting" screen with no way forward. Report it on the curtain and
  // keep polling — if the replacement does eventually answer, pollHealth lifts
  // it on its own.
  setBoot({
    message: "The server didn't come back",
    hint: "Check data/restart.log, or run run_dashboard.bat again.",
    tone: "error",
  });
  pollHealth();
}

// --------------------------------------------------------------- shutdown
// Unlike restart, this is a one-way door from the browser's point of view —
// nothing on the page can bring the server back. So the confirm names the
// command needed to start it again, and the end state is presented as done
// rather than broken.
async function shutdownApp() {
  const button = $("#btn-shutdown");
  if (button.disabled) return;
  if (!confirm("Shut down the app server?\n\nThe page will stop working. "
             + "Run run_dashboard.bat to start it again.")) return;

  button.disabled = true;
  // Set BEFORE the request, not after: a health poll landing during the await
  // would otherwise catch the dying socket and flash the unreachable error.
  stopped = true;
  $("#btn-restart").disabled = true;
  document.dispatchEvent(new CustomEvent("agent-state", { detail: { ready: false } }));

  try {
    await api.shutdown();
  } catch (error) {
    // A dropped connection is the expected case — the process exits before
    // the response can land. Only a real refusal means we are still running.
    if (error?.status === 409) {
      stopped = false;
      button.disabled = false;
      $("#btn-restart").disabled = false;
      toast(`${error.message} ${error.hint ?? ""}`.trim(), { tone: "error" });
      pollHealth();
      return;
    }
  }

  // Confirm it actually went down rather than asserting it. If health still
  // answers after a few seconds the exit failed, and saying "Stopped" then
  // would leave a running server the user believes is off.
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 600));
    try {
      await api.health();
    } catch {
      setModel("idle", "Stopped", "The app server has shut down. Run run_dashboard.bat to start it again.");
      // Curtain back up: nothing on the page works now, and a board that still
      // looks live invites clicks that fail with network errors.
      showBoot({
        message: "App server stopped",
        hint: "Run run_dashboard.bat to start it again.",
        steps: false,
        tone: "error",
      });
      return;
    }
  }
  stopped = false;
  button.disabled = false;
  $("#btn-restart").disabled = false;
  setModel("warn", "Still running", "The server did not shut down. Close its terminal window instead.");
  pollHealth();
}

$("#btn-restart").addEventListener("click", restartApp);
$("#btn-shutdown").addEventListener("click", shutdownApp);

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
