import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.api_client.rone_arena_client import get_hero_rank_stats

SNAPSHOT_DIR = Path("data/snapshots")
DRIFT_LOG_PATH = SNAPSHOT_DIR / "drift_log.txt"

# Minimum absolute change (in rate units, i.e. 0.02 == 2 percentage
# points) before we call it "drift" rather than noise. Rone Arena's
# rates fluctuate a little run to run even with no real meta shift, so
# this threshold exists to keep the report signal, not noise.
DRIFT_THRESHOLDS = {
    "win_rate": 0.02,
    "pick_rate": 0.02,
    "ban_rate": 0.02,
}


def take_snapshot(days: str = "7", size: int = 50) -> Path:
    stats = get_hero_rank_stats(days=days, size=size)
    taken_at = datetime.now(timezone.utc)

    payload = {
        "taken_at": taken_at.isoformat(),
        "days": days,
        "size": size,
        "heroes": stats,
    }

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{taken_at.strftime('%Y%m%d_%H%M%S')}.json"
    path = SNAPSHOT_DIR / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def list_snapshots() -> list[Path]:
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(p for p in SNAPSHOT_DIR.iterdir() if p.suffix == ".json")


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compute_drift(
    old_snapshot: dict,
    new_snapshot: dict,
    thresholds: dict[str, float] = DRIFT_THRESHOLDS,
) -> list[dict]:
    old_by_name = {h["name"]: h for h in old_snapshot.get("heroes", []) if h.get("name")}
    new_by_name = {h["name"]: h for h in new_snapshot.get("heroes", []) if h.get("name")}

    drift = []
    for name, new_h in new_by_name.items():
        old_h = old_by_name.get(name)
        if old_h is None:
            continue

        for metric, threshold in thresholds.items():
            old_val = old_h.get(metric)
            new_val = new_h.get(metric)
            if old_val is None or new_val is None:
                continue
            delta = new_val - old_val
            if abs(delta) >= threshold:
                drift.append({
                    "hero": name,
                    "metric": metric,
                    "old_value": old_val,
                    "new_value": new_val,
                    "delta": delta,
                    "direction": "up" if delta > 0 else "down",
                })

    drift.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return drift


def detect_drift(lookback: int = 1, thresholds: dict[str, float] = DRIFT_THRESHOLDS) -> dict:
    snapshots = list_snapshots()
    if len(snapshots) < lookback + 1:
        return {
            "error": f"Need at least {lookback + 1} snapshots to compare "
                     f"with lookback={lookback}, only have {len(snapshots)}. "
                     f"Run take_snapshot() again later (Phase 6 will "
                     f"automate this on a schedule).",
            "drift": [],
        }

    old_snapshot = load_snapshot(snapshots[-1 - lookback])
    new_snapshot = load_snapshot(snapshots[-1])
    drift = compute_drift(old_snapshot, new_snapshot, thresholds)

    return {
        "old_snapshot_taken_at": old_snapshot.get("taken_at"),
        "new_snapshot_taken_at": new_snapshot.get("taken_at"),
        "drift": drift,
        "error": None,
    }


def format_drift_report(result: dict) -> str:
    if result.get("error"):
        return result["error"]

    drift = result.get("drift", [])
    if not drift:
        return (f"No significant drift between "
                 f"{result['old_snapshot_taken_at']} and "
                 f"{result['new_snapshot_taken_at']}.")

    lines = [
        f"Meta drift from {result['old_snapshot_taken_at']} to "
        f"{result['new_snapshot_taken_at']}:"
    ]
    for d in drift:
        arrow = "UP" if d["direction"] == "up" else "DOWN"
        lines.append(
            f"  [{arrow}] {d['hero']} {d['metric']}: "
            f"{d['old_value']:.3f} -> {d['new_value']:.3f} "
            f"({d['delta']:+.3f})"
        )
    return "\n".join(lines)


def append_to_log(text: str) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    run_at = datetime.now(timezone.utc).isoformat()
    with DRIFT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {run_at} ---\n{text}\n")


def run_snapshot_and_report() -> str:
    snapshot_path = take_snapshot()
    result = detect_drift(lookback=1)
    report = format_drift_report(result)

    full_report = f"Snapshot saved to: {snapshot_path}\n{report}"
    append_to_log(full_report)
    return full_report


# How stale the most recent snapshot needs to be before a startup
# catch-up run triggers. The n8n schedule fires daily, so this is
# deliberately a bit under 24h: if the wrapper was off across a
# scheduled run, the gap since the last real snapshot will be well
# past 24h by the time it's restarted, but this also tolerates the
# wrapper being restarted a few hours early/late around its own
# normal daily run without spuriously double-firing.
CATCH_UP_STALE_THRESHOLD_HOURS = 20.0


def catch_up_if_stale(threshold_hours: float = CATCH_UP_STALE_THRESHOLD_HOURS) -> str | None:
    """
    Meant to be called once, at wrapper startup (see
    meta_watcher_server.py). n8n's HTTP Request node can only trigger
    a run while the wrapper happens to be listening — if it was off
    when the 06:00 schedule fired, that snapshot is just gone, silently
    (n8n shows a failed execution, but nothing on the Python/data side
    ever ran to record it). This closes that gap from the other end:
    whenever the wrapper DOES start, it checks whether the most recent
    snapshot is older than `threshold_hours` (or there are no
    snapshots at all) and, if so, immediately takes one — so restarting
    the wrapper after a missed window self-heals instead of silently
    waiting for the next scheduled trigger. Returns the report string
    if a catch-up run happened, None if the most recent snapshot was
    already recent enough.
    """
    snapshots = list_snapshots()
    if snapshots:
        latest = load_snapshot(snapshots[-1])
        taken_at_str = latest.get("taken_at")
        if taken_at_str:
            taken_at = datetime.fromisoformat(taken_at_str)
            age_hours = (datetime.now(timezone.utc) - taken_at).total_seconds() / 3600
            if age_hours < threshold_hours:
                return None  # recent enough, nothing missed

    return run_snapshot_and_report()


if __name__ == "__main__":
    try:
        print(run_snapshot_and_report())
    except Exception as e:
        # Log the failure too, not just successes, so the log file is a
        # complete run history — and exit non-zero so n8n (or anyone
        # running this manually) sees the execution as failed rather
        # than silently missing a snapshot.
        error_text = f"FAILED: {e}\n{traceback.format_exc()}"
        print(error_text, file=sys.stderr)
        try:
            append_to_log(error_text)
        except Exception:
            pass  # logging the failure is best-effort; don't mask the original error
        sys.exit(1)
