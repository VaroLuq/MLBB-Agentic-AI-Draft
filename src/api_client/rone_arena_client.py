import os
import threading
import time
from typing import Callable

from dotenv import load_dotenv
from rone_arena import RoneArena
from rone_arena import RoneArenaError

load_dotenv()

# Every stats endpoint reports win rates over a trailing window, and the
# value only means something alongside the window that produced it. The
# three endpoints defaulted to three different ones — heroes_rank to 7
# days, hero_counters to 15, and hero_compatibility to 1 (verified: its
# no-days response matches the rank endpoint at days=1 exactly, on
# Benedetta, Gloo, Thamuz and Atlas). That made the synergy numbers a
# single day of matches sitting next to 15 days of counter data, and it
# made any arithmetic across the two measure window drift as much as
# matchup effect — Benedetta's own drift between windows (0.5324 -> 0.5273)
# is larger than most of the counter deltas involved.
DEFAULT_WINDOW_DAYS = 7

# --- Response cache ---------------------------------------------------
#
# A draft recommendation costs 2 + len(enemies) + len(allies) requests, and
# measured HTTP time dominates the whole node (~19-21s of a ~22s
# gather_live_stats in one run). Nothing was cached, so an identical request
# refetched all 8. The real win is not the repeated-identical case but a live
# draft: picks accumulate, so consecutive requests overlap almost entirely.
# Caching per (endpoint, args) rather than per request is what makes that
# overlap count — a whole-request key would essentially never hit.
#
# The TTL can afford to be generous: every endpoint now reports over a 7-day
# trailing window (DEFAULT_WINDOW_DAYS), and the Meta-Watcher treats a 2-point
# move between daily snapshots as notable, so the underlying numbers move far
# more slowly than any drafting session.
CACHE_TTL_SECONDS = float(os.getenv("RONE_CACHE_TTL_SECONDS", "3600"))

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _cached_call(key: tuple, ttl: float, loader: Callable[[], object]) -> object:
    """Return a cached response, or fetch and store one.

    The lock is deliberately NOT held across `loader()`: an HTTP call can take
    seconds, and blocking every other reader for that long would be worse than
    the only thing releasing it costs, which is that two concurrent misses on
    the same key may both fetch. That wastes a request; it cannot corrupt the
    cache or return anything stale.
    """
    if ttl <= 0:
        return loader()

    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]

    value = loader()
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
    return value


def _ttl(use_cache: bool) -> float:
    return CACHE_TTL_SECONDS if use_cache else 0.0


def clear_cache() -> None:
    """Drop every cached response. Call after anything that should see fresh data."""
    with _cache_lock:
        _cache.clear()


def cache_info() -> dict:
    """Entry count and keys, for diagnostics and tests."""
    with _cache_lock:
        return {"entries": len(_cache), "keys": sorted(str(k) for k in _cache)}


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
    use_cache: bool = True,
) -> list[dict]:
    # `use_cache=False` matters here specifically: meta_watcher.take_snapshot()
    # calls this, and its whole job is recording what the stats are RIGHT NOW.
    # A cached snapshot would silently bake in hour-old numbers, and because
    # drift is diffed across days that corruption would never be visible.
    def _fetch() -> list[dict]:
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

    cached = _cached_call(("hero_rank_stats", days, rank, sort_field, size),
                          _ttl(use_cache), _fetch)
    # Hand back copies: callers get plain dicts they may reasonably mutate,
    # and a mutation reaching the cached list would poison every later read.
    return [dict(row) for row in cached]


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
    hero_identifier: str, rank: str = "all", size: int = 10,
    days: int = DEFAULT_WINDOW_DAYS, use_cache: bool = True,
) -> list[dict]:
    # Keyed per hero, which is where the saving is: during a live draft the
    # enemy list grows one pick at a time, so every request after the first
    # re-asks about heroes already fetched.
    def _fetch() -> list[dict]:
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

    cached = _cached_call(("hero_counters", str(hero_identifier).lower(), rank, size, days),
                          _ttl(use_cache), _fetch)
    return [dict(row) for row in cached]


def get_hero_compatibility(
    hero_identifier: str, rank: str = "all", size: int = 10,
    days: int = DEFAULT_WINDOW_DAYS, use_cache: bool = True,
) -> list[dict]:
    # `days` is accepted by this endpoint but was never passed, leaving it
    # on its 1-day default — see DEFAULT_WINDOW_DAYS. Verified supported:
    # at days=7 every returned hero_win_rate matches heroes_rank at days=7
    # exactly (Miya and Gusion, 10/10 heroes).
    def _fetch() -> list[dict]:
        client = get_client()
        try:
            response = client.heroes.hero_compatibility(
                hero_identifier=hero_identifier, days=days, rank=rank, size=size, index=1,
            )
        except RoneArenaError as e:
            raise RuntimeError(
                f"Failed to fetch compatibility for '{hero_identifier}': {e}"
            ) from e

        records = response.get("data", {}).get("records", [])
        return _parse_hero_relation_response(records, "sub_hero")

    cached = _cached_call(("hero_compatibility", str(hero_identifier).lower(), rank, size, days),
                          _ttl(use_cache), _fetch)
    return [dict(row) for row in cached]


def get_recommended_guides(size: int = 20) -> list[dict]:
    
    client = get_client()
    try:
        response = client.academy.recommended(size=size, index=1)
    except RoneArenaError as e:
        raise RuntimeError(f"Failed to fetch recommended guides: {e}") from e

    records = response.get("data", {}).get("records", [])
    return records


def get_heroes_by_lane(lane: str, size: int = 200, use_cache: bool = True) -> list[dict]:
    # The safest thing here to cache: only five lanes exist and a roster
    # changes on patches, not between drafts.
    def _fetch() -> list[dict]:
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

    cached = _cached_call(("heroes_by_lane", lane, size), _ttl(use_cache), _fetch)
    return [dict(row) for row in cached]


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
