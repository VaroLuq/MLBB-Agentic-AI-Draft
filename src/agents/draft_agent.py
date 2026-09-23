from typing import TypedDict
from langgraph.graph import StateGraph, END

from src.agents import jev_client
from src.api_client.rone_arena_client import (
    get_hero_rank_stats,
    get_hero_counters,
    get_hero_compatibility,
    get_heroes_by_lane,
)
from src.rag.vectorstore import get_vectorstore
from src.rag.scoring import aggregate_rag_scores, mentions_hero

VALID_LANES = {"exp", "mid", "roam", "jungle", "gold"}


# --- Graph state ---

class DraftState(TypedDict, total=False):
    ally_picks: list[str]
    enemy_picks: list[str]
    banned_heroes: list[str]
    role_needed: str
    live_stats_summary: str
    retrieved_notes: str
    valid_lane_heroes: list[str] | None
    lane_roster_text: str | None
    lane_filtered_stats_text: str | None
    lane_filtered_aggregate: list[dict]
    parsed_recommendation: dict | None
    jev_raw: dict | None
    jev_error: str | None


# --- Nodes ---

def gather_live_stats(state: DraftState) -> DraftState:

    lines = []

    try:
        top_heroes = get_hero_rank_stats(days="7", size=10)
        lines.append("Current top win-rate heroes (last 7 days):")
        for h in top_heroes:
            lines.append(
                f"- {h['name']}: win_rate={h['win_rate']:.3f}, "
                f"pick_rate={h['pick_rate']:.3f}, ban_rate={h['ban_rate']:.3f}"
            )
    except Exception as e:
        lines.append(f"(Could not fetch tier list: {e})")

    # Lane roster is fetched BEFORE the counters/compatibility calls
    # below (moved up from its old position at the end of this
    # function) specifically so it's available to cross-reference
    # against them in code. Eval evidence (a manually-traced Aamon/exp
    # scenario) showed the LLM ignoring real, relevant counter data
    # (Gloo, Silvanna — both valid exp-lane counters to Aamon) in favor
    # of its own general knowledge, because nothing told it those two
    # separately-formatted lists (counters vs. eligible roster)
    # overlapped — cross-referencing two lists itself is a nontrivial
    # reasoning step for a 3B model with no prompted incentive to do
    # it. Doing that cross-reference here, deterministically, and
    # handing it a pre-filtered answer follows the same
    # don't-trust-the-small-model-to-self-police-it philosophy as the
    # existing used-hero/lane filters, just applied a step earlier.
    role_needed = (state.get("role_needed") or "").lower()
    valid_lane_heroes = None
    if role_needed in VALID_LANES:
        try:
            lane_heroes = get_heroes_by_lane(role_needed, size=200)
            valid_lane_heroes = [h["name"] for h in lane_heroes if h.get("name")]
            state["valid_lane_heroes"] = valid_lane_heroes
            # Deliberately NOT appended into `lines`/live_stats_summary:
            # eval evidence (src/eval/reliability_eval.py, 2026-09-13
            # run) showed the model reliably ignoring/misreading this
            # list when it was buried at the end of a long stats block
            # alongside tier lists, counters, and compatibility data.
            # generate_recommendation() instead gives it its own
            # prominent section, right next to the instruction that
            # references it, with each name quoted so multi-word names
            # (e.g. "Popol and Kupa", which the model was observed
            # splitting into two fictional heroes, "Popol" and "Kupa")
            # read as one atomic token rather than ambiguous
            # comma/"and"-separated text.
            state["lane_roster_text"] = ", ".join(f'"{n}"' for n in valid_lane_heroes)
        except Exception as e:
            lines.append(f"\n(Could not fetch lane roster for "
                          f"'{role_needed}': {e} — lane will not be enforced)")
            state["valid_lane_heroes"] = None
            state["lane_roster_text"] = None
    else:
        state["valid_lane_heroes"] = None
        state["lane_roster_text"] = None

    valid_lane_lower = {h.lower() for h in valid_lane_heroes} if valid_lane_heroes else None
    lane_filtered_sections = []

    # Per-hero running totals across every relation fetched below. The
    # lane-filtered text section answers "who counters this one enemy?"
    # once per enemy; this answers "how good is this hero against the
    # enemy team as a whole?" — a hero countering two enemies (or
    # synergising with two allies) only shows up as two unrelated
    # bullets otherwise, and nothing adds them up. Keyed by lowercased
    # name, matching how the lane filter compares names.
    aggregate: dict[str, dict] = {}
    # Heroes already picked or banned are excluded from the aggregate, not
    # just from the final recommendations. parse_output filters used heroes
    # out of the LLM's answer after the fact, which is enough while an LLM
    # is choosing, but the aggregate is a candidate list in its own right —
    # anything consuming it directly (the Jev evaluation) would otherwise be
    # handed banned heroes to score. Verified before this guard existed:
    # banning Esmeralda still left her as the sole candidate against
    # Lapu-Lapu. Deliberately NOT applied to lane_filtered_stats_text below,
    # which feeds the prompt — changing what the model sees is a behaviour
    # change that needs its own eval run.
    used_heroes = {
        h.lower()
        for h in (
            state.get("ally_picks", [])
            + state.get("enemy_picks", [])
            + state.get("banned_heroes", [])
        )
    }
    # win_rate is whichever source reaches the hero first, which is safe
    # only because both endpoints now run on the same trailing window
    # (rone_arena_client.DEFAULT_WINDOW_DAYS). They used to disagree —
    # counters on 15 days, compatibility on 1 — and the same hero could
    # carry a different base win rate depending on fetch order.

    def _accumulate(record: dict, opponent: str, is_counter: bool) -> None:
        name = record.get("name")
        if not name:
            return
        if valid_lane_lower is not None and name.lower() not in valid_lane_lower:
            return
        if name.lower() in used_heroes:
            return
        entry = aggregate.setdefault(name.lower(), {
            "name": name,
            "win_rate": None,
            "cumulative_counter_impact": 0.0,
            "cumulative_synergy_impact": 0.0,
            "counters": [],
            "synergises_with": [],
        })
        impact = record.get("increase_win_rate") or 0.0
        if is_counter:
            entry["cumulative_counter_impact"] += impact
            entry["counters"].append(opponent)
        else:
            entry["cumulative_synergy_impact"] += impact
            entry["synergises_with"].append(opponent)

        if entry["win_rate"] is None and record.get("win_rate") is not None:
            entry["win_rate"] = record["win_rate"]

    for enemy in state.get("enemy_picks", []):
        try:
            counters = get_hero_counters(enemy, size=5)
            lines.append(f"\nStrong counters to enemy hero {enemy}:")
            for c in counters[:5]:
                lines.append(
                    f"- {c['name']} (win_rate={c['win_rate']:.3f}, "
                    f"increase_win_rate={c['increase_win_rate']:.3f})"
                )

            for c in counters:
                _accumulate(c, enemy, is_counter=True)

            if valid_lane_lower is not None:
                matches = [c["name"] for c in counters if c["name"].lower() in valid_lane_lower]
                if matches:
                    names = ", ".join(f'"{n}"' for n in matches)
                    lane_filtered_sections.append(f"- Counters to {enemy}: {names}")
                else:
                    lane_filtered_sections.append(
                        f"- Counters to {enemy}: none of the live counter data "
                        f"overlaps with the '{role_needed}' lane roster"
                    )
        except Exception as e:
            lines.append(f"\n(Could not fetch counters for {enemy}: {e})")

    for ally in state.get("ally_picks", []):
        try:
            compat = get_hero_compatibility(ally, size=5)
            lines.append(f"\nGood teammates for ally hero {ally}:")
            for c in compat[:5]:
                lines.append(
                    f"- {c['name']} (win_rate={c['win_rate']:.3f}, "
                    f"increase_win_rate={c['increase_win_rate']:.3f})"
                )

            for c in compat:
                _accumulate(c, ally, is_counter=False)

            if valid_lane_lower is not None:
                matches = [c["name"] for c in compat if c["name"].lower() in valid_lane_lower]
                if matches:
                    names = ", ".join(f'"{n}"' for n in matches)
                    lane_filtered_sections.append(f"- Synergy with {ally}: {names}")
                else:
                    lane_filtered_sections.append(
                        f"- Synergy with {ally}: none of the live compatibility "
                        f"data overlaps with the '{role_needed}' lane roster"
                    )
        except Exception as e:
            lines.append(f"\n(Could not fetch compatibility for {ally}: {e})")

    state["lane_filtered_stats_text"] = (
        "\n".join(lane_filtered_sections) if lane_filtered_sections else None
    )

    # Ordered strongest-first. Counter impact is negative-is-better and
    # synergy positive-is-better, so the sort key flips the counter sign
    # to put a hero who does both at the top. This is presentation order
    # only — no composite score is stored, since how the two axes should
    # be weighted against each other isn't established.
    state["lane_filtered_aggregate"] = sorted(
        aggregate.values(),
        key=lambda h: h["cumulative_synergy_impact"] - h["cumulative_counter_impact"],
        reverse=True,
    )

    state["live_stats_summary"] = "\n".join(lines)
    return state


def retrieve_notes(state: DraftState) -> DraftState:
  
    query_parts = [state.get("role_needed", "")]
    query_parts += state.get("enemy_picks", [])
    query_parts += state.get("ally_picks", [])
    query = "Draft advice for: " + ", ".join(p for p in query_parts if p)

    # similarity_search_with_relevance_scores rather than the plain
    # retriever: same documents in the same order, but it also hands back
    # the 0-1 relevance the retriever discards, which _attach_rag_scores
    # needs. `notes_text` is byte-identical to what the retriever produced,
    # so the prompt the model sees is unchanged.
    scored = []
    try:
        vectorstore = get_vectorstore()
        scored = vectorstore.similarity_search_with_relevance_scores(query, k=4)
        notes_text = "\n\n".join(
            f"[{d.metadata.get('hero_name', 'general')}] {d.page_content}"
            for d, _ in scored
        ) or "(no relevant notes found)"
    except Exception as e:
        notes_text = f"(Could not retrieve notes: {e})"

    state["retrieved_notes"] = notes_text
    _attach_rag_scores(state, scored)
    return state


def _attach_rag_scores(state: DraftState, scored: list) -> None:
    """Add `rag_score` + `notes` to each row of `lane_filtered_aggregate`.

    Runs here rather than in gather_live_stats purely because of node order:
    the aggregate is built before retrieval happens, so this is the first
    point where both exist. Costs no extra query — it reuses the scores from
    the single scenario retrieval above.

    Scoring against the scenario query (not a per-hero one) is what makes
    rag_score draft-conditional for free: the query text contains the lane
    and the picks, so a note only scores well when it is relevant to THIS
    draft. Measured on the Esmeralda/Lapu-Lapu note: 0.409 when Lapu-Lapu is
    an enemy, 0.173 when he is not.
    """
    aggregate = state.get("lane_filtered_aggregate") or []
    if not aggregate:
        return

    for row in aggregate:
        hero = row.get("name", "")
        # A note counts for a hero if it is tagged with them or names them;
        # the second half is the valuable case (see mentions_hero).
        matched = [
            (str(doc.metadata.get("hero_name", "general")), score, doc.page_content)
            for doc, score in scored
            if str(doc.metadata.get("hero_name", "")).lower() == hero.lower()
            or mentions_hero(doc.page_content, hero)
        ]
        row["rag_score"] = aggregate_rag_scores([s for _, s, _ in matched])
        # Every matched note is kept, including ones that fell below the
        # threshold, so a 0.0 is explainable rather than mysterious. `text`
        # is carried because the Jev state includes the note prose itself —
        # rag_score says how relevant a note is, the text says what it
        # actually advises, and only the latter survives dropping the LLM.
        row["notes"] = [
            {"hero_name": tag, "relevance": round(s, 4), "text": text}
            for tag, s, text in matched
        ]

    state["lane_filtered_aggregate"] = aggregate


def evaluate_candidates(state: DraftState) -> DraftState:
    """Score every candidate with Jev, in one batched request.

    Replaces the generate -> parse -> repair loop that ran against a local
    3B model. That loop existed to coerce a generative model into emitting
    valid JSON and to catch it recommending picked, banned or wrong-lane
    heroes. None of it applies here: Jev returns typed output by
    construction, and the candidate list it is handed was already filtered
    for lane eligibility and used heroes upstream in gather_live_stats.
    """
    result = jev_client.evaluate_candidates(state)
    state["jev_raw"] = result.get("raw")
    state["jev_error"] = result.get("error")

    rows = result.get("rows") or []
    if not rows:
        state["parsed_recommendation"] = None
        return state

    # jev_client already sorted by the continuous score, best first.
    recommendations = [
        {
            "hero": row["hero"],
            "tier": row["tier"],
            "tier_index": row["tier_index"],
            "score": row["score"],
            "confidence": row["confidence"],
            "probabilities": row["probabilities"],
            "rationale": jev_client.describe_candidate(
                _aggregate_row(state, row["hero"])
            ),
        }
        for row in rows
    ]
    state["parsed_recommendation"] = {
        "recommendations": recommendations,
        "summary": jev_client.summarise(recommendations, state.get("role_needed")),
    }
    return state


def _aggregate_row(state: DraftState, hero: str) -> dict:
    for row in state.get("lane_filtered_aggregate") or []:
        if row.get("name") == hero:
            return row
    return {}


# --- Graph assembly ---

def build_draft_graph():
    """gather_live_stats -> retrieve_notes -> evaluate_candidates -> END.

    Linear now that Jev replaced the local LLM. The conditional edge and the
    parse_output <-> repair_output cycle are gone: they existed only to
    recover from malformed JSON, and a decision model that returns typed
    primitives cannot emit malformed JSON in the first place.
    """
    builder = StateGraph(DraftState)

    builder.add_node("gather_live_stats", gather_live_stats)
    builder.add_node("retrieve_notes", retrieve_notes)
    builder.add_node("evaluate_candidates", evaluate_candidates)

    builder.set_entry_point("gather_live_stats")
    builder.add_edge("gather_live_stats", "retrieve_notes")
    builder.add_edge("retrieve_notes", "evaluate_candidates")
    builder.add_edge("evaluate_candidates", END)

    return builder.compile()


def get_draft_recommendation(
    ally_picks: list[str] | None = None,
    enemy_picks: list[str] | None = None,
    banned_heroes: list[str] | None = None,
    role_needed: str = "any",
) -> DraftState:
    graph = build_draft_graph()
    initial_state: DraftState = {
        "ally_picks": ally_picks or [],
        "enemy_picks": enemy_picks or [],
        "banned_heroes": banned_heroes or [],
        "role_needed": role_needed,
    }
    return graph.invoke(initial_state)


if __name__ == "__main__":
    print("Running Draft Agent on a sample scenario...\n")
    print("Scenario: ally has picked Lolita, enemies have picked "
          "Marcel and Hirara, role needed: jungle.\n")

    result = get_draft_recommendation(
        ally_picks=["Lolita"],
        enemy_picks=["Marcel", "Hirara"],
        role_needed="jungle",
    )

    if result.get("jev_error"):
        print("Jev evaluation failed:", result["jev_error"])
    elif result.get("parsed_recommendation"):
        rec = result["parsed_recommendation"]
        print("Summary:", rec["summary"])
        print("\nRecommendations:")
        for r in rec["recommendations"]:
            print(f"  {r['hero']} [{r['tier']}] score={r['score']} "
                  f"confidence={r['confidence']}\n      {r['rationale']}")
    else:
        print("No candidates for this draft — nothing to evaluate.")
