"""
Golden scenario set for evaluating the Draft Agent. Deliberately NOT
"one correct answer per scenario" — that's the wrong mental model for
this kind of eval. These are realistic draft states chosen to stress
different parts of the pipeline; what we measure against them (see
reliability_eval.py) is behavior (JSON validity, constraint
compliance), not a single expected recommendation.

Scenarios are picked to vary the thing most likely to break each
mechanism:
- "empty_no_lane": minimal context — does the agent even produce
  valid output with almost nothing to reason about?
- "early_jungle": the project's own long-standing worked example
  (draft_agent.py's __main__ block), kept here so this eval and that
  manual sanity check stay comparable.
- "mid_gold_lane": a mid-draft state with real exclusions AND a lane
  constraint active at once.
- "late_heavy_exclusion": lots of used heroes (8 across allies/
  enemies/bans) — stresses the used-hero filter hardest, and shrinks
  the pool of "safe" heroes the LLM could pick from.
- "narrow_lane_mid": mid lane tends to have a smaller eligible roster
  than jungle/gold/exp/roam — stresses the lane filter hardest.
- "note_heavy_lolita": ally/enemy picks chosen to overlap with the
  seeded Lolita and Dyrroth notes, so retrieved_notes should be
  non-trivial — useful for eyeballing whether reliability issues
  correlate with heavier prompt context.
"""

SCENARIOS = [
    {
        "name": "empty_no_lane",
        "ally_picks": [],
        "enemy_picks": [],
        "banned_heroes": [],
        "role_needed": "any",
    },
    {
        "name": "early_jungle",
        "ally_picks": ["Lolita"],
        "enemy_picks": ["Marcel", "Hirara"],
        "banned_heroes": [],
        "role_needed": "jungle",
    },
    {
        "name": "mid_gold_lane",
        "ally_picks": ["Lolita", "Angela"],
        "enemy_picks": ["Marcel", "Hirara"],
        "banned_heroes": ["Dyrroth", "Rafaela"],
        "role_needed": "gold",
    },
    {
        "name": "late_heavy_exclusion",
        "ally_picks": ["Lolita", "Angela", "Melissa", "Rafaela"],
        "enemy_picks": ["Marcel", "Hirara", "Dyrroth", "Alucard"],
        "banned_heroes": ["Chou", "Gusion", "Fanny", "Lancelot"],
        "role_needed": "roam",
    },
    {
        "name": "narrow_lane_mid",
        "ally_picks": ["Lolita"],
        "enemy_picks": ["Marcel"],
        "banned_heroes": [],
        "role_needed": "mid",
    },
    {
        "name": "note_heavy_lolita",
        "ally_picks": ["Lolita"],
        "enemy_picks": ["Hirara", "Dyrroth"],
        "banned_heroes": [],
        "role_needed": "any",
    },
]
