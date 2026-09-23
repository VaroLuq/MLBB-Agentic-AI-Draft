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

import requests
from dotenv import load_dotenv

load_dotenv()

JEV_URL = os.getenv("OPEN_JEV_URL", "https://api.openjev.sh/v1/systemone")
JEV_MODEL = os.getenv("OPEN_JEV_MODEL", "openjev")
DEFAULT_TIMEOUT = 30

# Ascending: index 0 is worst. The caller relies on that ordering, and Jev's
# rubric is documented as ordered, so do not shuffle these.
TIER_LEVELS = ["Fallback", "Marginal", "Solid", "Priority"]

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
    "note_support": {"nonzero_rate": 0.14, "max_seen": 0.202},
}

RUBRIC_TEMPLATE = """\
Rate the draft viability of '{hero}' for the '{lane}' lane using its entry in \
'candidates' and the ranges in 'scales'. All metrics are sign-corrected so \
HIGHER IS BETTER.

Every candidate here has already passed a lane-eligibility filter, is not \
already picked or banned, and already appears in the live counter or synergy \
data for this draft, so all of them have some evidence. Rate relative to this \
pre-filtered pool: "Fallback" means the weakest evidence among \
already-reasonable options, not a bad hero.

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
counter and synergy present.
Solid - one clear advantage at or above the typical value for its axis, with no \
corroboration.
Marginal - evidence present but below typical for its kind, with nothing \
corroborating it.
Fallback - the weakest evidence in this pool: barely above zero on its single \
axis, no coverage advantage, no note support.\
"""


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
    """Build the request body and the question-key -> hero-name map.

    Returns `({}, {})` when there is nothing to evaluate. That is a real case,
    not an error: a draft can produce an empty aggregate when no counter or
    synergy hero overlaps the lane roster, and sending zero questions would be
    a pointless request.
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
            "counter_strength": round(-(row.get("cumulative_counter_impact") or 0.0), 4),
            "counter_coverage": round(len(countered) / len(enemies), 3) if enemies else 0.0,
            "counters": countered,
            "synergy_strength": round(row.get("cumulative_synergy_impact") or 0.0, 4),
            "synergy_coverage": round(len(synergised) / len(allies), 3) if allies else 0.0,
            "synergises_with": synergised,
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
    if row.get("rag_score", 0) > 0 and note_tags:
        parts.append(f"backed by your {_join(note_tags)} notes")

    if not parts:
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


def evaluate_candidates(state: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST one batched evaluation. Returns {rows, raw, payload, error}."""
    payload, key_to_hero = build_payload(state)
    if not payload:
        return {"rows": [], "raw": None, "payload": None, "error": None}

    api_key = os.getenv("OPEN_JEV_KEY")
    if not api_key:
        return {"rows": [], "raw": None, "payload": payload,
                "error": "OPEN_JEV_KEY is not set"}

    try:
        response = requests.post(
            JEV_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as e:
        return {"rows": [], "raw": None, "payload": payload,
                "error": f"{type(e).__name__}: {e}"}

    if response.status_code != 200:
        return {"rows": [], "raw": response.text, "payload": payload,
                "error": f"HTTP {response.status_code}: {response.text[:300]}"}

    body = response.json()
    return {"rows": parse_answers(body, key_to_hero), "raw": body,
            "payload": payload, "error": None}


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
    print("\nquestion key -> hero:", mapping)
