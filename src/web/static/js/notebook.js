import { api, ApiError } from "./api.js";
import { $, el, clear, icon, toast, announce, fmtDate } from "./ui.js";
import { portrait } from "./heroes.js";
import { renderMarkdown } from "./md.js";
import { getHeroes } from "./draft.js";

let notes = [];
let kbStale = false;
let rebuilding = false;
let filter = "all"; // "all" | "general" | "hero:<Name>"
let selectedId = null;
let selected = null; // full note (with content) for the reader
let readerError = null;
let confirmingDelete = false;
let loaded = false;

export function initNotebook() {
  $("#btn-new-note").addEventListener("click", () => openEditor());
  const dialog = $("#note-dialog");
  let pressedOnBackdrop = false;
  dialog.addEventListener("mousedown", (e) => { pressedOnBackdrop = e.target === dialog; });
  dialog.addEventListener("click", (e) => { if (e.target === dialog && pressedOnBackdrop) dialog.close(); });
}

/** Called each time the Notebook view is shown. */
export async function showNotebook() {
  await loadNotes({ keepSelection: loaded });
  loaded = true;
}

export const isKbStale = () => kbStale;

// ------------------------------------------------------------------ data
async function loadNotes({ keepSelection = true } = {}) {
  try {
    const data = await api.notes();
    notes = data.notes;
    setKbStale(data.kb.stale);
  } catch (error) {
    notes = [];
    clear($("#note-list"));
    $("#note-list").append(el("li", {}, bannerError(error, () => loadNotes({ keepSelection: false }))));
    renderFilters();
    return;
  }

  if (!keepSelection || !notes.some((n) => n.id === selectedId)) {
    selectedId = visibleNotes()[0]?.id ?? null;
  }
  renderFilters();
  renderList();
  await loadSelected();
}

async function loadSelected() {
  confirmingDelete = false;
  readerError = null;
  selected = null;
  if (!selectedId) { renderReader(); return; }
  renderReader(true);
  try {
    selected = await api.note(selectedId);
  } catch (error) {
    readerError = error;
    if (error.code === "not_found") { await loadNotes({ keepSelection: false }); return; }
  }
  renderReader();
}

function setKbStale(value) {
  kbStale = value;
  renderKbBanner();
  document.dispatchEvent(new CustomEvent("kb-state", { detail: { stale: value } }));
}

const visibleNotes = () => notes.filter((n) => {
  if (filter === "all") return true;
  if (filter === "general") return !n.hero;
  return n.hero === filter.slice(5);
});

// ------------------------------------------------------------- rendering
function bannerError(error, retry) {
  return el("div", { class: "banner banner-error bevel", role: "alert" }, icon("alert"),
    el("div", { class: "banner-body" }, el("strong", { text: error.message }), error.hint && el("p", { text: error.hint }),
      el("div", { class: "banner-actions" }, el("button", { class: "btn bevel", type: "button", onclick: retry }, icon("refresh"), "Retry"))));
}

function renderKbBanner() {
  const host = $("#kb-banner");
  clear(host);
  host.hidden = !kbStale && !rebuilding;
  if (host.hidden) return;

  host.append(el("div", { class: "banner banner-warn bevel kb-banner" }, icon("alert"),
    el("div", { class: "banner-body" },
      el("strong", { text: rebuilding ? "Rebuilding the knowledge base" : "Your notes and the knowledge base may be out of step" }),
      el("p", { text: rebuilding
        ? "Re-reading every note and re-indexing it. This takes about 15 seconds."
        : "The agent only sees notes as they were at the last rebuild. Rebuild to apply your latest additions, edits and deletions." }),
      !rebuilding && el("div", { class: "banner-actions" },
        el("button", { class: "btn bevel", type: "button", onclick: rebuild }, icon("refresh"), "Rebuild knowledge base")))));
}

async function rebuild() {
  if (rebuilding) return;
  rebuilding = true;
  renderKbBanner();
  try {
    const result = await api.rebuildKb();
    notes = result.notes;
    toast(`Knowledge base rebuilt from ${result.note_count} note${result.note_count === 1 ? "" : "s"}.`, { tone: "ok" });
    announce("Knowledge base rebuilt");
    rebuilding = false;
    setKbStale(result.kb.stale);
  } catch (error) {
    rebuilding = false;
    renderKbBanner();
    toast(`${error.message} ${error.hint}`.trim(), { tone: "error", timeout: 9000 });
  }
}

function renderFilters() {
  const host = $("#nb-filters");
  clear(host);
  const heroNames = [...new Set(notes.filter((n) => n.hero).map((n) => n.hero))].sort((a, b) => a.localeCompare(b));
  const options = [
    { key: "all", label: "All", count: notes.length },
    { key: "general", label: "General", count: notes.filter((n) => !n.hero).length },
    ...heroNames.map((name) => ({ key: `hero:${name}`, label: name, count: notes.filter((n) => n.hero === name).length })),
  ];
  for (const option of options) {
    if (option.key === "general" && !option.count) continue;
    host.append(el("button", {
      class: "chip-btn bevel", type: "button", "aria-pressed": String(filter === option.key),
      onclick: () => setFilter(option.key),
    }, option.label, el("span", { class: "count", text: option.count })));
  }
  host.hidden = notes.length < 2;
}

async function setFilter(key) {
  filter = key;
  const visible = visibleNotes();
  if (!visible.some((n) => n.id === selectedId)) selectedId = visible[0]?.id ?? null;
  renderFilters();
  renderList();
  await loadSelected();
}

function renderList() {
  const list = $("#note-list");
  clear(list);
  const visible = visibleNotes();

  if (!notes.length) {
    list.append(el("li", { class: "muted small", style: "padding:6px 2px" }, "Nothing here yet."));
    return;
  }
  for (const note of visible) {
    const lead = note.hero ? portrait(note.hero, { size: 36 }) : el("span", { class: "general-badge portrait bevel", "aria-hidden": "true" }, icon("hex"));
    list.append(el("li", {}, el("button", {
      class: "note-row bevel", type: "button", "aria-current": String(note.id === selectedId),
      onclick: () => { selectedId = note.id; renderList(); loadSelected(); },
    }, lead,
      el("span", {},
        el("span", { class: "note-title", text: note.title }),
        note.snippet && el("span", { class: "note-snip", text: note.snippet }),
        el("span", { class: "note-date num", text: `${note.hero ?? "General"} · ${fmtDate(note.updated)}` })))));
  }
}

function renderReader(loading = false) {
  const host = $("#note-reader");
  clear(host);

  if (!notes.length) {
    host.append(el("div", { class: "empty" },
      icon("book", "empty-mark"),
      el("h3", { text: "No notes yet" }),
      el("p", { text: "Notes are how your own drafting judgment reaches the model. Write down a matchup you know cold, a counter that keeps working, or a rule you draft by, and the agent will weigh it when it's relevant." }),
      el("button", { class: "btn btn-primary bevel", type: "button", onclick: () => openEditor() }, icon("plus"), "Write your first note")));
    return;
  }
  if (!selectedId) {
    host.append(el("div", { class: "empty" }, icon("book", "empty-mark"), el("h3", { text: "Nothing in this filter" }),
      el("p", { text: "Pick another hero above, or show all notes." })));
    return;
  }
  if (loading) {
    host.append(el("div", { class: "skel", style: "height:34px;width:55%;margin-bottom:14px" }), el("div", { class: "skel", style: "height:14px;width:90%;margin-bottom:10px" }), el("div", { class: "skel", style: "height:14px;width:70%" }));
    return;
  }
  if (readerError) { host.append(bannerError(readerError, loadSelected)); return; }
  if (!selected) return;

  const note = selected;
  const edited = new Date(note.updated) - new Date(note.created) > 60_000;

  host.append(el("div", { class: "reader-head" },
    el("div", {},
      el("h2", { class: "reader-title", text: note.title }),
      el("div", { class: "reader-meta" },
        el("span", { class: "tag tag-hero bevel", text: note.hero ?? "General" }),
        el("span", { class: "num", text: `Added ${fmtDate(note.created)}${edited ? ` · edited ${fmtDate(note.updated)}` : ""}` }))),
    readerActions(note)));

  if (note.editable) {
    host.append(renderMarkdown(note.content, { hideHeadings: [note.title], hideGeneric: true }));
  } else {
    host.append(el("div", { class: "banner banner-info bevel" }, icon("info"),
      el("div", { class: "banner-body" },
        el("strong", { text: `Preview isn't available for ${note.suffix} files.` }),
        el("p", { text: `The agent still reads it. Open data/raw/${note.id} to view it directly.` }))));
  }
}

function readerActions(note) {
  if (confirmingDelete) {
    return el("div", { class: "confirm", role: "alert" },
      el("span", { text: "Delete this note? This can't be undone." }),
      el("button", { class: "btn btn-danger bevel", type: "button", onclick: () => deleteNote(note) }, icon("trash"), "Yes, delete"),
      el("button", { class: "btn btn-quiet bevel", type: "button", onclick: () => { confirmingDelete = false; renderReader(); } }, "Cancel"));
  }
  return el("div", { class: "reader-actions" },
    el("button", {
      class: "btn bevel", type: "button", disabled: !note.editable,
      title: note.editable ? "" : "Only .md and .txt notes can be edited here.", onclick: () => openEditor(note),
    }, icon("pencil"), "Edit"),
    el("button", { class: "btn btn-quiet bevel", type: "button", onclick: () => { confirmingDelete = true; renderReader(); } }, icon("trash"), "Delete"));
}

async function deleteNote(note) {
  try {
    const data = await api.deleteNote(note.id);
    notes = data.notes;
    setKbStale(data.kb.stale);
    toast(`Deleted "${note.title}".`);
    announce("Note deleted");
    selectedId = null;
    if (filter !== "all" && filter !== "general" && !notes.some((n) => n.hero === filter.slice(5))) filter = "all";
    selectedId = visibleNotes()[0]?.id ?? null;
    renderFilters(); renderList(); await loadSelected();
  } catch (error) {
    confirmingDelete = false;
    toast(`${error.message} ${error.hint}`.trim(), { tone: "error" });
    if (error.code === "not_found") await loadNotes({ keepSelection: false });
    else renderReader();
  }
}

// ---------------------------------------------------------------- dialog
function openEditor(note = null) {
  const dialog = $("#note-dialog");
  clear(dialog);
  const creating = !note;
  const heroes = getHeroes();

  const errorBox = el("p", { class: "field-error", id: "nf-error", role: "alert", hidden: true });
  const textarea = el("textarea", {
    class: "field", id: "nf-text", rows: "10", required: true,
    placeholder: creating ? "e.g. Lolita's shield counters burst-heavy dive comps..." : "",
    "aria-describedby": "nf-error",
  });
  textarea.value = creating ? "" : note.content;

  const heroSelect = creating && el("div", {},
    el("label", { class: "field-label", for: "nf-hero", text: "Hero (optional)" }),
    el("select", { class: "field", id: "nf-hero" },
      el("option", { value: "", text: "General note, not tied to a hero" }),
      ...heroes.map((name) => el("option", { value: name, text: name }))),
    !heroes.length && el("p", { class: "hint", text: "The hero list couldn't be loaded, so this will be saved as a general note." }));

  const save = el("button", { class: "btn btn-primary bevel", type: "submit" }, icon("check"), creating ? "Save note" : "Save changes");

  const form = el("form", { class: "modal-inner bevel", method: "dialog", novalidate: true, "aria-labelledby": "nf-title" },
    el("h2", { class: "panel-title", id: "nf-title", style: "font-size:1.5rem", text: creating ? "New note" : `Edit: ${note.title}` }),
    heroSelect,
    el("div", {}, el("label", { class: "field-label", for: "nf-text", text: "Note" }), textarea, errorBox,
      el("p", { class: "hint" }, "Plain text or Markdown. ", el("kbd", { text: "Ctrl" }), " + ", el("kbd", { text: "Enter" }), " saves.")),
    el("div", { class: "modal-actions" },
      el("button", { class: "btn btn-quiet bevel", type: "button", onclick: () => dialog.close() }, "Cancel"), save));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = textarea.value.trim();
    if (!text) {
      errorBox.textContent = "Write something first. An empty note can't be saved.";
      errorBox.hidden = false;
      textarea.focus();
      return;
    }
    errorBox.hidden = true;
    save.disabled = true;
    try {
      let data;
      if (creating) {
        const hero = form.querySelector("#nf-hero")?.value || null;
        data = await api.createNote(text, hero);
        selectedId = data.id;
        filter = "all";
      } else {
        data = await api.updateNote(note.id, textarea.value);
      }
      notes = data.notes;
      setKbStale(data.kb.stale);
      dialog.close();
      toast(creating ? "Note saved." : "Changes saved.", { tone: "ok" });
      announce(creating ? "Note saved" : "Changes saved");
      renderFilters(); renderList(); await loadSelected();
    } catch (error) {
      errorBox.textContent = `${error.message} ${error.hint}`.trim();
      errorBox.hidden = false;
      save.disabled = false;
    }
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); form.requestSubmit(); }
  });

  dialog.append(form);
  dialog.showModal();
  (creating ? form.querySelector("#nf-hero") ?? textarea : textarea).focus();
}
