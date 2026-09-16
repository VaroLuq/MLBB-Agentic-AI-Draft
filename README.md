# Mobile Legends Draft Copilot

An agentic draft assistant for Mobile Legends: Bang Bang — combines
live hero stats (Rone Arena API) with RAG over your own curated
strategy notes, orchestrated with LangGraph. Runs fully locally, no
paid APIs.

## Why it's built this way

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
- [Ollama](https://ollama.com), with `qwen2.5:3b` pulled and running
  locally (`ollama pull qwen2.5:3b`)
- (Optional, for scheduled Meta-Watcher runs) Docker Desktop

## Quick start

```bash
git clone <this-repo>
cd MLBB-Draft

python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
cp .env.example .env            # no API key needed, defaults work out of the box

python -m src.rag.ingest        # index the sample strategy notes
streamlit run src/ui/app.py
```

Make sure Ollama is running before you open the dashboard. From the
draft board you can select ally/enemy picks, bans, and the lane you
need, then get a ranked recommendation with live stats and retrieved
notes shown alongside it. The sidebar shows a live meta snapshot and
lets you add/browse strategy notes and rebuild the knowledge base
without leaving the browser.

**Windows tip:** double-click `run_dashboard.bat` instead of using the
terminal each time — see "Desktop launcher" below.

## Project structure

| Path | What it is |
|---|---|
| `src/api_client/rone_arena_client.py` | Live stats (win rates, counters, compatibility) via direct API calls |
| `src/rag/` | Curated strategy notes → embeddings → Chroma vector store |
| `src/agents/draft_agent.py` | LangGraph agent: gather stats → retrieve notes → generate → validate (self-repair loop on invalid JSON) |
| `src/agents/meta_watcher.py` | Deterministic snapshot + drift-detection agent (no LLM needed) |
| `src/ui/app.py` | Streamlit dashboard |
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
`python -m src.rag.ingest` (or click "Rebuild knowledge base" in the
dashboard sidebar) to index new notes.

## Evaluating the Draft Agent

Since the Draft Agent's LLM output is non-deterministic, "does it
work" needs to be measured across repeated runs, not spot-checked
once. `src/eval/reliability_eval.py` measures three concrete things
against a fixed set of golden draft scenarios (`src/eval/scenarios.py`):

1. **JSON validity rate** — how often qwen2.5:3b produces valid
   structured output on the first try vs. needing the self-repair
   loop vs. failing even after retries.
2. **Repair-loop rescue rate** — of the runs that failed on the first
   try, how many did the repair loop actually save.
3. **Raw constraint-violation rate** — how often the LLM recommends
   an already-picked/banned or lane-ineligible hero *before* the
   deterministic filters remove it, i.e. how much real work those
   filters are doing.

```bash
python -m src.eval.reliability_eval                    # all scenarios, 2 repeats each
python -m src.eval.reliability_eval --repeats 5         # more repeats, tighter estimate
python -m src.eval.reliability_eval --scenario early_jungle
```

Each run is a real local LLM call, so this is slow (minutes, not
seconds) — progress prints per-run.

`src/eval/retrieval_eval.py` separately evaluates RAG retrieval
quality — independent of LLM generation, since a bad recommendation
could be the LLM's fault or the retriever's fault, and this tells you
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

`run_dashboard.bat` starts the dashboard with one double-click — no
terminal navigation needed. Right-click it → **Send to** → **Desktop
(create shortcut)** for a normal desktop icon. A console window stays
open behind the browser tab (closing it stops the app); Ollama still
needs to be running separately.

## Meta-Watcher: standalone trend detection

```bash
python -m src.agents.meta_watcher
```

Snapshots current hero stats to `data/snapshots/`, then diffs against
the previous snapshot to flag heroes whose win/pick/ban rate moved by
2+ percentage points. Every run — manual or scheduled — is logged to
`data/snapshots/drift_log.txt`.

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
