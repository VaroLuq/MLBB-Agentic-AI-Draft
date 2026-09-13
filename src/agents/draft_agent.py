import json
from typing import TypedDict
from pydantic import BaseModel, Field, ValidationError
from langgraph.graph import StateGraph, END

from src.agents.llm import get_llm
from src.api_client.rone_arena_client import (
    get_hero_rank_stats,
    get_hero_counters,
    get_hero_compatibility,
    get_heroes_by_lane,
)
from src.rag.vectorstore import get_vectorstore

MAX_REPAIR_ATTEMPTS = 2
VALID_LANES = {"exp", "mid", "roam", "jungle", "gold"}


# --- Structured output schema ---

class PickRecommendation(BaseModel):
    hero: str
    priority_score: float = Field(ge=0, le=1)
    rationale: str


class DraftRecommendation(BaseModel):
    recommendations: list[PickRecommendation]
    summary: str


# --- Graph state ---

class DraftState(TypedDict, total=False):
    ally_picks: list[str]
    enemy_picks: list[str]
    banned_heroes: list[str]
    role_needed: str
    live_stats_summary: str
    retrieved_notes: str
    valid_lane_heroes: list[str] | None
    raw_llm_output: str
    parsed_recommendation: dict | None
    parse_error: str | None
    repair_attempts: int


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

    for enemy in state.get("enemy_picks", []):
        try:
            counters = get_hero_counters(enemy, size=5)
            lines.append(f"\nStrong counters to enemy hero {enemy}:")
            for c in counters[:5]:
                lines.append(
                    f"- {c['name']} (win_rate={c['win_rate']:.3f}, "
                    f"increase_win_rate={c['increase_win_rate']:.3f})"
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
        except Exception as e:
            lines.append(f"\n(Could not fetch compatibility for {ally}: {e})")

    # Lane filtering: fetch the valid hero roster for the requested lane
    # (if it's a recognized lane) so the LLM sees only eligible options
    # and so we can enforce the constraint deterministically afterward,
    # rather than relying on the LLM to correctly apply lane knowledge
    # (which is what caused the Minsitthar-in-jungle recommendation).
    role_needed = (state.get("role_needed") or "").lower()
    if role_needed in VALID_LANES:
        try:
            lane_heroes = get_heroes_by_lane(role_needed, size=200)
            lane_names = [h["name"] for h in lane_heroes if h.get("name")]
            state["valid_lane_heroes"] = lane_names
            lines.append(f"\nHeroes eligible for the '{role_needed}' lane:")
            lines.append(", ".join(lane_names))
        except Exception as e:
            lines.append(f"\n(Could not fetch lane roster for "
                          f"'{role_needed}': {e} — lane will not be enforced)")
            state["valid_lane_heroes"] = None
    else:
        state["valid_lane_heroes"] = None

    state["live_stats_summary"] = "\n".join(lines)
    return state


def retrieve_notes(state: DraftState) -> DraftState:
  
    query_parts = [state.get("role_needed", "")]
    query_parts += state.get("enemy_picks", [])
    query_parts += state.get("ally_picks", [])
    query = "Draft advice for: " + ", ".join(p for p in query_parts if p)

    try:
        vectorstore = get_vectorstore()
        retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
        docs = retriever.invoke(query)
        notes_text = "\n\n".join(
            f"[{d.metadata.get('hero_name', 'general')}] {d.page_content}"
            for d in docs
        ) or "(no relevant notes found)"
    except Exception as e:
        notes_text = f"(Could not retrieve notes: {e})"

    state["retrieved_notes"] = notes_text
    return state


RECOMMENDATION_PROMPT = """You are a Mobile Legends: Bang Bang draft strategy assistant.

Draft state:
- Allies picked: {ally_picks}
- Enemies picked: {enemy_picks}
- Banned heroes: {banned_heroes}
- Role needed: {role_needed}

Live stats context:
{live_stats_summary}

Strategic notes (curated by the user — weigh these heavily, they reflect deliberate strategic judgment):
{retrieved_notes}

Respond with ONLY valid JSON matching this exact schema, no other text, no markdown code fences:
{{
  "recommendations": [
    {{"hero": "<hero name>", "priority_score": <float between 0 and 1>, "rationale": "<one sentence reason>"}}
  ],
  "summary": "<one or two sentence overall reasoning>"
}}

Provide 3 to 5 ranked recommendations, highest priority first. Do not recommend a hero that is already picked or banned. If a list of heroes eligible for the requested lane is given above, only recommend heroes from that list.
"""


def generate_recommendation(state: DraftState) -> DraftState:
    llm = get_llm()
    prompt = RECOMMENDATION_PROMPT.format(
        ally_picks=", ".join(state.get("ally_picks", [])) or "none yet",
        enemy_picks=", ".join(state.get("enemy_picks", [])) or "none yet",
        banned_heroes=", ".join(state.get("banned_heroes", [])) or "none",
        role_needed=state.get("role_needed") or "any",
        live_stats_summary=state.get("live_stats_summary", ""),
        retrieved_notes=state.get("retrieved_notes", ""),
    )
    response = llm.invoke(prompt)
    state["raw_llm_output"] = response.content
    return state


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def parse_output(state: DraftState) -> DraftState:
   
    raw = state.get("raw_llm_output", "")
    cleaned = _strip_code_fences(raw)

    try:
        parsed = DraftRecommendation.model_validate_json(cleaned)

        used_heroes = {
            h.lower() for h in (
                state.get("ally_picks", [])
                + state.get("enemy_picks", [])
                + state.get("banned_heroes", [])
            )
        }
        filtered_recs = [
            r for r in parsed.recommendations if r.hero.lower() not in used_heroes
        ]

        # Deterministic lane enforcement: if we successfully fetched a
        # lane roster, drop any recommendation for a hero not on it.
        # Only enforce when we actually have the data — an API failure
        # shouldn't silently zero out all recommendations.
        valid_lane_heroes = state.get("valid_lane_heroes")
        if valid_lane_heroes:
            valid_lower = {h.lower() for h in valid_lane_heroes}
            filtered_recs = [
                r for r in filtered_recs if r.hero.lower() in valid_lower
            ]

        state["parsed_recommendation"] = {
            "recommendations": [r.model_dump() for r in filtered_recs],
            "summary": parsed.summary,
        }
        state["parse_error"] = None

    except (ValidationError, json.JSONDecodeError) as e:
        state["parse_error"] = str(e)
        state["repair_attempts"] = state.get("repair_attempts", 0) + 1

    return state


REPAIR_PROMPT = """The following was supposed to be valid JSON but failed to parse.

Error: {error}

Original output:
{raw_output}

Return ONLY the corrected, valid JSON matching the required schema. No other text, no markdown fences.
"""


def repair_output(state: DraftState) -> DraftState:
    llm = get_llm()
    prompt = REPAIR_PROMPT.format(
        error=state.get("parse_error", "unknown error"),
        raw_output=state.get("raw_llm_output", ""),
    )
    response = llm.invoke(prompt)
    state["raw_llm_output"] = response.content
    return state


def should_retry(state: DraftState) -> str:
    if state.get("parsed_recommendation") is not None:
        return "end"
    if state.get("repair_attempts", 0) >= MAX_REPAIR_ATTEMPTS:
        return "end"  # give up; caller sees parse_error and raw_llm_output
    return "repair"


# --- Graph assembly ---

def build_draft_graph():
    builder = StateGraph(DraftState)

    builder.add_node("gather_live_stats", gather_live_stats)
    builder.add_node("retrieve_notes", retrieve_notes)
    builder.add_node("generate_recommendation", generate_recommendation)
    builder.add_node("parse_output", parse_output)
    builder.add_node("repair_output", repair_output)

    builder.set_entry_point("gather_live_stats")
    builder.add_edge("gather_live_stats", "retrieve_notes")
    builder.add_edge("retrieve_notes", "generate_recommendation")
    builder.add_edge("generate_recommendation", "parse_output")
    builder.add_conditional_edges(
        "parse_output", should_retry, {"repair": "repair_output", "end": END}
    )
    builder.add_edge("repair_output", "parse_output")

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
        "repair_attempts": 0,
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

    if result.get("parsed_recommendation"):
        rec = result["parsed_recommendation"]
        print("Summary:", rec["summary"])
        print("\nRecommendations:")
        for r in rec["recommendations"]:
            print(f"  {r['hero']} (score={r['priority_score']}): {r['rationale']}")
    else:
        print("Failed to get a valid recommendation after retries.")
        print("Last error:", result.get("parse_error"))
        print("Last raw output:", result.get("raw_llm_output"))
