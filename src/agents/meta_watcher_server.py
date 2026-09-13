import os
from flask import Flask, jsonify

from src.agents.meta_watcher import run_snapshot_and_report

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
    print(f"Meta-Watcher HTTP wrapper listening on http://0.0.0.0:{port}")
    print(f"  Health check: http://localhost:{port}/health")
    print(f"  Trigger a run: http://localhost:{port}/run")
    print("Leave this running while the n8n schedule is active.")
    app.run(host="0.0.0.0", port=port)
