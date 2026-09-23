"""
Local web app for the Draft Copilot: a Flask JSON API wrapped around the
unchanged agent / RAG / Meta-Watcher modules, plus the static frontend in
src/web/static/. It replaces the earlier Streamlit dashboard.

Run with:  python -m src.web.server [--open]     (or double-click run_dashboard.bat)

Security posture: this API can delete note files and launch a subprocess,
so unlike the Meta-Watcher wrapper (which must bind 0.0.0.0 for Docker's
host.docker.internal) it binds to loopback only, rejects requests whose
Host header isn't loopback (DNS-rebinding), and requires a custom header
on every state-changing request (a cross-origin page can't set one
without a CORS preflight, which we never grant).
"""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.chdir(PROJECT_ROOT)  # the RAG/snapshot modules use cwd-relative data paths

from src.api_client.rone_arena_client import list_heroes, get_hero_rank_stats  # noqa: E402
from src.rag.add_note import add_note  # noqa: E402
from src.web import notes_store, watcher_control, evidence  # noqa: E402

DEFAULT_PORT = 8600
LANES = ["any", "jungle", "gold", "exp", "mid", "roam"]
MAX_LIST = 12  # generous cap per draft list; the UI enforces the real slot limits

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.json.sort_keys = False

_recommend_lock = threading.Lock()
_rebuild_lock = threading.Lock()
_agent_ready = threading.Event()

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, loader):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = loader()  # network call, deliberately outside the lock
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _error(code: str, message: str, hint: str = "", status: int = 400, **extra):
    return jsonify({"error": {"code": code, "message": message, "hint": hint, **extra}}), status


# --- Request guards ------------------------------------------------------

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


@app.before_request
def _guard():
    host = request.host
    hostname = host[: host.index("]") + 1] if host.startswith("[") else host.split(":")[0]
    if hostname not in _LOOPBACK_HOSTS:
        return _error("bad_host", "This app only answers on localhost.", status=403)
    if request.method in {"POST", "PUT", "DELETE"}:
        if request.headers.get("X-Requested-With") != "draft-copilot":
            return _error("forbidden", "Missing request header.", status=403)


# --- Static frontend -----------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# --- Health --------------------------------------------------------------

def _ollama_online() -> bool:
    import requests

    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        return requests.get(f"{base}/api/tags", timeout=1.5).ok
    except requests.RequestException:
        return False


@app.get("/api/health")
def health():
    return jsonify({
        "ollama": _ollama_online(),
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        "agent_ready": _agent_ready.is_set(),
    })


def _warm_agent() -> None:
    """Import the agent stack and load the embedding model in the background,
    so the first recommendation doesn't pay the multi-second import cost."""
    try:
        from src.agents import draft_agent  # noqa: F401
        from src.rag.vectorstore import get_vectorstore

        get_vectorstore()
    except Exception as exc:  # warming is best-effort; real errors surface on use
        print(f"[warmup] agent warm-up failed (will retry on first use): {exc}")
    finally:
        _agent_ready.set()


# --- Live stats ----------------------------------------------------------

@app.get("/api/heroes")
def heroes():
    try:
        names = _cached("heroes", 1800, lambda: sorted(
            h["name"] for h in list_heroes(size=200) if h.get("name")
        ))
    except Exception as exc:
        return _error(
            "stats_unreachable", "Couldn't load the hero list from the Rone Arena API.",
            "Check your connection, then retry. If you see an SSL certificate error, "
            "see Troubleshooting in the README.", 502, detail=str(exc)[:300],
        )
    return jsonify({"heroes": names})


@app.get("/api/meta")
def meta():
    size = min(max(request.args.get("size", 8, type=int), 1), 20)
    try:
        # use_cache=False: this endpoint backs the "Refresh live intel" button,
        # which is an explicit "show me current data" action. It keeps its own
        # 600s TTL; layering the client's hour-long cache underneath would mean
        # refresh could hand back data up to an hour old.
        rows = _cached(f"meta:{size}", 600,
                       lambda: get_hero_rank_stats(days="7", size=size, use_cache=False))
    except Exception as exc:
        return _error(
            "stats_unreachable", "Couldn't load the current meta.",
            "Check your connection, then retry.", 502, detail=str(exc)[:300],
        )
    return jsonify({"days": 7, "heroes": rows})


# --- Recommendations -----------------------------------------------------

def _hero_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{field} must be a list of hero names.")
    cleaned = []
    for name in value:
        name = name.strip()
        if name and name.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(name)
    if len(cleaned) > MAX_LIST:
        raise ValueError(f"{field} has too many heroes.")
    return cleaned


# _filtered_out() was removed alongside the LLM. It reported heroes that the
# model had recommended and the deterministic filters then stripped; with Jev
# scoring a candidate list that is already lane-filtered and free of used
# heroes, nothing is ever stripped after the fact, so the field had no content
# to carry.


@app.post("/api/recommend")
def recommend():
    body = request.get_json(silent=True) or {}
    try:
        ally = _hero_list(body.get("ally_picks"), "ally_picks")
        enemy = _hero_list(body.get("enemy_picks"), "enemy_picks")
        banned = _hero_list(body.get("banned_heroes"), "banned_heroes")
    except ValueError as exc:
        return _error("bad_request", str(exc))
    role = str(body.get("role_needed") or "any").lower()
    if role not in LANES:
        return _error("bad_request", f"role_needed must be one of: {', '.join(LANES)}.")

    if not _recommend_lock.acquire(blocking=False):
        return _error("busy", "A recommendation is already running.",
                      "Wait for it to finish, then request again.", 409)
    try:
        from src.agents.draft_agent import get_draft_recommendation

        started = time.monotonic()
        result = get_draft_recommendation(
            ally_picks=ally, enemy_picks=enemy, banned_heroes=banned, role_needed=role,
        )
        elapsed = round(time.monotonic() - started, 1)
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "not found" in lowered and "model" in lowered:
            model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
            return _error("model_missing", f"The model '{model}' isn't installed in Ollama.",
                          f"Run `ollama pull {model}`, then try again.", 502, detail=message[:300])
        if any(s in lowered for s in ("refused", "connecterror", "10061", "11434", "connection")):
            return _error("llm_unreachable", "Can't reach the local model.",
                          "Start Ollama, then try again.", 502, detail=message[:300])
        return _error("agent_failed", "The agent hit an unexpected error.",
                      "Try again; if it keeps happening, check the server console.",
                      500, detail=message[:300])
    finally:
        _recommend_lock.release()

    result["role_needed"] = role
    parsed = result.get("parsed_recommendation")
    live = result.get("live_stats_summary", "")
    notes = result.get("retrieved_notes", "")

    if parsed:
        for rec in parsed["recommendations"]:
            rec["evidence"] = evidence.evidence_for(rec["hero"], live, notes)

    return jsonify({
        "recommendation": parsed,
        "jev_error": result.get("jev_error"),
        "jev_raw": result.get("jev_raw"),
        "live_stats_summary": live,
        "lane_filtered_stats": result.get("lane_filtered_stats_text"),
        "lane_filtered_aggregate": result.get("lane_filtered_aggregate") or [],
        "retrieved_notes": notes,
        "elapsed_seconds": elapsed,
        "role_needed": role,
    })


# --- Notes ---------------------------------------------------------------

def _notes_payload():
    return {"notes": notes_store.list_notes(), "kb": {"stale": notes_store.kb_is_stale()}}


@app.get("/api/notes")
def notes_list():
    return jsonify(_notes_payload())


@app.get("/api/notes/<path:note_id>")
def notes_read(note_id):
    try:
        return jsonify(notes_store.read_note(note_id))
    except notes_store.NoteNotFound:
        return _error("not_found", "That note no longer exists.",
                      "It may have been deleted; the list has been refreshed.", 404)


@app.post("/api/notes")
def notes_create():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return _error("bad_request", "A note needs some text.")
    try:
        hero = notes_store.validate_hero(body.get("hero"))
    except notes_store.InvalidHero as exc:
        return _error("bad_request", str(exc))
    path = add_note(text, hero=hero)
    return jsonify({"id": path.relative_to(notes_store.RAW_DIR).as_posix(), **_notes_payload()}), 201


@app.put("/api/notes/<path:note_id>")
def notes_update(note_id):
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error("bad_request", "A note can't be saved empty.",
                      "Delete the note instead if you no longer want it.")
    try:
        notes_store.write_note(note_id, content)
    except notes_store.NoteNotFound:
        return _error("not_found", "That note no longer exists.", status=404)
    except notes_store.NoteNotEditable:
        return _error("not_editable", "This file type can't be edited here.",
                      "Only .md and .txt notes can be edited in the app.", 400)
    return jsonify(_notes_payload())


@app.delete("/api/notes/<path:note_id>")
def notes_delete(note_id):
    try:
        notes_store.delete_note(note_id)
    except notes_store.NoteNotFound:
        return _error("not_found", "That note no longer exists.", status=404)
    return jsonify(_notes_payload())


@app.post("/api/knowledge-base/rebuild")
def kb_rebuild():
    if _recommend_lock.locked():
        return _error("busy", "A recommendation is running.",
                      "Rebuild once it finishes.", 409)
    if not _rebuild_lock.acquire(blocking=False):
        return _error("busy", "A rebuild is already running.", status=409)
    try:
        from src.rag.ingest import run_ingestion

        started = time.monotonic()
        run_ingestion()
        notes_store.mark_rebuilt()
        return jsonify({
            "note_count": len(notes_store.list_notes()),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            **_notes_payload(),
        })
    except Exception as exc:
        return _error("rebuild_failed", "The knowledge base couldn't be rebuilt.",
                      "Check the server console for details, then retry.", 500,
                      detail=str(exc)[:300])
    finally:
        _rebuild_lock.release()


# --- Meta-Watcher --------------------------------------------------------

def _watcher_snapshot_summary() -> dict:
    from src.agents.meta_watcher import list_snapshots, load_snapshot, detect_drift

    snapshots = list_snapshots()
    summary = {"count": len(snapshots), "latest_taken_at": None, "drift": None}
    if not snapshots:
        return summary

    summary["latest_taken_at"] = load_snapshot(snapshots[-1]).get("taken_at")
    if len(snapshots) >= 2:
        result = detect_drift(lookback=1)
        summary["drift"] = {
            "from": result.get("old_snapshot_taken_at"),
            "to": result.get("new_snapshot_taken_at"),
            "moves": result.get("drift", [])[:4],
            "total": len(result.get("drift", [])),
        }
    return summary


def _watcher_status() -> dict:
    listening = watcher_control.is_listening()
    return {
        "running": listening,
        "starting": (not listening) and watcher_control.is_starting(),
        "port": watcher_control.PORT,
        "snapshots": _watcher_snapshot_summary(),
    }


@app.get("/api/meta-watcher")
def watcher_status():
    return jsonify(_watcher_status())


@app.post("/api/meta-watcher/start")
def watcher_start():
    watcher_control.start()
    return jsonify(_watcher_status()), 202


@app.post("/api/meta-watcher/stop")
def watcher_stop():
    watcher_control.stop()
    time.sleep(0.4)  # let the OS release the port before we report status
    return jsonify(_watcher_status())


# --- Entrypoint ----------------------------------------------------------

def main():
    port = int(os.getenv("DRAFT_COPILOT_PORT", DEFAULT_PORT))
    url = f"http://localhost:{port}/"
    threading.Thread(target=_warm_agent, daemon=True).start()
    if "--open" in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"Draft Copilot running at {url}")
    print("  Loopback only. Press Ctrl+C to stop.")
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
