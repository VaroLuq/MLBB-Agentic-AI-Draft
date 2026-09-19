---
version: 1
slug: "src-web-static-index-html"
primary_target: "src/web/static/index.html"
related_targets: ["src/web/static/js/main.js","src/web/static/app.css"]
---

# Surface brief: Draft Copilot web app (Operate)

## Scope and mode
Whole app, replacing the Streamlit dashboard: Draft view (the primary task), Notebook view (strategy-note CRUD), and a Live Intel rail (current meta + Meta-Watcher control). Visitor mode: Operate. Flask API backend wrapping unchanged agent/RAG/Meta-Watcher logic; static HTML + Tailwind v4 (built by the standalone CLI, no runtime CDN) + vanilla ES modules.

## Audience, job, task
An MLBB ranked player (today the developer; aspirationally other players) drafting live or planning a scenario. Task: state the draft (allies, enemies, bans, lane), request a ranked recommendation, trust it enough to act, inspect the evidence behind it. Second job: curate strategy notes and keep the knowledge base current.

## Proof and content
Real backend, real notes, real live stats, real eval-verified grounding. No hero art exists: placeholder initial badges only, never scraped or generated game likenesses. No invented claims.

## Constraints
Local-first, $0. Code-led build (no usable image generation). Fixed rem type scale, 150-250ms motion, native form controls, `<dialog>` for the two user-pinned popups (new note, edit note). Delete keeps its two-step confirm.

## Memorable moment
Locking in a recommendation: the request runs as a live countdown, then the lead pick's badge locks in with a single flip and gold edge.

## Unresolved
Real hero portraits (licensing). Any optional decorative raster via Gemini (cost unconfirmed).

## Direction contract

THESIS: The draft board is MLBB's own pick/ban screen rebuilt as a working tool: two teams face each other across a hero pool, and the recommendation is the next pick locking in. It refuses the stacked-form dashboard, three selects above a button.

OWN-WORLD: Blue-black stage #101820 with a faint hex lattice; chamfered panels edged by a 1px steel line; gold #E8C547 reserved for the primary action, selection and the lead pick; ally slate-blue and enemy red tint whole side panels; banned heroes carry a diagonal hazard band. Barlow Condensed for headings and wordmark, Barlow for labels, controls and data. Placeholder portraits are chamfered initial badges on a curated set of muted hues. Recognizable with all content removed by the chamfers, the gold, and the ally/enemy split.

STORY: A ranked player at a desk, room lights low, Discord open, sees the draft laid out like the screen they already know, fills in what has been picked and banned, sets the lane, and locks in a request. Within seconds they know which hero to take and why, and can open the evidence behind it.

FIRST VIEWPORT: Desktop 1440x900. Top bar: wordmark left, Draft and Notebook tabs beside it, model and knowledge-base status chips right. Stage below: ally panel left and enemy panel right as tall five-slot draft cards that stretch to the height of the centre column, which holds the ban strip, the ally/enemy/ban assign control and the searchable hero pool. Under the stage a lock-in bar: the lane selector left (it is a parameter of the request, so it sits with the action), Clear draft and the gold "Get recommendation" button right. Results and the Live Intel rail sit below the fold, results 2/3 and intel 1/3. Revised after the first inspection round: lane selector moved from the pool to the lock bar; the draft summary chips were dropped because each panel header already shows its count.

FORM: In-game pick/ban screen. Position 1 on my ordered list (the pick card); seed key c7ab6761.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
