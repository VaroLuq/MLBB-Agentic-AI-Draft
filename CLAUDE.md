# Project context for Claude Code

This file is auto-loaded by Claude Code at the start of every session.
It summarizes decisions and conventions from the project's build
history (originally developed in a claude.ai conversation) so context
isn't lost when continuing work here.

## What this project is

A Mobile Legends: Bang Bang draft copilot, built as a portfolio/CV
project demonstrating agentic AI engineering: LangGraph orchestration,
tool-calling vs. RAG used deliberately for different data types, and
reliability engineering.

REWRITTEN 2026-09-23: the headline demonstration used to be "structured
output validation with a self-repair loop" around a local qwen2.5:3b.
That model, its prompt, its JSON schema, the parse/repair cycle and the
post-generation constraint filters have ALL been removed. The pipeline
now ends in Jev, a third-party decision model that returns typed
primitives, so there is no generated JSON to validate and no generated
hero name to filter. The demonstration is now the migration itself:
measuring that a generative model was doing a classification job badly
and slowly, then replacing it with a classifier and re-measuring. If a
future session finds text describing the repair loop as current
behaviour, that text is stale — the loop is gone.

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
  machine. CURRENT graph (2026-09-23), linear, no conditional edges:
  gather_live_stats -> retrieve_notes -> evaluate_candidates -> END.
  `evaluate_candidates` calls Jev (see the Jev bullet below); it does
  not call an LLM. The old `generate_recommendation`, `parse_output`,
  `repair_output`, `should_retry`, `RECOMMENDATION_PROMPT`,
  `REPAIR_PROMPT`, `_strip_code_fences` and the Pydantic
  `DraftRecommendation`/`PickRecommendation` models were all deleted.
  `src/agents/llm.py` still exists but NOTHING imports it — the Ollama
  dependency is detached, not merely unused.
  `gather_live_stats` does more than fetch data: it deterministically
  cross-references `get_hero_counters()`/`get_hero_compatibility()`
  results against the fetched lane roster (`lane_filtered_stats_text`)
  before the prompt is built — this exists because the LLM was found
  (via manual trace, then confirmed via repeat runs) to ignore real,
  relevant counter data it technically had in-context, since nothing
  told it to cross-reference two separately-formatted lists itself.
  Both `lane_filtered_stats_text` and `lane_roster_text` USED to be
  given prominent, emphatically-worded sections late in the prompt (see
  the empirical findings below for why position/framing, not just
  presence, turned out to matter). That prompt no longer exists.
  `lane_filtered_stats_text` and `lane_roster_text` are still built and
  still carried in `DraftState` — the web app's diagnostics panel reads
  the former — but nothing consumes them as prompt text any more. The
  cross-referencing work itself survived the migration and now feeds
  `lane_filtered_aggregate` instead, which is the point: it was always
  deterministic code, never prompt engineering.
  `gather_live_stats` also excludes already-picked and banned heroes
  from the aggregate (not just from the final answer). That guard was
  added 2026-09-23 and is load-bearing now: `parse_output` used to strip
  used heroes AFTER generation, and deleting it would otherwise have
  handed Jev banned heroes to score. Verified before the fix: banning
  Esmeralda still left her as the sole candidate against Lapu-Lapu.
  Deliberately NOT applied to `lane_filtered_stats_text`.
- **Cumulative counter/synergy aggregate** (2026-09-23,
  `gather_live_stats` -> `DraftState["lane_filtered_aggregate"]`) —
  originally built as a Jev experiment, now THE candidate list the
  pipeline actually scores. `lane_filtered_stats_text` answers
  "who counters this one enemy?" once per enemy, so a hero who counters
  two of them reads as two unrelated bullets and nothing adds them up.
  This accumulates per-hero totals across every relation already
  fetched (no extra API calls), lane-filtered, one row per hero:
  `{name, win_rate, cumulative_counter_impact,
  cumulative_synergy_impact, counters[], synergises_with[], rag_score,
  notes[]}`. `counters`/`synergises_with`/`notes` are provenance beyond
  the originally-specified schema. Ordering
  is `synergy - counter` (counter impact is negative-is-better) and is
  presentation only — NO composite score is stored, because how to
  weight the two axes against each other is not established. Surfaced
  read-only via `server.py`'s `/api/recommend`
  (`lane_filtered_aggregate`) and rendered as an aligned monospace
  table by `aggregateText()` in `src/web/static/js/draft.js`, appended
  to the existing "Live stats" diagnostics tab. Known limitation: the
  table is ~75 chars and `.diag pre` sets `white-space: pre-wrap`, so
  column alignment collapses on a ~390px viewport; left alone rather
  than change CSS shared by all three diagnostics tabs.
- **`rag_score`** (`src/rag/scoring.py`, 2026-09-23) — per-candidate
  note relevance, merged into `lane_filtered_aggregate` by
  `_attach_rag_scores()` in `retrieve_notes`. It lives there and not in
  `gather_live_stats` purely because of node order: the aggregate is
  built before retrieval runs. Design chosen ("Design A" in the
  transcript): reuse the ONE scenario retrieval already happening —
  `retrieve_notes` switched from the plain retriever to
  `similarity_search_with_relevance_scores`, which returns the same
  documents in the same order but also the 0-1 relevance the retriever
  threw away. VERIFIED byte-identical retrieved-notes text across three
  queries, so the switch changed no downstream content. Zero extra
  queries, zero added latency. A per-candidate query was considered and
  rejected: at 4 chunks with `k=4` both approaches see the identical
  notes, so the extra ~170ms/candidate buys nothing until the corpus
  outgrows `k`.
  Attribution: a note counts for a hero if its `hero_name` metadata
  matches OR the note text names the hero (`mentions_hero()`, the same
  whole-word rule `src/web/evidence.py` uses). The second half is the
  valuable one — the Lapu-Lapu note names Esmeralda as his counter, so
  it is evidence FOR Esmeralda whenever Lapu-Lapu is drafted.
  Aggregation is Noisy-OR (probabilistic union), the user's choice:
  bounded in [0,1], saturating, and it returns 0.0 on an empty list, so
  a hero named in no note scores 0.0 at any threshold. Scenario
  conditioning is FREE because the query string contains the lane and
  the picks — measured on the Esmeralda/Lapu-Lapu note: 0.409 when
  Lapu-Lapu is an enemy, 0.173 when he is not.
  KNOWN LIMITATION: `mentions_hero` has no notion of direction. The
  "Edith as an Esmeralda Counter" note argues AGAINST Esmeralda but
  still raises her `note_support`. The note text is now in Jev's state
  so it can in principle read the direction; the scalar alone cannot.
- **Jev decision node** (`src/agents/jev_client.py`, 2026-09-23) —
  replaced qwen2.5:3b entirely. Jev is a third-party "System 1"
  decision model (TypeSafe AI) reached at
  `https://api.openjev.sh/v1/systemone` with `OPEN_JEV_KEY`, model
  `openjev`. It emits no text: given a `state` plus `questions` it
  returns typed primitives with calibrated probabilities. This module
  owns State Engineering only — `build_payload()` turns
  `lane_filtered_aggregate` into an abstract state plus one `Score`
  question per candidate, all in ONE request (fan-out is free, see the
  empirical findings). No ranking policy lives here.
  Rubric: 4 ascending tiers `["Fallback","Marginal","Solid","Priority"]`.
  Metrics are SIGN-FLIPPED so every one is higher-is-better
  (`counter_strength = -cumulative_counter_impact`) — qwen was
  previously observed misreading the raw negatives as a "win rate
  increase", so the trap was removed rather than re-documented.
  `win_rate` is deliberately NOT in the state: it is a global average
  with no matchup meaning, ~half of viable counter-picks sit below
  0.500, and gating on it is exactly what made an earlier draft rubric
  rate Esmeralda "Unusable" when she was the only valid counter.
  `is_lane_match` is also absent — the aggregate is already
  lane-filtered, so it was constant `True`.
  The rubric deliberately carries NO hard numeric gates. Real ranges go
  in a `scales` block in the state (typical/strong/max_seen, measured
  over 21 candidates from 6 scenarios) so Jev knows what a big number
  is on our axes, then weighs them itself. Hard cuts would make the
  whole thing arithmetic, at which point an `if` beats a network round
  trip and Jev adds nothing.
  Question keys are SANITISED (`viability_X_Borg`, not
  `viability_X.Borg`) with a map back to real names, because hero names
  contain spaces, dots, hyphens and apostrophes; this project has
  already lost time to "Popol and Kupa" being split in two.
  `build_payload()` returns `({}, {})` for an empty candidate list — a
  real case, not an error, and more common now that used heroes are
  excluded.
  `describe_candidate()` / `summarise()` TEMPLATE the rationale and
  summary from the same numbers Jev scored. Jev cannot write prose, and
  templating is arguably an upgrade: qwen was caught inventing "a good
  win rate against Aamon" for a hero that appeared in no counter data.
- **Web app** (`src/web/`, replaced the Streamlit dashboard `src/ui/app.py`,
  now deleted) — a Flask JSON API (`server.py`) wrapping the agents, RAG
  and Meta-Watcher with ZERO backend logic changes, plus a static frontend
  in `src/web/static/` (HTML, Tailwind v4 built by the standalone CLI into
  a committed `app.css`, vanilla ES modules, self-hosted Barlow fonts, no
  runtime CDN). Run: `python -m src.web.server [--open]` / `run_dashboard.bat`
  (port 8600, `DRAFT_COPILOT_PORT` overrides). Decisions worth keeping:
  - **Security posture**: this API can delete note files and launch a
    subprocess, so unlike the Meta-Watcher wrapper (0.0.0.0 for Docker) it
    binds loopback only, rejects non-loopback Host headers (DNS rebinding),
    and requires an `X-Requested-With: draft-copilot` header on every
    POST/PUT/DELETE (cross-origin pages can't set it without a CORS
    preflight, which is never granted). Note ids are validated against the
    `general/x` / `heroes/<Name>/x` shape and re-resolved under `data/raw/`
    before any read/write/delete (`notes_store.py`). Verified live: forged
    request 403, traversal 404/405, bad hero 400, wrong Host 403.
  - **`notes_store.py`** owns note CRUD over the same folder convention
    `note_loader.py` reads. Knowledge-base freshness is a fingerprint of
    the notes written to `vectorstore/.notes_signature` after a rebuild
    THROUGH THE APP; with no fingerprint the state is reported STALE
    ("unknown"), deliberately — an mtime comparison can't see deleted
    notes, which may still be indexed. CLI-only rebuilds therefore read
    as stale until one rebuild via the app.
  - **`watcher_control.py`** is the Streamlit start/stop ported off
    `session_state`: status is a real TCP check on the wrapper's port (not
    "did I launch it"), start returns immediately and the UI polls (the
    wrapper runs its catch-up snapshot BEFORE listening, so "alive but not
    listening yet" is normal), stop falls back to a Windows port-kill.
    NO LONGER REACHABLE FROM THE UI (2026-09-23): the whole Meta-Watcher
    panel was removed from the intel rail at the user's request. The
    module, `/api/meta-watcher`, `/start` and `/stop` all still work and
    the snapshot schedule still runs — nothing in the app reads them.
    `api.js`'s `watcher`/`startWatcher`/`stopWatcher` were deleted, as
    were `renderWatcher()`/`refreshWatcher()` in `intel.js` and the
    `.md-*`, `.watch-*` and `.moves*` CSS. `.lamp` was KEPT: the topbar
    status chips use it. Retiring the backend routes is an open decision,
    not an oversight.
  - **`evidence.py`** derives, per recommended hero, which supporting
    evidence actually appeared in the agent's own context (tier list,
    counter/synergy data, retrieved notes) by parsing `live_stats_summary`
    / `retrieved_notes`. The UI shows tags like "Counters Aamon" and an
    amber "Model knowledge only" tag when nothing backs a pick — it
    surfaces the grounding gap the Aamon/exp trace found. Changes nothing
    about how recommendations are produced.
  - **Latency reality**: SUPERSEDED. The old figures (98s cold, ~20-30s
    warm) were qwen. Measured 2026-09-23 after the Jev migration: **6.1s
    warm** end-to-end through `/api/recommend`, ~22.6s on the first call
    in a fresh process (that is the HuggingFace embedder loading, not
    Jev). Jev itself is 0.6-0.9s. The loading UI's copy still says "A
    local model reads the live stats and your notes. This usually takes
    15 to 30 seconds" and `TYPICAL_SECONDS = 30` in `draft.js` — both
    now wrong and not yet updated.
  - **Response contract changed** with the Jev migration. `/api/recommend`
    no longer returns `parse_error`, `raw_llm_output`, `repair_attempts`
    or `filtered_out`; it returns `jev_error` and `jev_raw`.
    `_filtered_out()` was deleted outright — filtering now happens BEFORE
    evaluation, so there is never a stripped pick to report. Each
    recommendation carries `{hero, tier, tier_index, score, confidence,
    probabilities, rationale}` instead of `{hero, priority_score,
    rationale}`. In the UI, `meter(rec.priority_score)` became
    `verdict(rec)` — a tier badge plus confidence, with gold reserved for
    Priority. The bare 0-1 meter was dropped partly because a finish
    review had already flagged an unlabelled score in that slot as
    reading like a win probability. The third diagnostics tab is now
    "Jev response" (raw JSON) instead of "Model output".
  - **Design**: visual world "The Draft Screen, Rebuilt" (MLBB's own
    pick/ban screen grammar), chosen via impeccable's direction round;
    product truth in `PRODUCT.md`, contract in
    `.impeccable/surfaces/src-web-static-index-html.md`. Code-led build
    (no usable image generation: impeccable's fallback wants
    `OPENAI_API_KEY`; the Gemini key/docs-MCP in `.env` are NOT wired in and
    no image was generated). Hero portraits are deliberate placeholder
    initials badges — no game art exists or was scraped/generated.
  - Rebuild CSS: download the Tailwind standalone CLI into `tools/`
    (git-ignored, 112 MB) then `tools\tailwindcss.exe -i
    src/web/styles/input.css -o src/web/static/app.css --minify`.
- **Eval harness** (`src/eval/`, Phase 7) — deliberately separated by
  layer, because a bad recommendation could be the model's fault or the
  retriever's fault and you want to know which.
  - `jev_eval.py` (2026-09-23) is the CURRENT reliability eval and
    supersedes `reliability_eval.py`. The old metrics are now true by
    construction (typed output, pre-filtered candidates) and would
    report a meaningless 100%. It measures what can still go wrong with
    a decision model instead: **stability** (identical state twice ->
    identical tiers and order; max score drift), **separation** (does
    the rubric discriminate or collapse everything into one tier — a
    perfectly stable rubric that rates everything Solid is useless), and
    **calibration** as a descriptive confidence spread, since there is
    no ground truth to score against. It rebuilds live stats ONCE per
    scenario and reuses that state across repeats, so upstream API drift
    cannot masquerade as Jev instability. Costs ~12 real API calls, so
    it never runs automatically. NOT YET RUN — written, not executed.
  - NOTE the eval axis shifted: Jev emits no tokens, so "hallucination"
    is not its failure mode. Miscalibration is. Don't port the old
    factuality framing onto it.
  - `reliability_eval.py` is SUPERSEDED and marked DO NOT RUN at the top
    of the file. It still imports and still runs, which is the danger:
    every state key it reads is gone, so it would report 0 repair
    attempts and 0 violations and read as a perfect score rather than a
    missing measurement. Kept only for the record and for the historical
    numbers in `data/eval_results/`. Described below as it was:
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
- ADDED (2026-09-16): `meta_watcher.catch_up_if_stale()` +
  `CATCH_UP_STALE_THRESHOLD_HOURS` (20h default, overridable via
  `META_WATCHER_CATCHUP_THRESHOLD_HOURS` env var). Motivated by a
  user question ("if the wrapper's off, does n8n's fetched data get
  saved anywhere?") that surfaced a real misconception worth
  recording: n8n's Docker container NEVER holds the fetched stats
  data at all, even transiently — it only sends an HTTP POST and
  gets connection-refused if the wrapper's down, since all the
  actual API-fetching and file-writing happens inside the Python
  wrapper process on the host, not in Docker. So "buffer it in the
  container" isn't a coherent fix without duplicating
  rone_arena_client.py's/meta_watcher.py's logic into an n8n
  workflow — a real ongoing-drift risk, rejected in favor of making
  the wrapper self-heal instead. `meta_watcher_server.py` now checks
  the latest snapshot's age at startup and immediately runs a
  catch-up snapshot if it's stale, before the Flask server starts
  serving. Verified both branches directly: restarted the wrapper
  with a ~2-day-old snapshot present -> caught up immediately;
  restarted again right after -> correctly skipped ("recent enough").
  Still doesn't auto-start on boot/login — auto-start was offered
  TWICE (once before this fix, once after, when the user clarified
  their actual pattern: n8n/Docker stays on essentially always, the
  wrapper is the thing that's usually off, not just occasionally
  restarted) and declined both times in favor of staying manual. This
  is a deliberate, informed tradeoff, not an oversight: given that
  usage pattern, catch-up-on-start does NOT give daily snapshot
  granularity — it only captures "state at the moment I happened to
  start the wrapper," collapsing however many missed 06:00 triggers
  happened in between into a single point-in-time snapshot (and
  there's no way to backfill the missed days after the fact; the API
  only reflects current stats, not history). Don't re-litigate this
  as an unresolved gap or push auto-start again without new evidence
  the user's priorities changed.
- FOUND + FIXED (2026-09-23): the three stats endpoints each defaulted
  to a DIFFERENT trailing window, silently. `heroes_rank` 7 days,
  `hero_counters` 15, and `hero_compatibility` **1 day** — the last one
  because `get_hero_compatibility()` never passed `days` at all, not
  because the endpoint lacks it. Verified by matching win rates across
  endpoints: `hero_compatibility`'s no-`days` response equals the rank
  endpoint at `days=1` EXACTLY (six decimals, on Benedetta, Gloo,
  Thamuz and Atlas), and `hero_counters(days=15)` equals rank at
  `days=15`. Consequence: synergy data was one single day of matches
  sitting next to 15 days of counter data, and any arithmetic across
  the two measured window drift as much as matchup effect —
  Benedetta's own drift between windows (0.5324 -> 0.5273) is larger
  than most of the counter deltas involved. Fixed via
  `rone_arena_client.DEFAULT_WINDOW_DAYS = 7` (user's choice; verified
  supported on all three endpoints — at `days=7` every compatibility
  `hero_win_rate` matches rank at `days=7`, 10/10 across Miya and
  Gusion). After the change, all 6 heroes appearing in both endpoints
  agree to six decimals, 0 mismatches. Impact of the switch: counters
  15d->7d changed NOTHING (Aamon and Ixia returned identical 5-hero
  rosters); synergy 1d->7d churned ~2 of 5 heroes in every ally list
  (Gusion lost Barats/Thamuz, gained Chang'e/Minotaur; Miya lost
  Benedetta/Tigreal, gained Franco/Roger; Rafaela lost Baxia/Kalea,
  gained Kaja/Khufra) — which is itself the evidence that the 1-day
  synergy data was noise. NOT re-run after this change: the
  reliability eval. A single Aamon/exp end-to-end run was clean (35.3s,
  valid JSON first try, 0 constraint violations) but that is not a
  substitute.
- CORRECTED (2026-09-23, supersedes an earlier note from the same
  session): `hero_win_rate` inside a counter/compatibility sub-record
  is the sub-hero's OVERALL BASE win rate at the requested window, NOT
  a matchup-specific win rate. It is stable across different queries
  in the same window and matches `heroes_rank` exactly. An earlier
  reading of this as "the two endpoints disagree about a hero's win
  rate" was wrong — they were simply reporting different windows. The
  base win rate therefore needs NO extra API call. `main_hero_win_rate`
  (the queried hero's own base rate) is also in the same payload and
  is currently DISCARDED by `_parse_hero_relation_response`.
- `increase_win_rate` is a delta on the MAIN (queried) hero, not on the
  sub-hero: "Counters to Ixia: Benedetta -0.0262" means IXIA's win rate
  drops 2.6 points when Benedetta is present. There is no field
  anywhere giving the candidate's own win rate in a specific matchup —
  the full sub-record is `hero_appearance_rate, hero_index,
  hero_win_rate, heroid, increase_win_rate, min_win_rate6 ...
  min_win_rate20`. Those `min_win_rate*` fields are win rate bucketed
  by game duration (an early/late-game scaling curve) and are
  completely unused by this project.
- Log-odds aggregation was EVALUATED AND NOT ADOPTED (2026-09-23).
  Proposal was to combine pairwise win rates via log-odds addition
  instead of summing `increase_win_rate` directly. Findings: (a) the
  proposed function signature wants per-matchup win rates for the
  candidate, which the API does not provide (see above), so its inputs
  can't be satisfied without an unjustified zero-sum assumption; (b)
  on real data it produced the IDENTICAL ranking to naive summing —
  it works out to a near-constant x4 rescale (ratios 4.007-4.054),
  because `d(logit)/dp ~ 4` at p~0.5 and all MLBB win rates sit in
  0.45-0.56 where logit is effectively linear; (c) log-odds addition
  assumes independence, which is false for correlated matchups, and
  overstates confidence. It WOULD help at full 5-enemy draft, where
  naive sums can run away and log-odds saturates gracefully — revisit
  then, but don't expect it to change today's ordering. Related
  decision: don't pre-collapse the aggregate into a pseudo-probability
  before handing state to Jev, whose selling point is calibrated
  probabilities; feed it the components.
- RAG currently has NO discriminative power, and this is a corpus-size
  problem, not a retrieval bug: `data/raw/` holds 4 notes -> 4 chunks
  in the collection, and `retrieve_notes` queries with `k=4`. Every
  query therefore returns the ENTIRE knowledge base regardless of what
  was asked, so nothing is being ranked or excluded. The retrieval
  eval's 100% hit@4 / MRR 1.0 is measuring a system that cannot miss.
  Demonstrated 2026-09-23 by an accidental A/B on the Aamon/exp
  scenario: with retrieval broken (zero notes) and with it working,
  the agent returned the SAME three heroes in the same order (Gloo,
  Silvanna, Aulus; one score moved 0.01). None of the 4 notes mention
  Aamon or the exp lane. The deterministic cross-reference in
  `gather_live_stats` is doing essentially all the decision work; the
  LLM's distinct contribution is prose, some of it fabricated (it
  invented a "good win rate against Aamon" for Aulus, who is not in the
  counters list at all, and described all-negative `increase_win_rate`
  values as a "win rate increase" while still ranking them correctly).
  Fix is writing more notes, not tuning the retriever.
- GOTCHA: a mismatched `EMBEDDING_MODEL` fails SILENTLY at request
  time, not at startup. `.env` had been switched to
  `microsoft/harrier-oss-v1-0.6b` (1024-dim) while the Chroma
  collection was still built with `all-MiniLM-L6-v2` (384-dim), so
  every query raised `Embedding dimension 1024 does not match
  collection dimensionality 384`. `retrieve_notes` catches ALL
  exceptions and passes the string `"(Could not retrieve notes: ...)"`
  into the prompt as if it were content, so the agent produced a
  confident, well-formed, correct-looking answer with zero notes and
  nothing surfaced to the user. Re-ingest after ANY embedder change.
  Worth deciding whether retrieval failure should be loud.
- GOTCHA (Windows): two `python -m src.web.server` processes can BOTH
  hold `127.0.0.1:8600` in LISTENING state simultaneously, and the
  OLDER process wins connections. A server left running from an
  earlier session will therefore serve stale code with no error
  anywhere, and edits appear to have no effect. Check with
  `netstat -ano | grep :8600` and match PIDs via
  `Get-CimInstance Win32_Process`; use `DRAFT_COPILOT_PORT` to test on
  a separate port rather than killing someone else's process.
- Jev LIVE RESPONSE SHAPE, confirmed against real calls 2026-09-23.
  `answers.<key>` = `{type, score, legend, probabilities, confidence}`;
  top level = `{answers, id, model, provider, usage}`. **`score` is a
  FLOAT**, neither an ordinal index nor a label — it is the
  probability-weighted expected tier index, and `sum(i * p[i])`
  reproduced it to within 0.01 on all 9 answers observed. That makes it
  a CONTINUOUS ranking signal, which solves the tie problem four coarse
  tiers would otherwise have. The response also carries its own
  `legend` ({"0":"Fallback",...}); `parse_answers()` reads tiers from
  that rather than assuming the local list survived the round trip.
  Tier = the MODE of `probabilities`, not `round(score)`: with a
  0.45/0.55 split the mean can land on a level Jev never favoured.
  An earlier parser that handled only int and str scores returned
  `tier: None` for every row — caught precisely because the first live
  call was run as a probe instead of being trusted.
- Jev FAN-OUT IS FREE, measured: 1 candidate 891ms, 7 candidates 859ms
  in the same session. N questions cost one round trip, which is the
  architectural claim the whole design rests on. Wall clock 594-891ms
  is above JEV.md's stated 70-500ms, but that includes network RTT.
  Cost for the 7-candidate call: **$0.00018** (4275 input / 130 output
  tokens). Cost is not a constraint at this scale.
- Jev STABILITY: identical state twice gave 2.99 vs 2.98 — close to
  deterministic but not exactly, so treat small score differences as
  noise, not signal. Note-text A/B on the same scenario (prose stripped,
  `note_support` scalar kept) moved the score 2.99 -> 2.97, barely
  outside that noise band, i.e. the PROSE made no measurable difference
  and the scalar carried the signal. Single scenario, so inconclusive
  rather than settled; the sharper test is the adversarial Edith note.
- CANDIDATE POOL SHAPE (21 rows, 6 scenarios, 2026-09-23). These
  constrain any rubric and were measured before writing one:
  `win_rate_delta` -0.085..+0.086, `counter_strength` 0..0.049 (p50
  0.027), `synergy_strength` 0..0.051 (nonzero in only 7/21),
  `rag_score` 0..0.202 (nonzero in only 3/21). Critically: **0/21 rows
  countered more than one enemy** and **1/21 had both counter and
  synergy**, so any tier gated on "multiple enemies" or "counter AND
  synergy" would never fire. 10/21 had a losing win rate. The pool is
  also pre-filtered twice (API returns top-5 counters; lane filter),
  so every candidate is already decent — which is why the bottom tier
  is "Fallback" (weakest of a good set) and not "Avoid".
- RAG_SCORE THRESHOLD is 0.30 and is NOT portable
  (`src/rag/scoring.py`). It depends on the embedding model, the
  distance space AND the query wording together. Measured for the
  Harrier embedder with the query `retrieve_notes` builds: realistic
  draft queries score 0.17-0.41, a draft with no applicable note tops
  out at 0.287, and the weakest true positive is 0.409 — so 0.30 sits
  in a 0.122-wide gap. For scale: verbatim note text scores 0.96 and a
  close paraphrase 0.72, which is why thresholds borrowed from
  cosine-similarity intuition (0.70) return 0.0 unconditionally. An
  earlier 0.70 and then 0.50 both did exactly that, including on the
  Esmeralda/Lapu-Lapu case the threshold exists to catch.
  IMPORTANT: the zeros for heroes with no notes come from Noisy-OR's
  empty-list branch, NOT from the threshold. Lowering the threshold
  cannot make a note-less hero non-zero; it only controls whether real
  evidence registers.
- QUERY FORMAT MATTERS AND WAS TESTED (2026-09-23). A structured,
  instructional query ("Find strategy notes relevant to this draft
  query: - Lane needed: ... - Ally Picks: ...") was tested against the
  current terse `"Draft advice for: <lane>, <enemies>, <allies>"` and
  REJECTED. Its constant boilerplate lifted the NOISE FLOOR from 0.287
  to 0.404 while barely moving true positives, collapsing the usable
  gap from 0.122 to 0.020 and producing false positives on drafts with
  no relevant note. It also caused a ranking regression: with allies in
  the draft the correct note fell from rank 1 to rank 3, behind a note
  about an ally. Mechanism: the query is not an instruction, nothing
  reads it — it is a point in vector space, and identical boilerplate
  in every query pulls all queries toward a common generically-note-like
  direction, compressing relative differences. Keep queries dense with
  discriminative tokens. This is the OPPOSITE of prompting an LLM,
  which is why the structured version looks like it should help.
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
  web app) to avoid stale connections.
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
  restarted whenever the schedule needs to fire. Partially
  mitigated 2026-09-16: it now self-heals on startup instead of
  silently missing whatever ran while it was off — see the empirical
  findings entry below (`catch_up_if_stale`). Still no auto-start, so
  a missed window only gets backfilled once you actually restart it,
  not the moment it's missed.
- UI migration (2026-09-19): the Streamlit dashboard was replaced by the
  Flask + HTML/Tailwind web app in `src/web/` (see Architecture). Passed
  an independent finish review (verdict: ship, after one fix round:
  nested cards, gold-reservation breach, an unlabeled model score that
  read as a win probability, sticky mobile header, lead-card weight,
  one contrast miss). VERIFIED: every API endpoint live (CRUD, guards,
  a real Aamon/exp recommendation with correct evidence tags); every JS
  module parses as ES modules; headless-Chrome captures of the draft,
  result, loading, failure, notebook and dialog states at 1440 and a
  true 390px viewport. NOT VERIFIED: a real click-through of the browser
  UI against the live LLM (the result/failure captures used a fetch stub
  of `/api/recommend` shaped from a real response); the edit/delete/
  rebuild/Meta-Watcher-toggle handlers were exercised server-side but
  not driven through the UI; touch scrolling in the hero pool's inner
  scroll region; real keyboard/screen-reader passes. Known state: the
  header shows "Rebuild needed" until one knowledge-base rebuild is done
  through the app (records the notes fingerprint).
  `retrieval_golden_set.py` is now STALE: three notes it references
  (general philosophy, Dyrroth, one Esmeralda) were deleted from
  `data/raw/`, so `retrieval_eval` will report misses that are label
  drift, not retrieval failure — re-label before trusting it.
  Ideas not built: a "lock in" action on the lead pick that places it in
  the next empty ally slot; real hero portraits (licensing);
  optional decorative raster via the Gemini key (unwired, cost unconfirmed).
- JEV MIGRATION SHIPPED 2026-09-23 (the entry below is the superseded
  exploration note, kept for the access details). Status: qwen dropped
  entirely, graph rewired, rationale templated, server contract and UI
  updated, `jev_eval.py` written. The Vercel AI Gateway route in the
  note below is NOT what shipped — `api.openjev.sh` with `OPEN_JEV_KEY`
  is, and it sidesteps the Vercel credit-card 403 entirely.
  VERIFIED: end-to-end through `/api/recommend` (HTTP 200, 6.1s warm,
  8 candidates tiered Priority..Fallback with templated rationales);
  through the graph's `__main__`; response shape pinned by a 4-call
  probe. NOT VERIFIED: `jev_eval.py` has never been executed, and no
  regression run exists comparing Jev's picks against qwen's on the
  golden scenarios — the old eval could not be reused for that.
  WATCH FOR: `/api/health` still reports `{"ollama":true,"model":
  "qwen2.5:3b"}` and the header chip still renders it, so the UI
  advertises a dependency the pipeline no longer has. `draft.js`'s
  `TYPICAL_SECONDS = 30` and the loading copy ("A local model reads...
  15 to 30 seconds") are stale for the same reason. Neither was fixed.
  PRODUCT.md and `.impeccable/surfaces/src-web-static-index-html.md`
  are ALSO stale on all of this (they still describe the 3B local
  model, the self-repair loop, and 15-30s generation), and PRODUCT.md's
  principle 4 ("stay local-first and $0-cost by default") is now in
  tension with a paid third-party dependency — worth an explicit
  decision rather than silent drift.
  `misc/jev_probe.py` is the 4-call probe (stability, note-text A/B,
  fan-out). It originally had no `if __name__ == "__main__"` guard and
  IMPORTING it fired all four calls; the guard is now there.
- Jev EXPLORATION — SUPERSEDED, see above. (2026-09-23, written while
  it was not yet implemented.)
  Jev is a third-party "System 1" decision model (TypeSafe AI, released
  Sept 2026, after this assistant's training cutoff — everything known
  about it comes from `JEV.md`, which is gitignored/local-only, as is
  `misc/`). It generates no text: given a `state` plus `questions` it
  returns typed primitives — `Choice`, `Score` (2-10 level rubric),
  `Noul` (boolean probability) — with calibrated probabilities in
  70-500ms, all questions answered in one parallel pass. Access is via
  the Vercel AI Gateway. `misc/jev_test.py` was fixed this session: the
  endpoint is `https://ai-gateway.vercel.sh/v1/evaluate`, NOT
  `gateway.ai.vercel.com` (that host resolves to a Vercel anycast IP,
  so DNS looks fine, but drops the TLS handshake — surfaces on Windows
  as a misleading `ConnectionError: ('Connection aborted.',
  FileNotFoundError(2, ...))` that looks like a missing cert). Also
  removed a `verify=False` that was disabling TLS verification on a
  request carrying the API key while fixing nothing. CURRENT BLOCKER,
  not code: the gateway returns 403
  `customer_verification_required` — Vercel requires a credit card on
  file before servicing any request, even on free credits. The key
  itself authenticates fine (`GET /v1/models` returns the model list,
  and `/v1/evaluate` validates the payload schema). STILL UNVERIFIED
  because of that gate: whether `typesafe-ai/jev` is the right model
  slug, and whether the response keys `jev_test.py` reads
  (`answers.<key>.probability` / `.score` / `.confidence`) match what
  Jev actually returns. Motivation worth keeping straight: the user
  framed this as speeding up RAG, but per `JEV.md` Jev does no
  embedding, retrieval or generation, and retrieval is neither slow nor
  discriminative here (see the 4-chunk finding above). The real target
  is the 6-15s generation step, which is largely narrating a decision
  the deterministic cross-reference already made — lane-eligibility is
  a `Noul`, `priority_score` is a `Score`. Jev cannot produce the
  free-text `rationale`/`summary` fields at all. A node-by-node mapping
  of the pipeline onto Jev's three primitives was offered but not yet
  done.
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
