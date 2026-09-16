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
  `gather_live_stats` does more than fetch data: it deterministically
  cross-references `get_hero_counters()`/`get_hero_compatibility()`
  results against the fetched lane roster (`lane_filtered_stats_text`)
  before the prompt is built — this exists because the LLM was found
  (via manual trace, then confirmed via repeat runs) to ignore real,
  relevant counter data it technically had in-context, since nothing
  told it to cross-reference two separately-formatted lists itself.
  Both `lane_filtered_stats_text` and `lane_roster_text` are
  deliberately given prominent, emphatically-worded sections late in
  the prompt (not buried in the general stats block) — see the
  empirical findings below for why position/framing, not just
  presence, turned out to matter.
- **Dashboard** (`src/ui/app.py`) — Streamlit, calls the agent directly.
- **Eval harness** (`src/eval/`, Phase 7) — two independent pieces so
  far, deliberately separated because a bad recommendation could be
  either the LLM's fault or the retriever's fault and you want to
  know which:
  - `reliability_eval.py` + `scenarios.py`: fixed golden set of draft
    states (not "correct answer" pairs — evals *behavior* across
    repeated runs, not exact-match). Measures JSON-validity rate
    (first-try vs. after repair vs. hard failure), repair-loop rescue
    rate, and raw (pre-filter) constraint-violation rate — the last
    one only works because `draft_agent.py`'s `parse_output` stashes
    `raw_recommended_heroes`/`constraint_violations` into
    `DraftState` BEFORE the deterministic filters run (pure
    observability addition, doesn't change filtering behavior). Slow
    (real LLM calls, minutes not seconds).
  - `retrieval_eval.py` + `retrieval_golden_set.py`: hand-labeled
    query -> expected-note pairs, queries `get_vectorstore()`
    DIRECTLY (no LLM, no agent graph) — fast (seconds), isolates
    retrieval quality from generation quality. Measures hit@k and
    MRR. IMPORTANT: golden set is hand-labeled against the actual
    contents of `data/raw/` at time of writing — re-label if notes
    are added/removed, and always `python -m src.rag.ingest` first or
    this measures stale data.
  Both explicitly scoped to *reliability/correctness*, not
  recommendation *quality* (are the picks actually good?) — that's a
  separate, harder, more subjective eval not yet built (would need
  LLM-as-judge or manual labeling). Results land in
  `data/eval_results/` per-run plus an append-only shared
  `eval_log.txt`, same durability pattern as Meta-Watcher's
  `drift_log.txt`.
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
- `get_heroes_by_lane()` (`heroes_positions`) is CONFIRMED working:
  `get_heroes_by_lane('jungle')` returns 37 real MLBB junglers (Fanny,
  Lancelot, Hayabusa, Gusion, Karina, etc.), no obviously-wrong
  entries. Confirmed indirectly via the reliability eval
  (`src/eval/reliability_eval.py`): its very first run had the LLM
  recommend Kalea/Khaleed/Odette for a jungle request — all three are
  real non-jungle heroes (support/exp/mid) in actual MLBB, and all
  three were correctly caught and filtered by the lane constraint,
  which only works if the fetched roster itself is accurate.
- Chroma's telemetry warnings ("Failed to send telemetry event") are
  silenced via `Settings(anonymized_telemetry=False)` — harmless
  library version mismatch, not a real error if it reappears elsewhere.
- CRITICAL: `langchain_chroma.Chroma.__init__`, when given a
  `client_settings` object, only copies `persist_directory` onto it —
  it does NOT set `is_persistent=True` the way its other branch (no
  `client_settings`, just `persist_directory`) does. `chromadb.config
  .Settings` defaults `is_persistent=False`. Net effect if you pass
  `client_settings` without setting `is_persistent=True` yourself:
  the client is silently **in-memory only** — `python -m src.rag
  .ingest` reports success and writes nothing to disk. Compounded by
  reusing one mutable `Settings()` object across repeated `Chroma()`
  calls (build_vectorstore alone makes two), which surfaced as a
  genuinely confusing `ValueError: Could not connect to tenant
  default_tenant` crash from the dashboard's "Rebuild knowledge base"
  button. Fixed in `src/rag/vectorstore.py`'s `_chroma_settings()`:
  build a fresh `Settings(anonymized_telemetry=False,
  is_persistent=True, persist_directory=...)` on every call, never
  share/mutate one instance. Verified fixed: ingestion now writes a
  real `chroma.sqlite3`, and a separate process can read notes back.
- Local LLM is qwen2.5:3b via Ollama (chosen for an 8GB RAM machine)
  — expect real latency, and expect occasional structured-output
  failures, which is why the repair loop exists rather than assuming
  reliable JSON on the first try.
- First reliability eval (2026-09-13, 12 runs, 6 scenarios x 2
  repeats — see `data/eval_results/reliability_20260913_114100.json`):
  100% first-try JSON validity, repair loop never fired. Raw
  constraint violations were 36% of recommendation slots (13/36) and
  100% of those were LANE violations — zero used-hero violations in
  any run. The model perfectly respects "don't recommend picked/
  banned heroes" via prompting alone, but reliably gets lane
  assignment wrong in a *systematic*, not random, way: both
  `narrow_lane_mid` runs independently recommended the identical
  wrong trio (Kalea, Khaleed, Hylos), and both `mid_gold_lane` runs
  hallucinated "Popol" and "Kupa" as two separate heroes — they're
  actually one hero, "Popol and Kupa." Small sample (n=2/scenario);
  don't treat the exact 36% as stable, but the used-hero-vs-lane
  asymmetry and the Popol/Kupa name-splitting bug were real, and were
  acted on (see next entry) rather than left as unconfirmed noise.
- FIXED (2026-09-13, same day): root cause of the lane violations was
  a prompt design issue, not a fundamentally unfixable model
  limitation. The eligible-hero list was buried at the END of a long
  `live_stats_summary` block (after tier list/counters/compatibility)
  with only a single soft instruction sentence at the very end of an
  even longer prompt. Fix in `draft_agent.py`: the list now gets its
  own prominent `LANE_CONSTRAINT_TEMPLATE` section, placed right next
  to the instruction that references it (not buried early in a long
  prompt), with each hero name individually quoted (`"Popol and
  Kupa"`) so multi-word names read as one atomic token instead of
  ambiguous comma/"and"-separated text. Re-ran the same eval
  (`reliability_20260913_115133.json`): raw violation rate dropped
  36.1% -> 2.8% (13/36 -> 1/36), JSON validity stayed 100% first-try
  (no regression), latency unchanged (median ~23s). Only remaining
  violation: one Khaleed mis-pick in `narrow_lane_mid` (down from a
  systematic 3-hero failure every run) — a residual single-hero
  confusion, not the previous pattern. This is a good example of eval
  -> root-cause -> fix -> re-eval actually working as a loop; if
  continuing this work, look at whether Khaleed-specific confusion
  recurs before concluding it's fully resolved.
- FOUND + FIXED (2026-09-14, via manual trace, not the eval suite this
  time): asked to walk through a concrete scenario (enemy picks
  Aamon, role_needed="exp", no bans) step by step, found the LLM's
  picks (Khaleed/Julian/Gatotkaca) were NOT grounded in the live
  `get_hero_counters("Aamon")` data at all, despite that data
  containing two real, valid exp-lane counters (Gloo, Silvanna). Root
  cause, same family as the lane-hallucination bug: the counters list
  and the eligible-lane list are two separately-formatted blocks with
  no instruction telling the model to cross-reference them — that's a
  nontrivial reasoning step for a 3B model with no prompted incentive
  to attempt it. The counters section also has zero imperative
  framing (just a passive label) compared to the lane list's "You
  MUST"/"INVALID" language, and sits earlier in the prompt (recency
  effects favor what's near the end). Fix in `gather_live_stats()`:
  the lane roster fetch now happens BEFORE the counters/compatibility
  calls, so both can be cross-referenced in code; the intersection
  gets its own emphatically-worded `LANE_FILTERED_STATS_TEMPLATE`
  section ("Strongly prefer recommending from here"), placed late in
  the prompt next to the lane constraint section. Same
  don't-trust-the-small-model-to-self-police-it philosophy as the
  existing deterministic filters, just applied one step earlier (as
  prompt curation, not post-hoc filtering). Verified: 5/5 repeat runs
  on the same Aamon/exp scenario now put Gloo AND Silvanna in the top
  2 picks (was 0/1 before) with rationale explicitly citing "strong
  counter to Aamon." Re-ran the full reliability eval as a regression
  check: 0% raw constraint violations (0/36, down from the already-
  fixed 2.8%/1-in-36 — even the residual Khaleed mis-pick is gone),
  100% first-try JSON validity maintained, no latency regression. This
  also extends symmetrically to ally compatibility data
  ("Synergy with X" lines) even though the triggering case was
  enemy counters — same structural bug, same fix, applied once.
- Retrieval eval (2026-09-13, `retrieval_eval.py`, 7 golden queries):
  100% hit@4, MRR 1.0 — every real note in `data/raw/` reachable at
  rank 1 by a realistic query, after fixing a bug IN THE EVAL ITSELF
  (not the RAG system): the Lolita note's source .md hand-wraps at
  ~78 chars, so "burst-heavy dive" appears in the raw text as
  "burst-heavy\ndive" — a naive substring check on raw `page_content`
  reported a false MISS for a genuinely correct rank-1 retrieval.
  Fixed by normalizing whitespace before comparing, in both the note
  content and the expected keyword. Worth remembering for similar
  content checks elsewhere: source markdown line-wrapping is a real,
  recurring gotcha, not a one-off.
- On this dev machine, outbound HTTPS calls (Rone Arena API, PyPI)
  intermittently/reliably failed with `SSLCertVerificationError:
  unable to get local issuer certificate`. Root cause: Norton
  Antivirus's HTTPS inspection injects its own root CA into the OS
  trust store, which Python's `requests`/`pip` don't consult by
  default (unlike the OS/browser/Node — `NODE_EXTRA_CA_CERTS` was
  already set for Node for this reason).
  CORRECTED FIX (supersedes an earlier version of this note): do NOT
  set `REQUESTS_CA_BUNDLE` to Norton's cert file alone — that
  replaces Python's *entire* trusted root store with just that one
  cert. It worked initially, then broke the moment `arena.rone.dev`
  was excluded from Norton's SSL scanning in Norton's own settings:
  once Norton stops intercepting a domain, that domain presents its
  real public CA-signed cert, which isn't trusted anymore because the
  single-cert override replaced the normal CA store entirely — same
  `SSLCertVerificationError`, opposite cause. Real fix:
  `certs/combined_ca_bundle.pem` = certifi's public CA bundle +
  Norton's cert, concatenated (`certs/` is gitignored, regenerate
  per-machine — see `.env`'s comment for the exact command), with
  `.env`'s `REQUESTS_CA_BUNDLE` pointing at that combined file via an
  **absolute** path. This validates both intercepted and
  Norton-excluded domains correctly. For `pip install` specifically,
  use `pip install --cert <path-to-combined-bundle>` (pip vendors its
  own requests/urllib3 and doesn't read `REQUESTS_CA_BUNDLE`). If this
  project moves to a machine without Norton, this whole issue likely
  disappears and the env var becomes a no-op (or can be removed).

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

README.md no longer carries a phase checklist (it was rewritten to be
a concise, user-facing "how to run this" doc for people pulling the
repo — dev-progress tracking now lives here instead). Status as of
this file's writing:

- Phases 1-6 complete and verified against live data (API client, RAG
  on curated notes, Draft Agent, dashboard, Meta-Watcher,
  n8n-in-Docker scheduling). Two operational caveats worth knowing if
  they come up: the n8n workflow needs its **activate** toggle
  switched on in the UI for the daily 06:00 schedule to run
  unattended (only a manual "Execute Node" trigger has been
  confirmed), and the Meta-Watcher HTTP wrapper
  (`src/agents/meta_watcher_server.py`) doesn't survive a machine
  restart/session end — no auto-start configured, must be manually
  restarted whenever the schedule needs to fire.
- Phase 7 (eval harness) IN PROGRESS, being built collaboratively
  with the user (who explicitly asked to be guided through eval
  methodology, not just handed a finished harness — keep that
  framing if continuing this work). First piece built and working:
  `src/eval/reliability_eval.py` (structured-output validity +
  constraint-violation reliability, see the Architecture section
  above). Scoped deliberately narrow first — the user chose
  "structured-output + constraint reliability" over three other
  options (RAG retrieval quality, full 4-dimension harness) when
  asked; RAG retrieval quality and recommendation-quality (LLM-as-
  judge) are natural next pieces if this continues, not yet built.
  Check `data/eval_results/eval_log.txt` for the latest run's actual
  numbers before assuming any specific reliability rate — don't
  invent or assume figures here, read the log.
