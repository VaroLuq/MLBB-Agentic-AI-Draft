# Project context for Claude Code

This file is auto-loaded by Claude Code at the start of every session.
It summarizes decisions and conventions from the project's build
history (originally developed in a claude.ai conversation) so context
isn't lost when continuing work here.

## What this project is

A Mobile Legends: Bang Bang draft copilot, built as a portfolio/CV
project demonstrating agentic AI engineering: LangGraph orchestration,
tool-calling vs. RAG used deliberately for different data types, and
reliability engineering (structured output validation with a
self-repair loop). See README.md for full phase-by-phase status.

## Architecture (see README.md for the diagram-level view)

- **Live stats** (win rates, counters, compatibility, lane rosters) —
  fetched via direct API tool-calls to the Rone Arena API
  (`src/api_client/rone_arena_client.py`). Deliberately NOT put through
  RAG — this data changes too often and is too precise to risk
  retrieving stale.
- **Strategic narrative content** — manually curated by the user
  (`src/rag/`), NOT scraped from the API's community guide feed (that
  was tried and reworked away — see git history / earlier chat — the
  user's own drafting judgment was judged more valuable RAG content).
- **Draft Agent** (`src/agents/draft_agent.py`) — a LangGraph state
  machine: gather_live_stats -> retrieve_notes -> generate_recommendation
  -> parse_output <-> repair_output (loop, max 2 retries) -> end.
- **Dashboard** (`src/ui/app.py`) — Streamlit, calls the agent directly.
- **Meta-Watcher** (`src/agents/meta_watcher.py`) — NOT a LangGraph
  graph, deliberately: it's deterministic snapshot + diff, no LLM
  reasoning or self-repair loop needed. `take_snapshot()` writes
  timestamped JSON to `data/snapshots/`; `detect_drift()` compares the
  latest snapshot against an earlier one and flags heroes whose
  win/pick/ban rate moved past a threshold (default 0.02). Recurring
  scheduling is Phase 6 (n8n) — this module is the primitive that
  scheduler will call, kept independently runnable/testable via its
  `__main__` block in the meantime. `run_snapshot_and_report()` is the
  single entry point both the CLI and n8n go through; every run
  (success or failure) also appends to `data/snapshots/drift_log.txt`
  as a durable trail independent of n8n's own execution history.
- **n8n scheduling** (`n8n/meta_watcher_schedule.json`) — n8n runs in
  **Docker** (`docker run ... docker.n8n.io/n8nio/n8n`), NOT via
  `npx n8n`/local install: `npx n8n` and `npm install -g n8n` both
  failed on this machine because n8n depends on the native module
  `isolated-vm`, which needs `node-gyp`/Visual Studio Build Tools to
  compile — not installed here, and installing that toolchain (several
  GB) just for n8n was judged too heavy. Docker's official image ships
  prebuilt, sidestepping compilation entirely.
  Consequence: a Dockerized n8n can't reach the host venv's Python
  directly (no Execute Command), so the workflow is Schedule Trigger
  -> HTTP Request node, POSTing to
  `http://host.docker.internal:8765/run` — a tiny local Flask wrapper
  (`src/agents/meta_watcher_server.py`) that calls
  `meta_watcher.run_snapshot_and_report()` and must be left running
  (`python -m src.agents.meta_watcher_server`) whenever the n8n
  schedule is active. It binds `0.0.0.0` (required for
  `host.docker.internal` to reach it — loopback-only wouldn't work),
  which also means it's reachable from the local LAN, not just this
  machine; acceptable for a portfolio project, not something to
  expose further. VERIFIED end-to-end 2026-09-12 via the workflow's
  "Execute Node": snapshot written, drift checked, logged to
  `data/snapshots/drift_log.txt`.

## Important empirical findings (don't relitigate these without new evidence)

- The Rone Arena SDK's method naming is inconsistent: `heroes_rank`
  uses a `heroes_` prefix, but `hero_counters`/`hero_compatibility`
  don't. Don't assume a naming pattern for new endpoints — check via
  `dir(client.heroes)` first (see the diagnostic in
  `rone_arena_client.py`'s `__main__` block).
- `get_hero_counters()` reads the `sub_hero_last` field, NOT
  `sub_hero`, despite `sub_hero` looking superficially plausible
  (positive increase_win_rate values). This was corrected empirically
  by the user cross-checking against known real matchups — the API's
  field naming doesn't reliably match its documented semantics.
  `get_hero_compatibility()` correctly uses `sub_hero`.
- `get_heroes_by_lane()` (lane/role filtering) was added but its SDK
  method name (`heroes_positions`) was UNVERIFIED as of this file's
  writing — check whether it's been confirmed working before trusting
  it; if not, re-run the diagnostic in `rone_arena_client.py`.
- Chroma's telemetry warnings ("Failed to send telemetry event") are
  silenced via `Settings(anonymized_telemetry=False)` — harmless
  library version mismatch, not a real error if it reappears elsewhere.
- Local LLM is qwen2.5:3b via Ollama (chosen for an 8GB RAM machine)
  — expect real latency, and expect occasional structured-output
  failures, which is why the repair loop exists rather than assuming
  reliable JSON on the first try.
- On this dev machine, outbound HTTPS calls (Rone Arena API, PyPI)
  intermittently/reliably failed with `SSLCertVerificationError:
  unable to get local issuer certificate`. Root cause: Norton
  Antivirus's HTTPS inspection injects its own root CA into the OS
  trust store, which Python's `requests`/`pip` don't consult by
  default (unlike the OS/browser/Node — `NODE_EXTRA_CA_CERTS` was
  already set for Node for this reason). Fixed for the app via
  `REQUESTS_CA_BUNDLE` in `.env` pointing at Norton's exported
  `wscert.pem`; for `pip install` specifically, use `pip install
  --cert <path>` instead (pip vendors its own requests/urllib3 and
  doesn't read `REQUESTS_CA_BUNDLE`). If this project moves to a
  machine without Norton, this whole issue likely disappears and the
  env var becomes a no-op.

## Conventions used throughout

- Module-level caching pattern for expensive resources (embedding
  model, vectorstore connection, LLM client) to avoid reloading on
  every call — see `get_cached_chain`-style patterns in `src/agents/llm.py`
  and `src/rag/vectorstore.py`. `clear_vectorstore_cache()` must be
  called after any re-ingestion from a long-lived process (e.g. the
  Streamlit app) to avoid stale connections.
- API client functions are written defensively (`.get()` with
  fallbacks) rather than assuming documented schemas are accurate —
  this API's docs have been wrong before.
- Deterministic filters (used-hero exclusion, lane-eligibility) are
  enforced in code after LLM generation, not just requested in the
  prompt — small local models don't reliably self-police constraints.

## Where the project is now / what's next

See README.md's "Project status" checklist for the authoritative
phase list. As of this file's writing, Phases 1-6 are all complete
and verified against live data (API client, RAG on curated notes,
Draft Agent, dashboard, Meta-Watcher, n8n-in-Docker scheduling). The
n8n workflow still needs its **activate** toggle switched on in the
UI for the daily 06:00 schedule to run unattended (only a manual
"Execute Node" trigger has been confirmed so far) — worth nudging
about if it comes up, since an unactivated workflow silently never
fires on its own. Also keep in mind: the Meta-Watcher HTTP wrapper
(`src/agents/meta_watcher_server.py`) must be running whenever the
schedule is meant to fire — it doesn't survive a machine
restart/session end on its own, there's no auto-start configured for
it. Remaining: an eval harness (Phase 7, stretch goal, valuable for
the CV story).
