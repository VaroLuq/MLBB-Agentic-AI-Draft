import { api } from "./api.js";
import { $, el, clear, icon, toast, relTime, pct, announce } from "./ui.js";
import { portrait } from "./heroes.js";

const METRIC = { win_rate: "win rate", pick_rate: "pick rate", ban_rate: "ban rate" };

let watcher = null;
let watcherError = null;
let busy = false; // a start/stop request is in flight
let pollTimer = null;

export function initIntel() {
  $("#intel-refresh").addEventListener("click", loadMeta);
  loadMeta();
  refreshWatcher();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshWatcher(); });
}

// ------------------------------------------------------------------ meta
async function loadMeta() {
  const list = $("#intel-list");
  clear(list);
  for (let i = 0; i < 8; i++) {
    list.append(el("li", { class: "intel-row", "aria-hidden": "true" },
      el("span"), el("span", { class: "skel", style: "width:30px;height:30px" }),
      el("span", { class: "skel", style: "height:14px;width:70%" }), el("span", { class: "skel", style: "height:14px;width:42px" })));
  }
  try {
    const { heroes } = await api.meta(8);
    clear(list);
    heroes.forEach((hero, index) => {
      list.append(el("li", { class: "intel-row" },
        el("span", { class: "r-num", "aria-hidden": "true", text: index + 1 }),
        portrait(hero.name, { size: 30 }),
        el("span", { class: "r-name" }, hero.name,
          el("span", { class: "r-sub", text: `Pick ${pct(hero.pick_rate)} · Ban ${pct(hero.ban_rate)}` })),
        el("span", { class: "r-wr", "aria-label": `Win rate ${pct(hero.win_rate)}`, text: pct(hero.win_rate) })));
    });
  } catch (error) {
    clear(list);
    list.append(el("li", {},
      el("div", { class: "banner banner-warn bevel", role: "alert", style: "margin:10px 0 0" }, icon("alert"),
        el("div", { class: "banner-body" }, el("strong", { text: error.message }),
          error.hint && el("p", { text: error.hint }),
          el("div", { class: "banner-actions" }, el("button", { class: "btn bevel", type: "button", onclick: loadMeta }, icon("refresh"), "Retry"))))));
  }
}

// ---------------------------------------------------------- meta-watcher
async function refreshWatcher() {
  clearTimeout(pollTimer);
  try {
    watcher = await api.watcher();
    watcherError = null;
  } catch (error) {
    watcherError = error;
  }
  renderWatcher();
  // Poll quickly while it's coming up, lazily otherwise; pause when the tab is hidden.
  const delay = watcher?.starting || busy ? 2000 : 8000;
  pollTimer = setTimeout(() => { if (!document.hidden) refreshWatcher(); else pollTimer = setTimeout(refreshWatcher, delay); }, delay);
}

async function toggleWatcher() {
  if (busy || !watcher) return;
  const starting = !watcher.running && !watcher.starting;
  busy = true;
  renderWatcher();
  try {
    watcher = starting ? await api.startWatcher() : await api.stopWatcher();
    announce(starting ? "Meta-Watcher starting" : "Meta-Watcher stopped");
    if (!starting) toast("Meta-Watcher stopped.");
  } catch (error) {
    toast(`${error.message} ${error.hint}`.trim(), { tone: "error" });
  } finally {
    busy = false;
    refreshWatcher();
  }
}

function stateLine() {
  if (watcherError) return { tone: "warn", text: "Status unavailable" };
  if (!watcher) return { tone: "idle", text: "Checking..." };
  if (watcher.running) return { tone: "ok", text: `Running on port ${watcher.port}` };
  if (watcher.starting || busy) return { tone: "busy", text: "Starting up" };
  return { tone: "idle", text: "Stopped" };
}

function renderWatcher() {
  const host = $("#watcher");
  clear(host);
  const { tone, text } = stateLine();
  const running = watcher?.running;
  const starting = watcher?.starting || (busy && !running);

  host.append(
    el("div", { class: "watch-state" }, el("span", { class: "lamp", dataset: { tone }, "aria-hidden": "true" }), el("span", { text })),
    el("button", {
      class: `btn bevel ${running ? "btn-danger" : ""}`, type: "button", disabled: busy || !watcher || (starting && !running), onclick: toggleWatcher,
      style: "width:100%",
    }, icon("power"), running ? "Stop Meta-Watcher" : starting ? "Starting..." : "Start Meta-Watcher"),
  );

  if (starting) {
    host.append(el("p", { class: "watch-meta", text: "If the last snapshot is stale it takes a fresh one before it starts listening, which can take a little while." }));
  }

  if (watcherError) {
    host.append(el("p", { class: "watch-meta", text: `${watcherError.message} ${watcherError.hint}`.trim() }));
    return;
  }
  if (!watcher) return;

  const { count, latest_taken_at: latest, drift } = watcher.snapshots;
  if (!count) {
    host.append(el("p", { class: "watch-meta", text: "No snapshots yet. Starting the Meta-Watcher takes the first one." }));
    return;
  }

  host.append(el("p", { class: "watch-meta num", text: `${count} snapshot${count === 1 ? "" : "s"} · latest ${relTime(latest)}` }));

  if (!drift) {
    host.append(el("p", { class: "watch-meta", text: "Drift shows once there are two snapshots to compare." }));
  } else if (!drift.total) {
    host.append(el("p", { class: "watch-meta", text: "No hero moved 2 points or more since the previous snapshot." }));
  } else {
    host.append(
      el("p", { class: "watch-meta", style: "margin-top:14px", text: `Biggest moves since the previous snapshot (${relTime(drift.from)}):` }),
      el("ul", { class: "moves" }, ...drift.moves.slice(0, 3).map((move) => {
        const points = move.delta * 100;
        return el("li", {},
          icon(move.direction === "up" ? "up" : "down", move.direction),
          el("span", {}, el("b", { text: move.hero }), " ", el("span", { class: "m-what", text: METRIC[move.metric] ?? move.metric })),
          el("span", { class: `m-delta num ${move.direction}`, text: `${points > 0 ? "+" : "-"}${Math.abs(points).toFixed(1)} pts` }));
      })),
    );
  }
}
