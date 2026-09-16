import os
import traceback
from flask import Flask, jsonify

from src.agents.meta_watcher import (
    run_snapshot_and_report,
    catch_up_if_stale,
    CATCH_UP_STALE_THRESHOLD_HOURS,
)

app = Flask(__name__)

DEFAULT_PORT = 8765


@app.route("/run", methods=["POST", "GET"])
def run():
    try:
        report = run_snapshot_and_report()
        return jsonify({"success": True, "report": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("META_WATCHER_SERVER_PORT", DEFAULT_PORT))
    threshold_hours = float(os.getenv(
        "META_WATCHER_CATCHUP_THRESHOLD_HOURS", CATCH_UP_STALE_THRESHOLD_HOURS
    ))

    # Closes the gap where a scheduled n8n run fires while this
    # wrapper is off: n8n's HTTP Request node just gets connection-
    # refused and nothing on this side ever runs to record it, so a
    # missed 06:00 snapshot is otherwise gone for good. Checking here,
    # once at startup, means restarting the wrapper after any downtime
    # self-heals instead of silently waiting for tomorrow's trigger.
    print(f"Checking for a missed snapshot (threshold: {threshold_hours}h stale)...")
    try:
        catch_up_report = catch_up_if_stale(threshold_hours)
        if catch_up_report:
            print("Most recent snapshot was stale — caught up now:")
            print(catch_up_report)
        else:
            print("Most recent snapshot is recent enough, no catch-up needed.")
    except Exception as e:
        # Best-effort: a failed catch-up attempt (e.g. Ollama/API down
        # at this exact moment) shouldn't prevent the server itself
        # from starting — the /run endpoint being available for the
        # NEXT scheduled or manual trigger matters more than this one
        # startup check succeeding.
        print(f"Catch-up check failed (server will still start): {e}")
        traceback.print_exc()

    print(f"\nMeta-Watcher HTTP wrapper listening on http://0.0.0.0:{port}")
    print(f"  Health check: http://localhost:{port}/health")
    print(f"  Trigger a run: http://localhost:{port}/run")
    print("Leave this running while the n8n schedule is active.")
    app.run(host="0.0.0.0", port=port)
