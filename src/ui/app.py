import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from src.api_client.rone_arena_client import list_heroes, get_hero_rank_stats
from src.agents.draft_agent import get_draft_recommendation
from src.rag.add_note import add_note
from src.rag.ingest import run_ingestion
from src.rag.note_loader import GENERAL_DIR, HEROES_DIR, SUPPORTED_SUFFIXES

st.set_page_config(page_title="ML Draft Copilot", page_icon="", layout="wide")

LANE_OPTIONS = ["any", "jungle", "gold", "exp", "mid", "roam"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
META_WATCHER_PORT = 8765


@st.cache_data(ttl=1800, show_spinner=False)
def load_hero_names() -> list[str]:
    heroes = list_heroes(size=200)
    return sorted(h["name"] for h in heroes if h.get("name"))


@st.cache_data(ttl=600, show_spinner=False)
def load_current_meta(size: int = 10) -> list[dict]:
    return get_hero_rank_stats(days="7", size=size)


def list_all_notes() -> list[dict]:

    notes = []

    if GENERAL_DIR.exists():
        for path in sorted(GENERAL_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                notes.append({"path": path, "hero": None})

    if HEROES_DIR.exists():
        for hero_dir in sorted(HEROES_DIR.iterdir()):
            if not hero_dir.is_dir():
                continue
            for path in sorted(hero_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                    notes.append({"path": path, "hero": hero_dir.name})

    return notes


def is_meta_watcher_running(port: int = META_WATCHER_PORT, timeout: float = 1.0) -> bool:
    """
    Cheap TCP-connect check against the wrapper's port — avoids adding
    a `requests` dependency just for a health check, and works
    regardless of whether the process was started by this dashboard,
    a terminal, or n8n's own testing earlier — status here always
    reflects reality, not just "did I personally launch it."
    """
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


def start_meta_watcher() -> None:
    """
    Launch src/agents/meta_watcher_server.py as a background
    subprocess using the SAME python interpreter running this
    Streamlit process (sys.executable), so it shares the venv and
    picks up the same .env config. The Popen handle is stashed in
    session_state so a later Stop click (in the same dashboard
    session) can terminate it directly, without needing the
    port-kill fallback in stop_meta_watcher().
    """
    process = subprocess.Popen(
        [sys.executable, "-m", "src.agents.meta_watcher_server"],
        cwd=str(PROJECT_ROOT),
    )
    st.session_state["_meta_watcher_process"] = process

    # Give Flask a moment to actually bind the port before the caller
    # re-checks status — without this, a Start click followed
    # immediately by a status check would still show "stopped" even
    # though the process is happily starting up.
    for _ in range(10):
        if is_meta_watcher_running():
            break
        time.sleep(0.3)


def stop_meta_watcher() -> None:
    """
    Prefers terminating our own tracked subprocess handle (clean,
    portable). Falls back to a Windows-specific port-based kill if
    it's running but we have no handle for it — e.g. it was started
    manually in a terminal before this dashboard session existed, or
    a previous Streamlit rerun/restart lost the in-memory Popen
    reference. This project already assumes Windows throughout
    (run_dashboard.bat, the n8n/Docker setup notes), so a
    Windows-only fallback here is consistent, not a new constraint.
    """
    process = st.session_state.get("_meta_watcher_process")
    if process is not None and process.poll() is None:
        process.terminate()
        st.session_state.pop("_meta_watcher_process", None)
        return

    st.session_state.pop("_meta_watcher_process", None)
    if sys.platform == "win32":
        _kill_by_port_windows(META_WATCHER_PORT)


def _kill_by_port_windows(port: int) -> None:
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, check=False,
    )
    for line in result.stdout.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            pid = line.strip().split()[-1]
            subprocess.run(
                ["taskkill", "/PID", pid, "/F"], capture_output=True, check=False,
            )


@st.dialog("Edit note")
def edit_note_dialog(path: Path):
    """
    Modal popup for editing a note's raw text in place. Only wired up
    for .md/.txt notes (same set the sidebar can already preview) —
    editing PDF/DOCX content in a text box would mean rewriting the
    file in a completely different format than it was uploaded in,
    which isn't what "edit" should mean for those.
    """
    current_content = path.read_text(encoding="utf-8")
    new_content = st.text_area("Note content", value=current_content, height=300)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save", type="primary", use_container_width=True):
            path.write_text(new_content, encoding="utf-8")
            st.session_state["_note_notice"] = (
                f"Updated {path.name}. Rebuild the knowledge base to apply the change."
            )
            st.rerun()
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


def main():
    st.title("Mobile Legends Draft Copilot")
    st.caption("Live stats via tool-calling, strategic reasoning via RAG over "
               "your own notes, orchestrated with LangGraph. Runs fully locally.")

    try:
        hero_names = load_hero_names()
    except Exception as e:
        st.error(f"Couldn't load hero list from the Rone Arena API: {e}")
        hero_names = []

    # --- Sidebar: current meta + note management ---
    with st.sidebar:
        st.header("Current Meta")
        st.caption("Live win rates, last 7 days")
        try:
            meta = load_current_meta(size=8)
            for h in meta:
                st.write(f"**{h['name']}** — WR {h['win_rate']:.1%}, "
                         f"Pick {h['pick_rate']:.1%}, Ban {h['ban_rate']:.1%}")
        except Exception as e:
            st.caption(f"Couldn't load meta data: {e}")

        st.divider()

        st.header("Add Strategy Note")
        with st.form("add_note_form", clear_on_submit=True):
            note_text = st.text_area(
                "Note content",
                placeholder="e.g. Lolita's shield counters burst-heavy dive comps...",
            )
            note_hero = st.selectbox(
                "Tag to a specific hero (optional)",
                options=["(general note)"] + hero_names,
            )
            submitted = st.form_submit_button("Save note")

            if submitted and note_text.strip():
                hero_arg = None if note_hero == "(general note)" else note_hero
                path = add_note(note_text.strip(), hero=hero_arg)
                st.success(f"Saved to {path.name}. Rebuild the knowledge "
                           f"base below to include it in recommendations.")

        if st.button("Rebuild knowledge base", use_container_width=True):
            with st.spinner("Re-ingesting notes..."):
                run_ingestion()
            st.success("Knowledge base rebuilt.")

        st.divider()

        st.header("Meta-Watcher")
        st.caption("Local HTTP wrapper used by the n8n scheduling workflow "
                   "to trigger snapshot + drift checks.")
        watcher_running = is_meta_watcher_running()
        if watcher_running:
            st.caption(f"Status: \U0001F7E2 Running on port {META_WATCHER_PORT}")
            if st.button("Stop Meta-Watcher", use_container_width=True):
                with st.spinner("Stopping..."):
                    stop_meta_watcher()
                st.rerun()
        else:
            st.caption("Status: ⚪ Stopped")
            if st.button("Start Meta-Watcher", use_container_width=True):
                with st.spinner("Starting..."):
                    start_meta_watcher()
                st.rerun()

        st.divider()

        st.header("Browse Notes")

        if "_note_notice" in st.session_state:
            st.success(st.session_state.pop("_note_notice"))

        all_notes = list_all_notes()
        if not all_notes:
            st.caption("No notes yet. Add one above to get started.")
        else:
            note_labels = [
                f"[{n['hero'] if n['hero'] else 'General'}] {n['path'].name}"
                for n in all_notes
            ]
            selected_label = st.selectbox("Saved notes", options=note_labels)
            selected_note = all_notes[note_labels.index(selected_label)]

            selected_path = selected_note["path"]
            is_editable = selected_path.suffix.lower() in (".md", ".txt")
            if is_editable:
                st.text(selected_path.read_text(encoding="utf-8"))
            else:
                st.caption(f"Preview not available for {selected_path.suffix} "
                           f"files — open {selected_path} directly.")

            delete_confirm_key = f"confirm_delete::{selected_path}"

            if st.session_state.get(delete_confirm_key):
                st.warning(f"Delete {selected_path.name}? This cannot be undone.")
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Yes, delete", type="primary", use_container_width=True):
                        selected_path.unlink()
                        st.session_state.pop(delete_confirm_key, None)
                        st.session_state["_note_notice"] = (
                            f"Deleted {selected_path.name}. Rebuild the knowledge "
                            f"base to remove it from recommendations."
                        )
                        st.rerun()
                with cancel_col:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state.pop(delete_confirm_key, None)
                        st.rerun()
            else:
                edit_col, delete_col = st.columns(2)
                with edit_col:
                    if st.button("Edit note", use_container_width=True, disabled=not is_editable):
                        edit_note_dialog(selected_path)
                with delete_col:
                    if st.button("Delete note", use_container_width=True):
                        st.session_state[delete_confirm_key] = True
                        st.rerun()

    # --- Main: draft board ---
    st.subheader("Draft Board")

    col1, col2, col3 = st.columns(3)
    with col1:
        ally_picks = st.multiselect("Ally picks", options=hero_names)
    with col2:
        enemy_picks = st.multiselect("Enemy picks", options=hero_names)
    with col3:
        banned_heroes = st.multiselect("Banned heroes", options=hero_names)

    role_needed = st.selectbox("Lane needed", options=LANE_OPTIONS)

    if st.button("Get Draft Recommendation", type="primary"):
        with st.spinner("Consulting live stats, your notes, and the model... "
                         "(local inference can take a while)"):
            try:
                result = get_draft_recommendation(
                    ally_picks=ally_picks,
                    enemy_picks=enemy_picks,
                    banned_heroes=banned_heroes,
                    role_needed=role_needed,
                )
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                result = None

        if result:
            rec = result.get("parsed_recommendation")
            if rec:
                st.markdown(f"**Summary:** {rec['summary']}")
                st.divider()
                for r in rec["recommendations"]:
                    cols = st.columns([3, 1, 6])
                    cols[0].markdown(f"**{r['hero']}**")
                    cols[1].progress(r["priority_score"],
                                      text=f"{r['priority_score']:.0%}")
                    cols[2].write(r["rationale"])
            else:
                st.warning(
                    "The agent couldn't produce a valid recommendation after "
                    "retrying. This can happen with small local models under "
                    "load — try again, or check the details below."
                )
                with st.expander("Debug details"):
                    st.write("Parse error:", result.get("parse_error"))
                    st.write("Last raw output:", result.get("raw_llm_output"))

            with st.expander("What the agent saw (live stats + retrieved notes)"):
                st.text("Live stats summary:")
                st.code(result.get("live_stats_summary", ""), language=None)
                st.text("Retrieved notes:")
                st.code(result.get("retrieved_notes", ""), language=None)


if __name__ == "__main__":
    main()
