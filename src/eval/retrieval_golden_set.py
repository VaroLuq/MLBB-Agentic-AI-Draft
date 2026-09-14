"""
Hand-labeled golden set for evaluating RAG retrieval quality,
independent of LLM generation. Each entry pairs a realistic query
(phrased the same way retrieve_notes() in draft_agent.py builds its
own queries — "Draft advice for: <role>, <enemy picks>, <ally
picks>") with which note(s) SHOULD show up in the results.

Labeled directly from the actual contents of data/raw/ at the time of
writing (see retrieval_eval.py's warning if the note set has changed
since — a stale golden set silently measures the wrong thing). One
entry per real seeded note, so a clean run means "every note is
actually reachable by a realistic query," not just "retrieval returns
something."

expected_hero: matches the `hero_name` metadata note_loader.py tags
    documents with ("general" for hero-agnostic notes).
expected_keyword: a distinctive substring from the note's actual text
    — used as a second, content-level check independent of the
    hero_name tag, since a hit on hero_name alone wouldn't catch e.g.
    retrieving the WRONG Esmeralda note when two exist for one hero.
"""

GOLDEN_SET = [
    {
        "name": "lolita_vs_burst_dive",
        "query": "Draft advice for: jungle, Marcel, Hirara, Lolita",
        "expected_hero": "Lolita",
        "expected_keyword": "burst-heavy dive",
    },
    {
        "name": "dyrroth_exp_matchup",
        "query": "Draft advice for: exp, Yu Zhong, Dyrroth",
        "expected_hero": "Dyrroth",
        "expected_keyword": "Mythic adjustment",
    },
    {
        "name": "angela_meta_healer",
        "query": "Draft advice for: roam, Angela",
        "expected_hero": "Angela",
        "expected_keyword": "meta pick",
    },
    {
        "name": "countering_lapu_lapu",
        "query": "Draft advice for: exp, Lapu-Lapu",
        "expected_hero": "Lapu-Lapu",
        "expected_keyword": "Esmeralda",
    },
    {
        "name": "countering_esmeralda_exp",
        "query": "Draft advice for: exp, Esmeralda",
        "expected_hero": "Esmeralda",
        # Either Esmeralda note is an acceptable hit for this query;
        # checked as a list rather than a single keyword.
        "expected_keyword": ["Dyyroth", "Edith"],
    },
    {
        "name": "split_push_wave_clear",
        "query": "Draft advice for: any, split push wave clear priority",
        "expected_hero": "general",
        "expected_keyword": "split-push",
    },
    {
        "name": "ban_priority_gold_meta",
        "query": "Draft advice for: gold, ban priority high mobility assassins",
        "expected_hero": "general",
        "expected_keyword": "Ban priority",
    },
]
