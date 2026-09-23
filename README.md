# Mobile Legends Draft Copilot

An agentic draft assistant for Mobile Legends: Bang Bang — combines
live hero stats (Rone Arena API) with RAG over your own curated
strategy notes, orchestrated with LangGraph. Everything runs locally
except the final ranking call, which goes to Jev (a hosted decision
model) at roughly $0.0002 per recommendation.

## Why it's built this way

The draft agent doesn't generate its recommendation — it ranks. Live
stats are cross-referenced against the lane roster in plain Python to
build a candidate list, each candidate is scored for note relevance,
and Jev assigns a tier against a fixed rubric. The rationale you read
is templated from those same numbers, so it can only state things that
are true by construction. An earlier version had a local 3B model
write the picks and the prose, guarded by a JSON self-repair loop and
post-hoc constraint filters; it was slower, and it was caught
inventing matchup claims that weren't in its context.

Live, structured stats (win rates, counters, compatibility) are
fetched via direct API tool-calls at query time — they change too
often and are too precise to embed and risk retrieving stale.
Narrative strategy content (drafting philosophy, hero-specific
reasoning) goes through RAG instead, and is manually curated by you
rather than scraped, since your own judgment is more valuable RAG
content than generic guides. A separate Meta-Watcher agent covers the
one thing the live API can't: historical trend detection, by
snapshotting stats over time.

## Prerequisites

- Python 3.11+
- An `OPEN_JEV_KEY` in `.env` — the draft agent ranks candidates with
  [Jev](https://api.openjev.sh), a hosted decision model. Calls cost
  roughly $0.0002 each.
- (Optional, for scheduled Meta-Watcher runs) Docker Desktop

Ollama is no longer required. An earlier version generated
recommendations with a local `qwen2.5:3b`; that model was replaced by
Jev and nothing in the pipeline imports it any more.

## Quick start

```bash
git clone <this-repo>
cd MLBB-Draft

python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
cp .env.example .env            # then add your OPEN_JEV_KEY

python -m src.rag.ingest        # index the sample strategy notes
python -m src.web.server --open # starts the app and opens http://localhost:8600
```

On the **Draft** view, add the heroes already picked and
banned, choose the lane you need, and request a ranked
recommendation. Each pick shows the live-data or note evidence
behind it, and "What the agent saw" exposes the live stats, the
cumulative counter/synergy table, the retrieved notes and Jev's raw
response. Each pick carries a tier (Priority / Solid / Marginal /
Fallback) and the confidence behind it. The **Notebook** view is
where you write, edit and delete strategy notes and rebuild the
knowledge base. The app only listens on localhost.

**Windows tip:** double-click `run_dashboard.bat` instead of using the
terminal each time — see "Desktop launcher" below.

## Project structure

| Path | What it is |
|---|---|
| `src/api_client/rone_arena_client.py` | Live stats (win rates, counters, compatibility) via direct API calls |
| `src/rag/` | Curated strategy notes → embeddings → Chroma vector store |
| `src/agents/draft_agent.py` | LangGraph agent: gather stats → retrieve notes → score candidates with Jev |
| `src/agents/jev_client.py` | Jev adapter: builds the candidate state + rubric, one batched request, templates the rationale |
| `src/rag/scoring.py` | Note-relevance scoring (Noisy-OR) feeding each candidate's `rag_score` |
| `src/agents/meta_watcher.py` | Deterministic snapshot + drift-detection agent (no LLM needed) |
| `src/web/` | The app: Flask JSON API (`server.py`) wrapping the agents/RAG unchanged, plus the static frontend in `static/` (HTML, Tailwind CSS, vanilla JS modules) |
| `data/raw/` | Your strategy notes (general + per-hero) |
| `data/snapshots/` | Meta-Watcher's historical snapshots + drift log |

## Adding your own strategy notes

```bash
python -m src.rag.add_note "Lolita's shield counters burst-heavy dive comps" --hero Lolita
python -m src.rag.add_note "Ban high-mobility assassins first in gold-heavy metas"
```

Or drop a `.md`/`.txt`/`.pdf`/`.docx` file directly into
`data/raw/general/` (hero-agnostic) or `data/raw/heroes/<HeroName>/`
(hero-specific — folder name is the tag). Then re-run
`python -m src.rag.ingest` (or use "Rebuild knowledge base" in the
Notebook view) to index new notes. Notes can also be written, edited
and deleted from the Notebook view itself; it tells you when the
knowledge base has fallen out of step with them.

## Evaluating the Draft Agent

Jev's output is near-deterministic but not exactly so, and a rubric
can be perfectly stable while still being useless — so "does it work"
is measured across repeated runs against a fixed set of golden draft
scenarios. `src/eval/jev_eval.py` measures three things:

1. **Stability** — given byte-identical state, does a repeat run
   return the same tiers in the same order? Reported with the largest
   score drift any candidate showed.
2. **Separation** — does the rubric discriminate, or collapse every
   candidate into one tier? A stable rubric that rates everything
   "Solid" tells you nothing.
3. **Calibration** — the confidence spread. Descriptive only: there's
   no ground truth here to score against.

```bash
python -m src.eval.jev_eval
```

Live stats are fetched once per scenario and reused across repeats, so
upstream API drift can't masquerade as model instability. Each run is
a real API call (~12 per invocation, a fraction of a cent), so it
never runs automatically.

`src/eval/reliability_eval.py` is **superseded and should not be run**.
It measured JSON-validity, repair-loop rescue rate and raw constraint
violations — all of which are now true by construction, since Jev
returns typed output and is handed a candidate list that has already
been filtered for lane eligibility and used heroes. It still executes,
which is the trap: it would report zero failures and read as a perfect
score rather than a missing measurement. It's kept for the historical
numbers in `data/eval_results/`.

`src/eval/retrieval_eval.py` separately evaluates RAG retrieval
quality — independent of ranking, since a bad recommendation could be
the retriever's fault rather than the rubric's, and this tells you
which. It queries the vector store directly against a hand-labeled
set of query → expected-note pairs (`src/eval/retrieval_golden_set.py`),
measuring hit@k and Mean Reciprocal Rank. No LLM calls, so it's fast
(seconds):

```bash
python -m src.rag.ingest              # make sure the vector store is current first
python -m src.eval.retrieval_eval
```

Both evals save results to `data/eval_results/` (one JSON file per
run) and append to a shared `data/eval_results/eval_log.txt` for
tracking over time. Together they measure reliability and
retrieval correctness, not recommendation *quality* (i.e. whether the
picks are actually good) — that's a harder, more subjective eval and
a likely next step.

## Desktop launcher (Windows)

`run_dashboard.bat` starts the app with one double-click and opens it
in your browser — no terminal navigation needed. Right-click it →
**Send to** → **Desktop (create shortcut)** for a normal desktop
icon. A console window stays open behind the browser (closing it
stops the app), and launching it again while it's running just
reopens the existing instance. The port defaults to 8600; set
`DRAFT_COPILOT_PORT` to change it.

## Frontend styling

The stylesheet `src/web/static/app.css` is built from
`src/web/styles/input.css` with Tailwind's standalone CLI (no npm
needed) and the built file is committed, so running the app never
requires a build. To change styles, download
`tailwindcss-windows-x64.exe` from the
[Tailwind releases](https://github.com/tailwindlabs/tailwindcss/releases)
into `tools/` (git-ignored) as `tailwindcss.exe`, then:

```bash
tools\tailwindcss.exe -i src/web/styles/input.css -o src/web/static/app.css --minify
```

Fonts (Barlow, Barlow Condensed) are self-hosted in
`src/web/static/fonts/`; nothing loads from a CDN at runtime. Hero
portraits are generated initials badges, since no hero art ships
with the project.

## Meta-Watcher: standalone trend detection

```bash
python -m src.agents.meta_watcher
```

The command snapshots current hero stats to `data/snapshots/`, then
diffs against the previous snapshot to flag heroes whose win/pick/ban
rate moved by 2+ percentage points. Every run, manual or scheduled,
is logged to `data/snapshots/drift_log.txt`.

## Optional: scheduling Meta-Watcher with n8n

For unattended daily snapshots, n8n runs in Docker (its official image
ships prebuilt, no native build tools needed) and calls a small local
HTTP wrapper instead of your Python environment directly, since a
containerized n8n can't reach the host venv:

```bash
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n
python -m src.agents.meta_watcher_server   # leave running whenever the schedule is active
```

Then open `http://localhost:5678`, create an owner account, and
import `n8n/meta_watcher_schedule.json` (**Import from File**). It's a
Schedule Trigger → HTTP Request node posting to
`http://host.docker.internal:8765/run`. Activate the workflow (toggle,
top-right of the editor) for the daily schedule to run unattended.

If the wrapper happens to be off when the schedule fires, that run is
just lost — n8n's Docker container never holds the fetched data
itself (all the API-calling and file-writing happens inside the
wrapper on the host, not in Docker), so there's nothing to replay
later. To avoid silently missing snapshots, the wrapper self-heals
instead: every time it starts, it checks whether the most recent
snapshot is more than 20 hours old and immediately takes a catch-up
one if so — so restarting it after any downtime backfills the gap
rather than waiting for tomorrow's trigger.

## Troubleshooting

**`SSLCertVerificationError` on any HTTPS call (API requests or
`pip install`):** usually antivirus/corporate HTTPS inspection
injecting its own root CA that Python doesn't trust by default. Fix:
point `REQUESTS_CA_BUNDLE` in `.env` at a combined bundle (your AV's
cert + certifi's public CA bundle — **not** the AV's cert alone, which
would break any site *not* being intercepted). See `.env.example` for
the exact command to generate one.

## Data source disclaimer

This project uses the Rone Arena API, an unofficial, community-
maintained data source for Mobile Legends: Bang Bang. It is not
affiliated with or endorsed by Moonton. Used here for learning/
portfolio purposes only.
