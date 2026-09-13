import os
from dotenv import load_dotenv
from rone_arena import RoneArena
from rone_arena import RoneArenaError

load_dotenv()

_client = None


def get_client() -> RoneArena:
    global _client
    if _client is None:
        base_url = os.getenv("RONE_ARENA_BASE_URL", "https://arena.rone.dev/api")
        _client = RoneArena(base_url=base_url)
    return _client


def list_heroes(size: int = 50) -> list[dict]:
    
    client = get_client()
    try:
        response = client.heroes.heroes(size=size, index=1, order="desc")
    except RoneArenaError as e:
        raise RuntimeError(f"Failed to fetch hero list: {e}") from e

    records = response.get("data", {}).get("records", [])
    heroes = []
    for record in records:
        data = record.get("data", {})
        hero_info = data.get("hero", {}).get("data", {})
        relation = data.get("relation", {})
        heroes.append({
            "hero_id": data.get("hero_id"),
            "name": hero_info.get("name"),
            "strong_against": relation.get("strong", {}).get("target_hero_id", []),
            "weak_against": relation.get("weak", {}).get("target_hero_id", []),
            "assists": relation.get("assist", {}).get("target_hero_id", []),
        })
    return heroes


def get_hero_rank_stats(
    days: str = "7",
    rank: str = "all",
    sort_field: str = "win_rate",
    size: int = 20,
) -> list[dict]:
    
    client = get_client()
    try:
        response = client.heroes.heroes_rank(
            days=days, rank=rank, sort_field=sort_field,
            sort_order="desc", size=size, index=1,
        )
    except RoneArenaError as e:
        raise RuntimeError(f"Failed to fetch hero rank stats: {e}") from e

    records = response.get("data", {}).get("records", [])
    stats = []
    for record in records:
        data = record.get("data", {})
        hero_info = data.get("main_hero", {}).get("data", {})
        stats.append({
            "hero_id": data.get("main_heroid"),
            "name": hero_info.get("name"),
            "pick_rate": data.get("main_hero_appearance_rate"),
            "ban_rate": data.get("main_hero_ban_rate"),
            "win_rate": data.get("main_hero_win_rate"),
        })
    return stats


_hero_id_to_name_cache: dict[int, str] | None = None


def get_hero_id_to_name_map(force_refresh: bool = False) -> dict[int, str]:
    
    global _hero_id_to_name_cache
    if _hero_id_to_name_cache is None or force_refresh:
        # size=200 comfortably covers the full roster (~133 heroes as
        # of testing); adjust upward if the roster grows past that.
        heroes = list_heroes(size=200)
        _hero_id_to_name_cache = {h["hero_id"]: h["name"] for h in heroes}
    return _hero_id_to_name_cache


def _parse_hero_relation_response(records: list[dict], sub_hero_field: str) -> list[dict]:
    
    if not records:
        return []

    id_to_name = get_hero_id_to_name_map()
    record_data = records[0].get("data", {})

    related = []
    for sub in record_data.get(sub_hero_field, []):
        hero_id = sub.get("heroid")
        related.append({
            "hero_id": hero_id,
            "name": id_to_name.get(hero_id, f"Unknown hero ({hero_id})"),
            "win_rate": sub.get("hero_win_rate"),
            "appearance_rate": sub.get("hero_appearance_rate"),
            "increase_win_rate": sub.get("increase_win_rate"),
        })

    related.sort(key=lambda c: c["increase_win_rate"] or 0, reverse=True)
    return related


def get_hero_counters(
    hero_identifier: str, rank: str = "all", size: int = 10, days: int = 15,
) -> list[dict]:

    client = get_client()
    try:
        response = client.heroes.hero_counters(
            hero_identifier=hero_identifier, days=days, rank=rank, size=size, index=1,
        )
    except RoneArenaError as e:
        raise RuntimeError(
            f"Failed to fetch counters for '{hero_identifier}': {e}"
        ) from e

    records = response.get("data", {}).get("records", [])
    return _parse_hero_relation_response(records, "sub_hero_last")


def get_hero_compatibility(hero_identifier: str, rank: str = "all", size: int = 10) -> list[dict]:
   
    client = get_client()
    try:
        response = client.heroes.hero_compatibility(
            hero_identifier=hero_identifier, rank=rank, size=size, index=1,
        )
    except RoneArenaError as e:
        raise RuntimeError(
            f"Failed to fetch compatibility for '{hero_identifier}': {e}"
        ) from e

    records = response.get("data", {}).get("records", [])
    return _parse_hero_relation_response(records, "sub_hero")


def get_recommended_guides(size: int = 20) -> list[dict]:
    
    client = get_client()
    try:
        response = client.academy.recommended(size=size, index=1)
    except RoneArenaError as e:
        raise RuntimeError(f"Failed to fetch recommended guides: {e}") from e

    records = response.get("data", {}).get("records", [])
    return records


def get_heroes_by_lane(lane: str, size: int = 200) -> list[dict]:
   
    client = get_client()
    try:
        response = client.heroes.heroes_positions(lane=[lane], size=size, index=1)
    except AttributeError as e:
        raise RuntimeError(
            f"Guessed SDK method name 'heroes_positions' doesn't exist: {e}. "
            f"Run this file's __main__ block to see the real method list "
            f"under client.heroes and update this function accordingly."
        ) from e
    except RoneArenaError as e:
        raise RuntimeError(f"Failed to fetch heroes for lane '{lane}': {e}") from e

    records = response.get("data", {}).get("records", [])
    heroes = []
    for record in records:
        data = record.get("data", {})
        hero_info = data.get("hero", {}).get("data", {})
        heroes.append({
            "hero_id": data.get("hero_id"),
            "name": hero_info.get("name"),
        })
    return heroes


if __name__ == "__main__":
    print("Testing Rone Arena API connectivity...\n")

    print("1. Hero list (first 5):")
    heroes = list_heroes(size=5)
    for h in heroes:
        print(f"   {h['hero_id']}: {h['name']}")

    print("\n2. Top win-rate heroes (last 7 days, first 5):")
    stats = get_hero_rank_stats(days="7", size=5)
    for s in stats:
        print(f"   {s['name']}: win_rate={s['win_rate']}, "
              f"pick_rate={s['pick_rate']}, ban_rate={s['ban_rate']}")

    if heroes:
        sample_hero = heroes[0]["name"]

        print(f"\n3. Counters for {sample_hero!r} (parsed, top 5):")
        counters = get_hero_counters(sample_hero, size=10)
        for c in counters[:5]:
            print(f"   {c['name']}: win_rate={c['win_rate']}, "
                  f"increase_win_rate={c['increase_win_rate']}")

        print(f"\n4. Compatibility (best teammates) for {sample_hero!r} (parsed, top 5):")
        compat = get_hero_compatibility(sample_hero, size=10)
        for c in compat[:5]:
            print(f"   {c['name']}: win_rate={c['win_rate']}, "
                  f"increase_win_rate={c['increase_win_rate']}")

    print("\nDone. If all sections printed data, the API client is working.")

    print("\n5. Diagnostic — available methods under client.heroes:")
    client = get_client()
    methods = [m for m in dir(client.heroes) if not m.startswith("_")]
    print("  ", methods)

    print("\n6. Heroes valid for lane='jungle' (first 10) — "
          "may fail if the method name guess above is wrong, that's expected:")
    try:
        junglers = get_heroes_by_lane("jungle", size=10)
        for h in junglers:
            print(f"   {h['name']}")
    except Exception as e:
        print(f"   {e}")
