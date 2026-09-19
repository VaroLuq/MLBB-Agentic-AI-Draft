"""
Start/stop control for the local Meta-Watcher HTTP wrapper
(src/agents/meta_watcher_server.py), carried over from the Streamlit
dashboard with the Streamlit session_state dependency replaced by a
module-level process handle.

Status always comes from a real TCP check against the wrapper's port,
not from "did this app launch it": the wrapper may have been started
from a terminal, or by an earlier run of this app, and the UI should
reflect what's actually listening. That's also why stop() has a
port-based fallback for a process this app doesn't hold a handle to.
"""
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Must match meta_watcher_server.py's DEFAULT_PORT (and the n8n workflow's URL).
PORT = int(os.getenv("META_WATCHER_SERVER_PORT", 8765))
LOG_PATH = Path(tempfile.gettempdir()) / "draft_copilot_meta_watcher.log"

_process: subprocess.Popen | None = None


def is_listening(timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout):
            return True
    except OSError:
        return False


def is_starting() -> bool:
    """We launched it, it's still alive, but it isn't accepting connections yet."""
    # The wrapper runs its catch-up snapshot BEFORE it starts serving, which can
    # take a while when the last snapshot is stale — so "alive but not
    # listening" is a normal, temporary state, not a failure.
    return _process is not None and _process.poll() is None and not is_listening()


def start() -> None:
    global _process
    if is_listening() or is_starting():
        return
    log = LOG_PATH.open("wb")
    _process = subprocess.Popen(
        [sys.executable, "-m", "src.agents.meta_watcher_server"],
        cwd=str(PROJECT_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def recent_log(max_chars: int = 600) -> str:
    try:
        return LOG_PATH.read_text(encoding="utf-8", errors="replace")[-max_chars:].strip()
    except OSError:
        return ""


def stop() -> None:
    global _process
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _process.kill()
        _process = None
        return

    _process = None
    if sys.platform == "win32" and is_listening():
        _kill_by_port_windows(PORT)


def _kill_by_port_windows(port: int) -> None:
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            pid = line.strip().split()[-1]
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)
