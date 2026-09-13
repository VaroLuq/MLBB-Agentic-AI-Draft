# Mobile Legends Draft Copilot

An agentic draft assistant combining live hero stats (via the Rone
Arena API) with RAG over community strategy guides, orchestrated with
LangGraph. Runs fully locally — no paid APIs.

## Why this project 

Most RAG demos treat every data source the same way: embed it, retrieve
it. This project deliberately does NOT do that. Live, structured stats
(win rates, counters, compatibility) are fetched via direct API
tool-calls at query time — they change too often and are too precise
to embed and risk retrieving stale. Narrative strategy content (guides,
build reasoning) goes through RAG, since it's the kind of unstructured
text retrieval was actually designed for. A separate Meta-Watcher agent
handles the one thing the live API can't give us: historical trend
detection, by snapshotting stats over time ourselves.

## Setup

**1. Create and activate a virtual environment**

```bash
cd ml-draft-copilot
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure environment**

```bash
cp .env.example .env
```

No API key needed for the Rone Arena heroes/academy endpoints — they're
public. Ollama setup is the same as the Work Knowledge Base project
(see that project's README if you need a refresher): install Ollama,
run `ollama pull qwen2.5:3b`, leave it running in the background.

**4. Test the API client**

```bash
python -m src.api_client.rone_arena_client
```

## Project status

- [x] Environment scaffold
- [x] Phase 1: API client layer (Rone Arena SDK wrapper) — verified
      against live data: hero list, rank stats, counters, and
      compatibility all confirmed working with real responses
- [x] Phase 2: RAG ingestion — REWORKED to use manually curated
      strategy notes instead of API-sourced guides (see below)
- [x] Phase 3: Draft Agent (LangGraph, tool-calling + RAG + self-repair loop)
- [x] Phase 4: Streamlit dashboard
- [x] Phase 5: Meta-Watcher agent (snapshot + drift detection) —
      snapshot/reload/diff mechanics verified against live data
      (15-min-gap test run, correctly reported no significant drift).
      Real drift detection over a meaningful time gap will be
      confirmed naturally once Phase 6 scheduling has run for a day.
- [x] Phase 6: n8n scheduling — verified end-to-end: n8n (Docker) ->
      HTTP wrapper (host) -> Meta-Watcher -> snapshot + drift check,
      triggered via the workflow's "Execute Node" and confirmed in
      `data/snapshots/drift_log.txt`. Still needs the workflow
      **activated** (toggle in the n8n UI) for the daily schedule to
      actually run unattended — see below.
- [ ] Phase 7 (stretch): Eval harness

## Using the dashboard 

Make sure Ollama is running, then:

```bash
streamlit run src/ui/app.py
```

From the draft board you can select ally/enemy picks, bans, and the
lane you need, then get a ranked recommendation with live stats and
retrieved notes shown alongside it (expand "What the agent saw" to
inspect). The sidebar shows a live meta snapshot and lets you add new
strategy notes and rebuild the knowledge base without leaving the
browser.

## Testing the Draft Agent 

Make sure Ollama is running and you've ingested at least one note
(Phase 2), then:

```bash
python -m src.agents.draft_agent
```

This runs a sample scenario (ally has picked Lolita, enemies have
picked Marcel and Hirara, role needed: jungle) through the full graph:
live stats gathering -> RAG retrieval -> LLM recommendation -> JSON
validation (with up to 2 self-repair attempts if the model's first
output isn't valid JSON).

**Please report back the full output**, including whether it needed
any repair attempts — that's a genuinely useful signal about how
reliably qwen2.5:3b follows the JSON format instruction without help.
Also worth checking: do the recommended heroes actually make sense
given the Lolita shield-counters-burst-comps note we seeded in Phase
2? If the LLM's reasoning ignores that note, we may need to weight
retrieved notes more heavily in the prompt.

## Testing the Meta-Watcher agent 

The live Rone Arena API only ever reflects a rolling window (e.g.
"last 7 days") — it has no memory of where a hero's win/pick/ban rate
stood before. The Meta-Watcher fills that gap itself, by snapshotting
`get_hero_rank_stats()` to disk over time and diffing snapshots to
surface heroes trending up or down.

```bash
python -m src.agents.meta_watcher
```

Each run takes a fresh snapshot into `data/snapshots/<timestamp>.json`,
then compares it against the previous snapshot (if one exists) and
prints a drift report — heroes whose win/pick/ban rate moved by at
least 2 percentage points, largest swing first. On the very first run
you'll just see "not enough snapshots yet"; run it a second time
(ideally after some real time has passed, so the stats have had a
chance to actually move) to see drift detection kick in.

**Please report back the full output of two consecutive runs** —
that's the first real check that snapshot writing, reloading, and the
diffing logic all work end-to-end against live data. Automating this
on a recurring schedule (rather than manual re-runs) is Phase 6, via
n8n.

Every run (manual or scheduled) also appends its result to
`data/snapshots/drift_log.txt`, timestamped — a durable, plain-text
history that doesn't depend on n8n's own execution log retention.

## Setting up n8n scheduling 

**Why Docker, and why an HTTP wrapper instead of Execute Command:**
the original plan was `npx n8n` on the host with an Execute Command
node calling the Meta-Watcher CLI directly (no server needed). That
hit a real blocker: n8n depends on a native module (`isolated-vm`)
that needs `node-gyp`/Visual Studio Build Tools to compile, which
this machine didn't have — installing that toolchain just to run n8n
was too heavy for what should be a light dependency. **n8n's official
Docker image ships prebuilt, sidestepping that entirely.** The
trade-off: a Dockerized n8n can't reach the host venv's Python
directly, so instead of Execute Command, the workflow calls a small
local HTTP endpoint (`src/agents/meta_watcher_server.py`) over
Docker Desktop's `host.docker.internal`.

**1. Start n8n in Docker** (Docker Desktop must be running first):

```bash
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n
```

Open `http://localhost:5678` and create an owner account on first run
(local-only, no external signup, nothing leaves your machine).

**2. Start the Meta-Watcher HTTP wrapper** and leave it running
whenever the n8n schedule is active:

```bash
python -m src.agents.meta_watcher_server
```

This listens on `http://localhost:8765` (`/health` to check it's up,
`/run` to trigger a snapshot+drift cycle — same
`run_snapshot_and_report()` the CLI uses, so behavior is identical).
It binds to `0.0.0.0` rather than just `localhost`, because
`host.docker.internal` reaches the host over a virtual network
interface, not loopback — worth knowing since that also means
anything else on your LAN could technically reach it; fine for a
local portfolio project, not something to expose beyond a trusted
network.

**3. Import the prebuilt workflow**: in the n8n UI, use the menu's
**Import from File** option and select `n8n/meta_watcher_schedule.json`
from this repo. It contains two nodes:
- **Daily Schedule** — a Schedule Trigger, default set to fire once a
  day at 06:00.
- **Run Meta-Watcher** — an HTTP Request node POSTing to
  `http://host.docker.internal:8765/run`.

**4. Activate the workflow** with the toggle in the top-right of the
n8n editor for the daily schedule to actually run unattended. You can
also click "Execute Node" on **Run Meta-Watcher** to trigger one run
immediately without waiting for the schedule.

**Verified working** (2026-09-12): triggered via "Execute Node",
returned `Snapshot saved to: data\snapshots\20260912_130417.json` /
`No significant drift between ...` — confirmed end-to-end in
`data/snapshots/drift_log.txt` too. One thing still worth doing:
activate the workflow and let it run unattended overnight to confirm
the *schedule* itself fires correctly, not just a manual trigger.

**Related fix baked into `.env`**: outbound HTTPS calls (to
`arena.rone.dev`, and to PyPI during `pip install`) were failing with
`SSLCertVerificationError` on this machine — caused by Norton
Antivirus's HTTPS inspection injecting its own root CA, which
Python's `requests`/`pip` don't trust by default even though the OS
does. Fixed via `REQUESTS_CA_BUNDLE` in `.env` (see that file's
comments) pointing at Norton's exported cert. If you don't run
Norton, you likely won't hit this at all; if you do, or you're behind
a similar corporate SSL-inspecting proxy, see `.env.example` for the
general fix.

## Narrative content: manually curated, not API-sourced

Live stats (win rates, counters, compatibility) come from the Rone
Arena API via direct tool-calls — see rone_arena_client.py. Narrative
strategic content (drafting philosophy, hero-specific reasoning) is
deliberately NOT pulled from the API's community guide feed; it's
supplied by you, since your own judgment on team comps and
counter-picking is more valuable RAG content than scraped guides.

Three ways to add content:

**1. Quick one-liner (no file editing needed):**
```bash
python -m src.rag.add_note "Lolita's shield counters burst-heavy dive comps" --hero Lolita
python -m src.rag.add_note "Ban high-mobility assassins first in gold-heavy metas"
```

**2. Write a file directly** into:
- `data/raw/general/` — hero-agnostic drafting philosophy
- `data/raw/heroes/<HeroName>/` — hero-specific notes (folder name = the tag, no special syntax needed)

**3. Drop in existing documents** (PDF/DOCX) into either folder above.

Two sample notes are included (`data/raw/general/draft_priority_philosophy.md`
and `data/raw/heroes/Lolita/counter_notes.md`) so you can test the
pipeline immediately.


## Data source disclaimer

This project uses the Rone Arena API, an unofficial, community-
maintained data source for Mobile Legends: Bang Bang. It is not
affiliated with or endorsed by Moonton. Data is used here purely for
learning/portfolio purposes — worth keeping in mind if this project
is later discussed in an interview or shown publicly.
