# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user today: the developer, drafting picks during their own Mobile Legends: Bang Bang ranked games (or planning scenarios ahead of time). Stated long-term aspiration: other MLBB players eventually — this is a real intent, not yet a validated one, and current architecture does not yet support it (see Capabilities and Constraints).

## Product Purpose

An agentic draft assistant for Mobile Legends: Bang Bang. Given the current draft state (allies picked, enemies picked, banned heroes, lane role needed), it returns ranked hero recommendations with priority scores and rationale. Success means recommendations that are valid (schema-conformant), constraint-compliant (never an already-picked/banned or lane-ineligible hero), and actually grounded in the live stats and curated notes the pipeline fetched — not just plausible-sounding text that happens to satisfy the schema.

## Positioning

Deliberately does not treat every data source the same way, which is the common mistake in RAG demos: fast-changing, structured stats (win/pick/ban rates, counters, compatibility, lane rosters) are fetched via direct tool-calls at query time and never embedded; narrative strategic judgment (the user's own curated notes) goes through RAG instead, since that's the kind of content retrieval was actually designed for. On top of that split, reliability is treated as something to measure, not assume: a self-repair loop for invalid structured LLM output, deterministic post-generation filters for constraint compliance, and a growing eval harness (JSON-validity rate, constraint-violation rate, RAG retrieval hit-rate/MRR) that has already found and fixed two real grounding/hallucination bugs with verified before/after numbers, not just a prompt tweak taken on faith. A neighboring "wire an LLM to a MOBA stats API" clone could not truthfully make the same measured-reliability claim.

## Operating Context

Runs on a single Windows machine today: a local Flask web app with a static HTML/Tailwind frontend (it replaced an earlier Streamlit dashboard), a local Ollama LLM (qwen2.5:3b, chosen for an 8GB RAM constraint), a Chroma vector store over user-authored Markdown/PDF/DOCX strategy notes, and the free, unofficial Rone Arena API for live hero stats. A separate Meta-Watcher agent snapshots stats over time to detect meta drift; it's normally scheduled via n8n-in-Docker (which needs a local Flask wrapper running), but can now also run fully unattended via a GitHub Actions scheduled workflow that commits snapshots back into the repo — a deliberate, one-off exception to the local-first rule (see Product Principles), made because the alternative genuinely required a machine to stay powered on. A `run_dashboard.bat` double-click launcher exists for non-terminal use on Windows.

## Capabilities and Constraints

- Draft recommendation: ally/enemy picks, bans, and lane role in, ranked hero suggestions with priority scores and rationale out.
- Strategy note authoring, editing, and deletion from the app's Notebook view (Markdown/text notes are editable; PDF/DOCX are listed but not editable), with a prompt to rebuild the knowledge base when notes and index fall out of step.
- Meta trend detection (Meta-Watcher), deliberately NOT LLM-driven — deterministic snapshot + diff against a configurable drift threshold.
- Eval harness covering structured-output reliability, constraint compliance, and RAG retrieval quality. Recommendation *quality* (are the picks actually good, beyond valid and grounded) is explicitly not yet evaluated — would need LLM-as-judge or manual labeling.
- Constraint: the local LLM is a small (3B-parameter) model on constrained hardware — expect real latency (roughly 15-30s per generation) and occasional first-try structured-output failures. This is a designed-for constraint the self-repair loop exists to handle, not a bug to hide.
- Constraint: the current implementation is single-user and single-machine throughout — local file storage for notes and snapshots, browser-local (localStorage) draft state, no auth, no multi-tenancy. The "other MLBB players eventually" aspiration is not yet reflected in the architecture; real design work (auth, shared/hosted storage, hosting itself) would be needed before it's true.
- Windows-specific tooling assumptions run throughout (the `.bat` launcher, Docker Desktop for n8n, a Norton-Antivirus-specific SSL certificate workaround) — not yet verified cross-platform.

## Brand Commitments

None established. Working title is "Mobile Legends Draft Copilot" (README) and "Draft Copilot" (the app's wordmark). A visual world now exists in the built app (see DESIGN.md once documented), but it was chosen in a design round rather than stated by the user as a binding commitment, so it isn't recorded here as one. No logo file exists; hero portraits are generated initials badges, since no hero art exists.

## Evidence on Hand

- Real (not placeholder) strategy notes exist for a handful of heroes (Lolita, Dyrroth, Angela, Lapu-Lapu, Esmeralda) plus one general drafting-philosophy note.
- Real eval results exist under `data/eval_results/` (reliability and retrieval runs), and real Meta-Watcher snapshots under `data/snapshots/`, with genuine before/after fix evidence recorded in `CLAUDE.md`.
- No hosted or public demo, no testimonials, no case studies, and no other users yet exist — future work must not fabricate any of these. The "other MLBB players eventually" audience is a stated intent, not a validated or built-toward one.

## Product Principles

1. Match the data source to the retrieval mechanism deliberately — fast-changing structured stats via tool-calls, curated narrative judgment via RAG — rather than defaulting to "embed everything."
2. Treat reliability as measurable, not assumed: every fix to LLM behavior (structured-output validity, constraint compliance, grounding in live data) is backed by a before/after eval run, not just a plausible-sounding prompt tweak.
3. Enforce hard constraints in code, not only in the prompt — small local models don't reliably self-police pick/ban/lane rules, so deterministic filters are the actual guarantee, not a suggestion to the model.
4. Stay local-first and $0-cost by default; step outside that only deliberately, piece by piece, when the alternative genuinely cannot work locally, and only when the replacement is still free and free of card/billing risk.
5. Design for a single local user today without assuming that's permanent — "other MLBB players eventually" is a real aspiration that the current architecture (local file storage, single-session state, no auth) does not yet support.

## Accessibility & Inclusion

No product-specific accessibility requirement established yet.
