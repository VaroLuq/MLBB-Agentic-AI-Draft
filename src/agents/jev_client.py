"""Jev (OpenJev) adapter: turns a draft state into one batched evaluation.

Jev is a decision model, not a generative one — it returns typed primitives
with calibrated probabilities and emits no text. This module owns the
State Engineering half of that contract: raw domain rows from
`lane_filtered_aggregate` become an abstract state, one `Score` question is
raised per candidate, and all of them ride in a single request (Jev answers
every question in one parallel pass, so N candidates cost one round trip).

Nothing here decides anything. Ranking policy stays in the caller.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from dotenv import load_dotenv

load_dotenv()

JEV_URL = os.getenv("OPEN_JEV_URL", "https://api.openjev.sh/v1/systemone")
JEV_MODEL = os.getenv("OPEN_JEV_MODEL", "openjev")
DEFAULT_TIMEOUT = 30

# Ascending: index 0 is worst. The caller relies on that ordering, and Jev's
# rubric is documented as ordered, so do not shuffle these.
TIER_LEVELS = ["Fallback", "Marginal", "Solid", "Priority"]


def _gate_threshold(default: float = 0.50) -> float:
    """Minimum Noul probability for a note-admitted hero to survive the gate.

    0.50 was chosen from the three-call probe (misc/jev_noul_probe.py, measured
    2026-10-01): the adversarial Edith case scored 0.14 and the two cases that
    must pass scored 0.78-0.91, so 0.50 sits centred in a 0.64-wide gap with
    ~0.28 of headroom below the weakest true positive. Deliberately NOT set
    higher "to be safe" — run-to-run jitter is real (Lukas read 0.82 then 0.78),
    and a 0.70 cut would leave the note the user most wants honoured sitting
    0.08 from rejection. Being cautious here means NOT dropping heroes.
    """
    try:
        value = float(os.getenv("JEV_GATE_THRESHOLD", default))
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value <= 1.0 else default


NOUL_GATE_THRESHOLD = _gate_threshold()

# Wording carried over almost verbatim from the probe that validated it, which
# measured a 0.77 separation on the same note and hero with only the SIDE
# changed. The policy lives in the question and the facts live in the state;
# Jev's job is to notice whether the hero a note argues against sits in
# ally_picks or enemy_picks. Do not "simplify" that inference out of the
# wording — it is the entire mechanism.
NOUL_TEMPLATE = """\
'{hero}' is under consideration as a pick FOR THE PLAYER'S OWN TEAM in the \
'{lane}' lane. It entered the candidate list ONLY because the player's own \
strategy notes name it — see the 'notes' field of candidates['{hero}']. The \
live match data holds no counter or synergy record for it in this draft.

Decide whether those notes actually recommend '{hero}' as a pick for the \
PLAYER'S team in THIS draft.

Answer yes if a note advises picking this hero, or names it as a counter to a \
hero listed in 'draft.enemy_picks'.
Answer no if the notes name this hero only as a threat to the player's own \
side — for instance as a counter to a hero listed in 'draft.ally_picks' — or \
merely mention it without recommending it for a draft like this one. A hero a \
note frames as beating the player's OWN pick is one they would rather not \
face, not one they should pick.\
"""

# Calibration reference handed to Jev as part of the state so it knows what
# counts as a big number on our scales. Measured 2026-09-23 over 21 candidate
# rows from 6 scenarios spanning all five lanes; `typical` is the median of
# non-zero values, `strong` the p90, `max_seen` the observed maximum. These
# are descriptive, not thresholds — the rubric deliberately avoids hard cuts.
# Re-measure if the API window (DEFAULT_WINDOW_DAYS), the embedder, or the
# note corpus changes materially.
SCALES = {
    "counter_strength": {"typical": 0.026, "strong": 0.036, "max_seen": 0.049},
    "synergy_strength": {"typical": 0.016, "strong": 0.032, "max_seen": 0.051},
    # STALE as of the 2026-09-29 note-admission change and deliberately left
    # rather than guessed at. These figures were measured when a note could
    # only annotate a hero the live data had already surfaced. Two things moved
    # since: heroes can now enter the pool on a note alone, and
    # RAG_RELEVANCE_THRESHOLD doubles as the Noisy-OR zero point, so raising it
    # compresses every note_support toward 0 (a note at 0.41 against a 0.40
    # threshold rescales to 0.017). That is why the rubric keys the note path
    # off `source`, which is robust to the rescale, rather than off this
    # magnitude. Re-measure over a fresh scenario sweep before relying on it.
    "note_support": {"nonzero_rate": 0.14, "max_seen": 0.202},
}

RUBRIC_TEMPLATE = """\
Rate the draft viability of '{hero}' for the '{lane}' lane using its entry in \
'candidates' and the ranges in 'scales'. All metrics are sign-corrected so \
HIGHER IS BETTER.

Every candidate here has already passed a lane-eligibility filter and is not \
already picked or banned, so all of them are playable choices. Rate relative \
to this pre-filtered pool: "Fallback" means the weakest evidence among \
already-reasonable options, not a bad hero.

source - how this candidate entered the pool, and it changes how to read the \
other metrics.
  "live_stats" - the live API lists this hero as a counter or synergy for this \
draft. Judge it on counter_strength, synergy_strength and their coverage.
  "note" - the user's own strategy notes name this hero for this situation, \
and the live API does not list it as a relation to anyone drafted. \
counter_strength, synergy_strength and both coverages are therefore EXACTLY \
ZERO BY CONSTRUCTION, not because the hero is weak — there is simply no \
matchup record to read. Do not treat those zeros as negative evidence. Judge \
it on the note that admitted it, whose text is in 'notes'. These notes are \
hand-written by the player about their own ranked games, so a hero appearing \
here is a deliberate, situation-specific recommendation rather than a \
statistical artefact, and it is a strong signal in its own right — a "note" \
candidate is a real contender, not a filler entry.

counter_strength - how much this hero suppresses the enemy team's win rate, \
summed over the enemies it counters. Zero means the live data does not list it \
as a counter to anyone here; that is common and not disqualifying, since \
synergy is an equally valid path.
counter_coverage - the fraction of the enemy team it counters. Countering the \
only enemy is worth more than countering one of four.
synergy_strength - how much it raises allied win rate. It is rare for a hero to \
have this and counter_strength at once; either alone is a real advantage.
synergy_coverage - the fraction of the allied team it pairs with.
note_support - confidence that the user's own strategy notes back this pick in \
THIS draft, and 'notes' holds the text of those notes. Non-zero for roughly 1 \
candidate in 7, so it is strong corroboration when present. Zero is absence of \
evidence, not evidence against.

Priority - a strong matchup advantage on either axis, or an ordinary advantage \
corroborated by a second signal: note support, near-total coverage, or both \
counter and synergy present. A "note" candidate belongs here when the note \
names it as a deliberate pick for a draft like this one.
Solid - one clear advantage at or above the typical value for its axis, with no \
corroboration. A "note" candidate belongs here by default: the player wrote it \
down, which is evidence, but nothing in the live data independently confirms it.
Marginal - evidence present but below typical for its kind, with nothing \
corroborating it. A "note" candidate belongs here only when the note mentions \
it in passing rather than recommending it for this situation.
Fallback - the weakest evidence in this pool: barely above zero on its single \
axis, no coverage advantage, no note support. A "note" candidate does NOT \
belong here merely for having zero counter and synergy values, since those are \
zero for every "note" candidate by construction.\
"""


def _unsigned_zero(value: float) -> float:
    """Normalise -0.0 to 0.0.

    Negating a 0.0 counter impact yields -0.0, which serialises into the
    request as `-0.0`. Every note-admitted candidate has exactly that, and the
    rubric tells Jev those zeros are structural rather than negative evidence —
    handing it a minus sign undercuts the sentence.
    """
    return 0.0 if value == 0 else value


def _sanitise(name: str, taken: set[str]) -> str:
    """Hero name -> a key safe to use in a JSON object and read back.

    Real hero names include spaces, dots, hyphens and apostrophes ("Popol and
    Kupa", "X.Borg", "Chang'e"). Those have already caused one bug in this
    project when a model split "Popol and Kupa" into two heroes, and they are
    a poor bet as request keys, so questions are keyed by a slug and mapped
    back afterwards rather than trusting the name to survive a round trip.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "hero"
    candidate, n = slug, 2
    while candidate in taken:  # "Chang'e" and "Chang e" would collide
        candidate, n = f"{slug}_{n}", n + 1
    taken.add(candidate)
    return candidate


def build_payload(state: dict) -> tuple[dict, dict[str, str]]:
    """Build the scoring request body and the question-key -> hero-name map.

    Returns `({}, {})` when there is nothing to evaluate. That is a real case,
    not an error: a draft can produce an empty aggregate when no counter or
    synergy hero overlaps the lane roster, and sending zero questions would be
    a pointless request.

    The relevance gate is NOT part of this request — see build_gate_payload for
    why it needs a state of its own.
    """
    candidates = state.get("lane_filtered_aggregate") or []
    if not candidates:
        return {}, {}

    lane = state.get("role_needed") or "any"
    enemies = state.get("enemy_picks") or []
    allies = state.get("ally_picks") or []

    abstract, questions, key_to_hero, taken = {}, {}, {}, set()
    for row in candidates:
        hero = row["name"]
        countered = row.get("counters") or []
        synergised = row.get("synergises_with") or []
        abstract[hero] = {
            # Sign flipped so every metric reads higher-is-better. The raw
            # field is negative-is-better, which a model has already been
            # observed misreading as a "win rate increase".
            "counter_strength": _unsigned_zero(
                round(-(row.get("cumulative_counter_impact") or 0.0), 4)
            ),
            "counter_coverage": round(len(countered) / len(enemies), 3) if enemies else 0.0,
            "counters": countered,
            "synergy_strength": round(row.get("cumulative_synergy_impact") or 0.0, 4),
            "synergy_coverage": round(len(synergised) / len(allies), 3) if allies else 0.0,
            "synergises_with": synergised,
            "source": row.get("source", "live_stats"),
            "note_support": row.get("rag_score", 0.0),
            # Inlined rather than referenced from a shared block: at most a
            # handful of short notes exist, so the duplication is trivial and
            # it avoids depending on Jev resolving cross-references in state.
            "notes": [n.get("text", "") for n in (row.get("notes") or [])],
        }
        key = f"viability_{_sanitise(hero, taken)}"
        key_to_hero[key] = hero
        questions[key] = {
            "type": "score",
            "instructions": RUBRIC_TEMPLATE.format(hero=hero, lane=lane),
            "criteria": TIER_LEVELS,
        }

    payload = {
        "model": JEV_MODEL,
        "state": {
            "draft": {
                "lane": lane,
                "enemy_picks": enemies,
                "ally_picks": allies,
                "enemy_count": len(enemies),
                "ally_count": len(allies),
            },
            "scales": SCALES,
            "candidates": abstract,
        },
        "questions": questions,
    }
    return payload, key_to_hero


def build_gate_payload(state: dict) -> tuple[dict, dict[str, str]]:
    """Build the relevance-gate request: a MINIMAL state, deliberately separate.

    Returns `({}, {})` when nothing was note-admitted, which is the common case
    for a draft whose notes name no lane-eligible hero.

    WHY A SECOND REQUEST. The gate originally rode along with the scoring
    questions, since Jev answers every question in one parallel pass and that
    looked free. It was not: measured 2026-10-01 by ablation
    (`misc/jev_gate_ablation.py`, then `misc/jev_gate_state_ablation.py`), a
    note-admitted hero that scores 0.80 against a minimal state scores 0.35
    against the scoring state. The regression is entirely CONTEXT DILUTION, and
    the wording is innocent — holding the state fixed, probe vs shipped wording
    moved the answer +0.02/-0.07, while holding the wording fixed, flat vs
    shipped state moved it -0.32/-0.41. Removing the suspected "for a draft
    like this one" clause made it slightly WORSE, not better.
    Where the 0.44 gap lives, each measured by one edit to the real state:
      - other candidates present      0.49 of the gap
      - the hero's own zero metrics   0.33
      - the `scales` block alone      0.13 (measured on the flat state)
      - note addressability           0.05  <- NOT the problem. Duplicating the
        note into a top-level field recovered almost nothing, so Jev reads
        candidates['<hero>'].notes perfectly well.
    The giveaway that this is dilution rather than missing information: adding a
    top-level copy of the note to the already-trimmed state made the answer
    WORSE (0.57 -> 0.49). More content costs accuracy even when the content is
    relevant. So the only fix is to ask the question against less state, and
    Jev takes one state per request.
    DO NOT "optimise" this back into build_payload. It would restore one round
    trip and silently return the gate to a signal that sits below its own
    threshold.

    The gates still batch among THEMSELVES, so this is 2 requests per
    recommendation regardless of pool size, not N+1. Note the batching is not
    free either: Lukas reads ~0.80 alone and ~0.67 beside one other gated hero.
    That is the accepted ceiling — per-hero requests would be N+1.
    """
    candidates = state.get("lane_filtered_aggregate") or []
    gated = [row for row in candidates if row.get("source") == "note"]
    if not gated:
        return {}, {}

    lane = state.get("role_needed") or "any"
    questions, gate_to_hero, taken = {}, {}, set()
    notes_by_hero = {}
    for row in gated:
        hero = row["name"]
        # Only the note text, and only for heroes actually under review. No
        # scales, no numeric metrics, no live_stats candidates — each of those
        # was measured to cost the answer.
        notes_by_hero[hero] = {
            "notes": [n.get("text", "") for n in (row.get("notes") or [])]
        }
        key = f"gate_{_sanitise(hero, taken)}"
        gate_to_hero[key] = hero
        questions[key] = {
            "type": "noul",
            "instructions": NOUL_TEMPLATE.format(hero=hero, lane=lane),
        }

    payload = {
        "model": JEV_MODEL,
        "state": {
            # The draft is what makes the direction judgement possible at all —
            # the same note flips verdict depending on whether the hero it
            # argues against sits in ally_picks or enemy_picks.
            "draft": {
                "lane": lane,
                "ally_picks": state.get("ally_picks") or [],
                "enemy_picks": state.get("enemy_picks") or [],
            },
            "candidates": notes_by_hero,
        },
        "questions": questions,
    }
    return payload, gate_to_hero


def parse_answers(response: dict, key_to_hero: dict[str, str]) -> list[dict]:
    """Normalise Jev's answers into one row per hero.

    Written defensively because the live response shape is not yet confirmed:
    `score` may come back as an ordinal index or as the criterion label, and
    sorting the label as if it were a number would silently invert the
    ranking ("Unusable" > "Strong Pick" alphabetically). Both are handled and
    the raw answer is kept so a surprise is inspectable rather than lost.
    """
    answers = (response or {}).get("answers") or {}
    rows = []
    for key, hero in key_to_hero.items():
        answer = answers.get(key) or {}
        # Confirmed against a live response (2026-09-23): `score` is a FLOAT,
        # not an ordinal and not a label. It is the probability-weighted
        # expected tier index — sum(i * probabilities[i]) reproduces it to
        # within 0.01 on every candidate observed. That makes it a continuous
        # ranking signal, which is better than the tier for ordering: it
        # separates candidates that land in the same bucket.
        score = answer.get("score")
        score = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None

        # The response carries its own `legend` ({"0": "Fallback", ...}); use
        # it rather than assuming TIER_LEVELS survived the round trip.
        legend = answer.get("legend") or {str(i): t for i, t in enumerate(TIER_LEVELS)}
        probabilities = answer.get("probabilities") or answer.get("distribution") or {}

        # Tier is the modal outcome, not round(score): with probabilities
        # split 0.45/0.55 across two levels, the mode is what Jev actually
        # thinks, while the rounded mean can land on a level it never
        # favoured. Falls back to rounding when probabilities are absent.
        tier_index = None
        if probabilities:
            tier_index = int(max(probabilities, key=lambda i: probabilities[i]))
        elif score is not None:
            tier_index = int(round(score))
        tier = legend.get(str(tier_index)) if tier_index is not None else None

        rows.append({
            "hero": hero,
            "tier": tier,
            "tier_index": tier_index,
            "score": score,
            "confidence": answer.get("confidence"),
            "probabilities": probabilities or None,
            "raw": answer,
        })
    # Rank by the continuous score, most viable first; unanswered rows last.
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    return rows


def parse_gates(response: dict, gate_to_hero: dict[str, str]) -> dict[str, float]:
    """Hero -> relevance probability, for the note-admitted rows that were gated.

    A hero is ABSENT from the result when no usable probability came back, and
    callers must read that as "no verdict" rather than as a low one — see
    apply_gates, which fails open.

    Shape confirmed live 2026-10-01: the answer is
    `{"type": "noul", "noul": <float>}`. The field is named after the primitive,
    and unlike Score there is NO `confidence` key, so the probability is the
    only signal and is thresholded directly. Alternative spellings are still
    tried because the shape is pinned by exactly one probe.
    """
    answers = (response or {}).get("answers") or {}
    gates: dict[str, float] = {}
    for key, hero in gate_to_hero.items():
        answer = answers.get(key) or {}
        for field in ("noul", "probability", "value", "score"):
            value = answer.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                gates[hero] = float(value)
                break
    return gates


def apply_gates(
    rows: list[dict],
    gates: dict[str, float],
    threshold: float = NOUL_GATE_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """Split scored rows into (kept, rejected) on the relevance gate.

    FAILS OPEN, deliberately: a hero with no gate verdict is KEPT. Only rows
    that were gated AND came back under the threshold are dropped. A network
    blip, a renamed response field or an answer Jev declined to give would
    otherwise silently delete candidates the user explicitly wrote a note about,
    and silent deletion is the worst failure available here — the symptom is a
    hero quietly missing from a list, with nothing anywhere saying why.

    Rejected rows keep their tier and score alongside `gate`, so the
    diagnostics panel can show what the pick WOULD have been rated. That
    matters: the question this answers is "why isn't Edith in the list", and
    "she scored Solid but the gate read 0.14" is an answer, while a bare
    absence is not.
    """
    kept, rejected = [], []
    for row in rows:
        probability = gates.get(row["hero"])
        if probability is None:
            kept.append(row)
            continue
        row = {**row, "gate": round(probability, 3)}
        (rejected if probability < threshold else kept).append(row)
    return kept, rejected


def _magnitude(value: float, scale: dict) -> str:
    if value >= scale["strong"]:
        return "Strong"
    if value >= scale["typical"]:
        return "Solid"
    return "Slight"


def describe_candidate(row: dict) -> str:
    """One-sentence rationale built from the evidence, not written by a model.

    The previous pipeline had the LLM write this, and it was caught inventing
    relationships that were not in its context — claiming Aulus had "a good
    win rate against Aamon" when Aulus appeared in no counter data at all.
    Composing the sentence from the same numbers Jev scored means it can only
    state things that are true by construction.
    """
    if not row:
        return "No supporting live data was recorded for this pick."

    parts = []
    counter = -(row.get("cumulative_counter_impact") or 0.0)
    if counter > 0 and row.get("counters"):
        parts.append(
            f"{_magnitude(counter, SCALES['counter_strength'])} counter to "
            f"{_join(row['counters'])}, cutting their win rate by {counter:.1%}"
        )
    synergy = row.get("cumulative_synergy_impact") or 0.0
    if synergy > 0 and row.get("synergises_with"):
        parts.append(
            f"{_magnitude(synergy, SCALES['synergy_strength']).lower()} synergy with "
            f"{_join(row['synergises_with'])}, adding {synergy:.1%} win rate"
        )

    note_tags = [n.get("hero_name") for n in (row.get("notes") or []) if n.get("hero_name")]
    # Keyed off the notes actually attached, not off rag_score. A hero admitted
    # by a note scoring exactly at the threshold has rag_score 0.0 — the
    # Noisy-OR rescale maps the threshold itself to zero — and would otherwise
    # lose the one piece of evidence that put it in the pool.
    if note_tags:
        tags = _join(sorted(set(note_tags)))
        if row.get("source") == "note":
            # Nothing else can be in `parts` — a note-sourced row has no live
            # relation data at all — so this sentence carries the entire
            # justification and has to say what is and isn't behind the pick.
            return (f"Named in your {tags} notes for this draft. The live data "
                    f"lists no counter or synergy record for this pick.")
        parts.append(f"backed by your {tags} notes")

    if not parts:
        # A "note" row has no live relation data by construction, so the
        # live-data wording below would be an outright false statement.
        if row.get("source") == "note":
            return ("Named in your strategy notes for this draft. The live "
                    "data lists no counter or synergy record for this pick.")
        return "Appears in the live data for this draft, but with no measurable edge."
    return _sentence(parts)


def _join(items: list[str]) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _sentence(parts: list[str]) -> str:
    text = _join(parts)
    return text[0].upper() + text[1:] + "."


def summarise(recommendations: list[dict], lane: str | None) -> str:
    """Factual one-liner about the evaluation — no interpretation added."""
    if not recommendations:
        return "No eligible candidates were found for this draft."
    top = recommendations[0]
    n = len(recommendations)
    lane_text = f" for the {lane} lane" if lane and lane != "any" else ""
    confidence = top.get("confidence")
    confidence_text = f" at {confidence:.0%} confidence" if isinstance(confidence, (int, float)) else ""
    subject = "candidate was" if n == 1 else "candidates were"
    return (
        f"{n} eligible {subject} scored{lane_text}. "
        f"{top['hero']} ranks highest, rated {top['tier']}{confidence_text}."
    )


def _post(payload: dict, api_key: str, timeout: int) -> tuple[dict | None, str | None]:
    """POST one payload. Returns (body, error) — never raises.

    Errors are RETURNED rather than raised because both calls run in a thread
    pool below, and an exception escaping a worker loses which of the two
    requests it belonged to.
    """
    try:
        response = requests.post(
            JEV_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as e:
        return None, f"{type(e).__name__}: {e}"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text[:300]}"
    try:
        return response.json(), None
    except ValueError as e:
        return None, f"malformed JSON: {e}"


def evaluate_candidates(state: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Score the pool and gate the note-admitted rows.

    Returns {rows, rejected, raw, gate_raw, payload, gate_payload, error,
    gate_error}. `rejected` holds note-admitted candidates the relevance gate
    dropped; it is always present and empty when nothing was gated.

    TWO REQUESTS, RUN CONCURRENTLY. The gate needs its own minimal state (see
    build_gate_payload), so it cannot share the scoring request. But the two are
    independent — neither's input depends on the other's output — so they go out
    together and the added wall clock is max(a, b) rather than a + b. Same
    argument as the relation fan-out in gather_live_stats, and it is what makes
    the correct-but-separate gate affordable.
    """
    payload, key_to_hero = build_payload(state)
    if not payload:
        return {"rows": [], "rejected": [], "raw": None, "gate_raw": None,
                "payload": None, "gate_payload": None, "error": None, "gate_error": None}

    gate_payload, gate_to_hero = build_gate_payload(state)

    api_key = os.getenv("OPEN_JEV_KEY")
    if not api_key:
        return {"rows": [], "rejected": [], "raw": None, "gate_raw": None,
                "payload": payload, "gate_payload": gate_payload or None,
                "error": "OPEN_JEV_KEY is not set", "gate_error": None}

    if gate_payload:
        with ThreadPoolExecutor(max_workers=2) as pool:
            score_job = pool.submit(_post, payload, api_key, timeout)
            gate_job = pool.submit(_post, gate_payload, api_key, timeout)
            body, error = score_job.result()
            gate_body, gate_error = gate_job.result()
    else:
        body, error = _post(payload, api_key, timeout)
        gate_body, gate_error = None, None

    if error:
        return {"rows": [], "rejected": [], "raw": body, "gate_raw": gate_body,
                "payload": payload, "gate_payload": gate_payload or None,
                "error": error, "gate_error": gate_error}

    # A failed gate request leaves `gates` empty, and apply_gates fails open on
    # a missing verdict — so a gate outage degrades to the pre-gate behaviour
    # rather than dropping every note-admitted hero. `gate_error` is returned so
    # that degradation is visible instead of silent.
    gates = parse_gates(gate_body, gate_to_hero) if gate_body else {}
    kept, rejected = apply_gates(parse_answers(body, key_to_hero), gates)
    return {"rows": kept, "rejected": rejected, "raw": body, "gate_raw": gate_body,
            "payload": payload, "gate_payload": gate_payload or None,
            "error": None, "gate_error": gate_error}


if __name__ == "__main__":
    # Dry run: builds and prints the request without sending it, so the state
    # and question shape can be inspected without spending an API call.
    import json
    import sys

    from src.agents.draft_agent import gather_live_stats, retrieve_notes

    draft = retrieve_notes(gather_live_stats({
        "ally_picks": [], "enemy_picks": ["Lapu-Lapu"],
        "banned_heroes": [], "role_needed": "exp",
    }))
    body, mapping = build_payload(draft)
    if not body:
        print("No candidates for this draft — nothing to evaluate.")
        sys.exit(0)
    print(json.dumps(body, indent=2)[:4000])
    print("\nscore key -> hero:", mapping)

    gate_body, gate_map = build_gate_payload(draft)
    print(f"\n--- gate request (separate, minimal state; threshold {NOUL_GATE_THRESHOLD}) ---")
    print(json.dumps(gate_body, indent=2)[:2000] if gate_body else "nothing note-admitted")
    print("\ngate key -> hero:", gate_map)
