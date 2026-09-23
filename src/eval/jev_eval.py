"""Reliability eval for the Jev decision node.

Replaces what reliability_eval.py measured. Those metrics — JSON-validity
rate, repair-loop rescue rate, constraint-violation rate — were all about
coercing a generative model into well-formed, rule-abiding output. Jev returns
typed primitives and is handed an already-filtered candidate list, so all three
are now true by construction and measuring them would only ever produce 100%.

What can still go wrong is different in kind, so this measures that instead:

  stability   - given byte-identical state, does Jev return the same tiers and
                a similar score on a repeat run? Probe runs showed 2.99 vs 2.98
                on a repeat, so it is close to deterministic but not exactly.
  separation  - does the rubric actually discriminate, or does everything
                collapse into one tier? A rubric that rates all candidates
                Solid is useless even if perfectly stable.
  calibration - when Jev is confident, is it confident about a clear-cut case?
                Reported as the confidence spread, since there is no ground
                truth to score against. This is descriptive, not a pass/fail.

Costs real API calls: roughly len(SCENARIOS) * REPEATS requests. At the
observed ~$0.0002 per multi-candidate call that is negligible, but it is not
free and it hits a third-party service, so it is never run automatically.
"""

import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from src.agents.draft_agent import gather_live_stats, retrieve_notes
from src.agents import jev_client

RESULTS_DIR = Path("data/eval_results")
LOG_FILE = RESULTS_DIR / "eval_log.txt"
REPEATS = 3

# Deliberately spans candidate-pool sizes, since a rubric that separates 7
# candidates may still collapse on 1, and both cases occur in real use.
SCENARIOS = [
    ("single_counter", {"ally_picks": [], "enemy_picks": ["Lapu-Lapu"],
                        "banned_heroes": [], "role_needed": "exp"}),
    ("four_enemies", {"ally_picks": ["Angela", "Miya"],
                      "enemy_picks": ["Diggie", "Ixia", "Baxia", "Gord"],
                      "banned_heroes": [], "role_needed": "exp"}),
    ("synergy_heavy", {"ally_picks": ["Lolita"], "enemy_picks": ["Marcel", "Hirara"],
                       "banned_heroes": [], "role_needed": "jungle"}),
    ("roam_pool", {"ally_picks": ["Miya"], "enemy_picks": ["Gusion", "Lancelot"],
                   "banned_heroes": [], "role_needed": "roam"}),
]


def _build(draft: dict) -> dict:
    """Live stats + retrieval once per scenario, so repeats share one state.

    Rebuilding would let the upstream API drift between repeats and show up as
    Jev instability, which is the opposite of what this measures.
    """
    return retrieve_notes(gather_live_stats(dict(draft)))


def run_scenario(name: str, draft: dict) -> dict:
    state = _build(draft)
    candidates = [row["name"] for row in state.get("lane_filtered_aggregate") or []]
    runs = []

    for _ in range(REPEATS):
        started = time.monotonic()
        result = jev_client.evaluate_candidates(state)
        runs.append({
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": result.get("error"),
            "tiers": {r["hero"]: r["tier"] for r in result["rows"]},
            "scores": {r["hero"]: r["score"] for r in result["rows"]},
            "confidence": {r["hero"]: r["confidence"] for r in result["rows"]},
            "order": [r["hero"] for r in result["rows"]],
        })

    ok = [r for r in runs if not r["error"]]
    tier_sets = [tuple(sorted(r["tiers"].items())) for r in ok]
    # Score drift: the largest spread any single hero showed across repeats.
    drift = 0.0
    for hero in candidates:
        values = [r["scores"].get(hero) for r in ok if r["scores"].get(hero) is not None]
        if len(values) > 1:
            drift = max(drift, max(values) - min(values))

    last = ok[-1] if ok else {"tiers": {}, "confidence": {}, "order": []}
    distinct_tiers = len(set(last["tiers"].values()))
    confidences = [c for c in last["confidence"].values() if isinstance(c, (int, float))]

    return {
        "scenario": name,
        "candidate_count": len(candidates),
        "runs_ok": len(ok),
        "runs_failed": len(runs) - len(ok),
        "errors": [r["error"] for r in runs if r["error"]],
        # Stability
        "tiers_identical_across_repeats": len(set(tier_sets)) == 1 if tier_sets else None,
        "order_identical_across_repeats": len({tuple(r["order"]) for r in ok}) == 1 if ok else None,
        "max_score_drift": round(drift, 4),
        # Separation
        "distinct_tiers": distinct_tiers,
        "collapsed_to_one_tier": distinct_tiers <= 1 and len(candidates) > 1,
        "tiers": last["tiers"],
        # Calibration (descriptive)
        "confidence_min": round(min(confidences), 3) if confidences else None,
        "confidence_mean": round(statistics.fmean(confidences), 3) if confidences else None,
        "latency_ms_median": round(statistics.median(r["elapsed_ms"] for r in runs)),
    }


def main() -> dict:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    results = [run_scenario(name, draft) for name, draft in SCENARIOS]

    evaluated = [r for r in results if r["candidate_count"]]
    summary = {
        "timestamp": started.isoformat(timespec="seconds"),
        "repeats_per_scenario": REPEATS,
        "scenarios": len(results),
        "scenarios_with_candidates": len(evaluated),
        "total_api_calls": len(results) * REPEATS,
        "stable_tier_rate": (
            sum(1 for r in evaluated if r["tiers_identical_across_repeats"]) / len(evaluated)
            if evaluated else None
        ),
        "stable_order_rate": (
            sum(1 for r in evaluated if r["order_identical_across_repeats"]) / len(evaluated)
            if evaluated else None
        ),
        "max_score_drift": max((r["max_score_drift"] for r in evaluated), default=0.0),
        "collapsed_scenarios": [r["scenario"] for r in evaluated if r["collapsed_to_one_tier"]],
        "failed_calls": sum(r["runs_failed"] for r in results),
        "latency_ms_median": round(statistics.median(
            [r["latency_ms_median"] for r in results])) if results else None,
    }
    payload = {"summary": summary, "results": results}

    stamp = started.strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"jev_{stamp}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Append-only shared trail, same durability pattern as drift_log.txt.
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"[{summary['timestamp']}] jev_eval  "
                  f"stable_tiers={summary['stable_tier_rate']} "
                  f"stable_order={summary['stable_order_rate']} "
                  f"drift={summary['max_score_drift']} "
                  f"collapsed={summary['collapsed_scenarios']} "
                  f"failed={summary['failed_calls']} "
                  f"median_ms={summary['latency_ms_median']} -> {out.name}\n")

    print(json.dumps(summary, indent=2))
    for r in results:
        print(f"\n{r['scenario']}  ({r['candidate_count']} candidates, "
              f"{r['distinct_tiers']} distinct tiers, drift {r['max_score_drift']})")
        for hero, tier in r["tiers"].items():
            print(f"   {hero:<14} {tier}")
    print(f"\nWritten to {out}")
    return payload


if __name__ == "__main__":
    main()
