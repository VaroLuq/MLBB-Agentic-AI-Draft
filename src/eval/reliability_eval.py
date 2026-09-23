"""
SUPERSEDED 2026-09-23 by src/eval/jev_eval.py — DO NOT RUN. Kept for the
record of what the qwen2.5:3b pipeline measured, and for the numbers in
data/eval_results/ that it produced, but it no longer reports anything real.

Every state key it reads (`parsed_recommendation` as a validity signal,
`repair_attempts`, `raw_recommended_heroes`, `constraint_violations`) was
written by the generate -> parse -> repair nodes, which were removed when Jev
replaced the local LLM. The module still imports and still runs; it will just
report 0 repair attempts and 0 violations for every scenario, which reads as a
perfect score rather than as a missing measurement. That is exactly the kind
of silent-zero this project has been bitten by before, hence this notice
rather than leaving it to be discovered.

--- original docstring below ---

Phase 7, part 1: structured-output + constraint reliability eval for
the Draft Agent. This is NOT "does the agent give good advice" (that's
a much harder, more subjective eval — see this module's docstring
notes for future phases). This measures three concrete, checkable
things across repeated runs of a fixed scenario set:

1. JSON validity rate — how often does qwen2.5:3b produce a schema-
   valid response on the FIRST try, vs. needing the self-repair loop,
   vs. failing even after MAX_REPAIR_ATTEMPTS. This is the number that
   actually justifies (or doesn't) the repair loop's existence.
2. Repair-loop rescue rate — of the runs that failed on the first
   try, how many did the repair loop actually save? If this is near
   zero, the loop isn't earning its complexity; if it's substantial,
   that's a concrete case for keeping it.
3. Raw constraint-violation rate — before the deterministic
   used-hero/lane filters run, how often does the LLM recommend an
   already-picked/banned or lane-ineligible hero? This measures how
   much real work those filters are doing (draft_agent.py's
   parse_output stashes this pre-filter data specifically for this —
   see raw_recommended_heroes / constraint_violations in DraftState).

Run with:
    python -m src.eval.reliability_eval
    python -m src.eval.reliability_eval --repeats 5
    python -m src.eval.reliability_eval --scenario early_jungle

Requires Ollama running (same as the Draft Agent normally). Each run
is a real local LLM call, so this is slow by nature — expect minutes,
not seconds, for the default scenario set. Progress prints per-run so
it's not a silent black box.
"""
import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from src.agents.draft_agent import get_draft_recommendation
from src.eval.scenarios import SCENARIOS

RESULTS_DIR = Path("data/eval_results")
LOG_PATH = RESULTS_DIR / "eval_log.txt"


def run_scenario_once(scenario: dict) -> dict:
    """Run the Draft Agent once for a scenario and extract eval-relevant fields from its state."""
    start = time.monotonic()
    try:
        result = get_draft_recommendation(
            ally_picks=scenario["ally_picks"],
            enemy_picks=scenario["enemy_picks"],
            banned_heroes=scenario["banned_heroes"],
            role_needed=scenario["role_needed"],
        )
        elapsed = time.monotonic() - start
    except Exception as e:
        # An infra failure (Ollama down, API error) is a different
        # failure mode than "the LLM produced bad JSON" — kept
        # separate in the report rather than silently counted as a
        # parse failure, since the fix for each is completely different.
        return {
            "scenario": scenario["name"],
            "infra_error": str(e),
            "elapsed_seconds": time.monotonic() - start,
        }

    succeeded = result.get("parsed_recommendation") is not None
    repair_attempts = result.get("repair_attempts", 0)
    violations = result.get("constraint_violations", {"used_hero_violations": [], "lane_violations": []})
    raw_heroes = result.get("raw_recommended_heroes", [])

    return {
        "scenario": scenario["name"],
        "infra_error": None,
        "elapsed_seconds": round(elapsed, 2),
        "succeeded": succeeded,
        "first_try_success": succeeded and repair_attempts == 0,
        "repair_attempts": repair_attempts,
        "raw_recommended_hero_count": len(raw_heroes),
        "used_hero_violation_count": len(violations.get("used_hero_violations", [])),
        "lane_violation_count": len(violations.get("lane_violations", [])),
        "used_hero_violations": violations.get("used_hero_violations", []),
        "lane_violations": violations.get("lane_violations", []),
    }


def run_eval(scenarios: list[dict], repeats: int) -> list[dict]:
    runs = []
    total = len(scenarios) * repeats
    i = 0
    for scenario in scenarios:
        for attempt in range(1, repeats + 1):
            i += 1
            print(f"[{i}/{total}] {scenario['name']} (run {attempt}/{repeats})... ", end="", flush=True)
            run = run_scenario_once(scenario)
            runs.append(run)
            if run["infra_error"]:
                print(f"INFRA ERROR: {run['infra_error']}")
            else:
                status = "OK (first try)" if run["first_try_success"] else (
                    "OK (after repair)" if run["succeeded"] else "FAILED"
                )
                print(f"{status} in {run['elapsed_seconds']}s")
    return runs


def summarize(runs: list[dict]) -> dict:
    """Aggregate raw per-run results into the headline metrics described in this module's docstring."""
    infra_failures = [r for r in runs if r["infra_error"]]
    completed = [r for r in runs if not r["infra_error"]]
    n = len(completed)

    if n == 0:
        return {"error": "No completed runs — check infra_failures.", "infra_failures": infra_failures}

    first_try = sum(1 for r in completed if r["first_try_success"])
    eventual = sum(1 for r in completed if r["succeeded"])
    rescued = sum(1 for r in completed if r["succeeded"] and not r["first_try_success"])
    hard_failures = sum(1 for r in completed if not r["succeeded"])

    total_raw_recs = sum(r["raw_recommended_hero_count"] for r in completed if r["succeeded"])
    total_violations = sum(
        r["used_hero_violation_count"] + r["lane_violation_count"]
        for r in completed if r["succeeded"]
    )

    latencies = [r["elapsed_seconds"] for r in completed]

    return {
        "total_runs": len(runs),
        "infra_failures": len(infra_failures),
        "completed_runs": n,
        "first_try_valid_rate": round(first_try / n, 3),
        "eventual_valid_rate": round(eventual / n, 3),
        "repair_loop_rescues": rescued,
        "hard_failures_after_max_retries": hard_failures,
        "raw_constraint_violation_rate": (
            round(total_violations / total_raw_recs, 3) if total_raw_recs else None
        ),
        "total_raw_recommendation_slots": total_raw_recs,
        "total_raw_violations": total_violations,
        "latency_seconds": {
            "min": round(min(latencies), 2),
            "median": round(statistics.median(latencies), 2),
            "max": round(max(latencies), 2),
        },
    }


def format_report(summary: dict, runs: list[dict]) -> str:
    if "error" in summary:
        lines = [summary["error"]]
        for r in summary.get("infra_failures", []):
            lines.append(f"  {r['scenario']}: {r['infra_error']}")
        return "\n".join(lines)

    lines = [
        f"Runs: {summary['completed_runs']}/{summary['total_runs']} completed"
        f" ({summary['infra_failures']} infra failures)",
        "",
        f"First-try JSON validity: {summary['first_try_valid_rate']:.1%}",
        f"Eventual JSON validity (within retry budget): {summary['eventual_valid_rate']:.1%}",
        f"  -> repair loop rescued {summary['repair_loop_rescues']} run(s) that failed on first try",
        f"  -> {summary['hard_failures_after_max_retries']} run(s) failed even after max repairs",
        "",
    ]
    if summary["raw_constraint_violation_rate"] is not None:
        lines.append(
            f"Raw constraint violation rate: {summary['raw_constraint_violation_rate']:.1%} "
            f"({summary['total_raw_violations']}/{summary['total_raw_recommendation_slots']} "
            f"raw recommendation slots violated a used-hero or lane constraint before filtering)"
        )
    else:
        lines.append("Raw constraint violation rate: n/a (no successful runs to measure)")

    lat = summary["latency_seconds"]
    lines.append(f"\nLatency (seconds): min={lat['min']} median={lat['median']} max={lat['max']}")

    # Per-scenario breakdown, since an aggregate can hide one bad scenario averaging out against good ones.
    lines.append("\nPer-scenario breakdown:")
    by_scenario: dict[str, list[dict]] = {}
    for r in runs:
        by_scenario.setdefault(r["scenario"], []).append(r)
    for name, scenario_runs in by_scenario.items():
        completed = [r for r in scenario_runs if not r["infra_error"]]
        ok = sum(1 for r in completed if r["succeeded"])
        lines.append(f"  {name}: {ok}/{len(scenario_runs)} succeeded")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Draft Agent structured-output + constraint reliability eval.")
    parser.add_argument("--repeats", type=int, default=2, help="Times to run each scenario (default: 2).")
    parser.add_argument("--scenario", type=str, default=None, help="Run only the named scenario.")
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [s for s in SCENARIOS if s["name"] == args.scenario]
        if not scenarios:
            names = ", ".join(s["name"] for s in SCENARIOS)
            raise SystemExit(f"Unknown scenario '{args.scenario}'. Available: {names}")

    print(f"Running reliability eval: {len(scenarios)} scenario(s) x {args.repeats} repeat(s) "
          f"= {len(scenarios) * args.repeats} total runs.\n")

    runs = run_eval(scenarios, args.repeats)
    summary = summarize(runs)
    report = format_report(summary, runs)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result_path = RESULTS_DIR / f"reliability_{timestamp}.json"
    result_path.write_text(
        json.dumps({"summary": summary, "runs": runs}, indent=2), encoding="utf-8"
    )
    print(f"\nFull results saved to: {result_path}")

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n--- {datetime.now(timezone.utc).isoformat()} ---\n{report}\n")


if __name__ == "__main__":
    main()
