import hashlib
import json
import os
import threading
import time
from pathlib import Path
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
# TTL is deliberately long. Every endpoint reports over a 7-day trailing
# window (DEFAULT_WINDOW_DAYS), so the underlying numbers move far more slowly
# than a drafting session. Measured against this project's own snapshot
# history: the median largest daily win-rate move is 0.13 points, against a
# counter_strength scale where "typical" is 2.6 points — day-old data almost
# never changes a recommendation.
#
# CAVEAT WORTH KEEPING IN VIEW at the current 96h default: those same snapshots
# show a 2.31-point move across a 3-day window, and the Meta-Watcher's own
# threshold for "this is a real meta move" is 2 points. So a 4-day TTL can
# serve data this codebase would elsewhere call drifted. That is a deliberate,
# informed trade for speed, not an oversight; lower it if recommendations start
# disagreeing with the Meta-Watcher view.
CACHE_TTL_SECONDS = float(os.getenv("RONE_CACHE_TTL_SECONDS", str(96 * 3600)))

# On-disk tier. The in-memory tier dies with the process, so every app launch
# used to re-pay the startup prefetch (7 calls, 12-17s) plus every hero in the
# first draft. Disk makes that survive restarts.
DISK_CACHE_DIR = Path(os.getenv("RONE_CACHE_DIR", "data/api_cache"))
DISK_CACHE_ENABLED = os.getenv("RONE_DISK_CACHE", "1").lower() not in {"0", "false", "no"}

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _disk_path(key: tuple) -> Path:
    # The key is a tuple of endpoint + args; hash it for a filesystem-safe name
    # and keep the endpoint as a readable prefix so the directory is skimmable.
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
    return DISK_CACHE_DIR / f"{str(key[0])[:32]}_{digest}.json"


def _disk_read(key: tuple, ttl: float, now: float):
    if not DISK_CACHE_ENABLED:
        return None
    path = _disk_path(key)
    try:
        with path.open(encoding="utf-8") as fh:
            entry = json.load(fh)
        if now - float(entry["stored_at"]) >= ttl:
            return None
        return entry["value"]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        # A truncated or hand-edited file is a cache miss, never a crash.
        return None


def _disk_write(key: tuple, value: object, now: float) -> None:
    if not DISK_CACHE_ENABLED:
        return
    path = _disk_path(key)
    try:
        DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: another process reading concurrently sees either
        # the old complete file or the new one, never a half-written one.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"key": [str(part) for part in key], "stored_at": now, "value": value}, fh)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass  # caching is an optimisation; never let it break a request


def _cached_call(key: tuple, ttl: float, loader: Callable[[], object]) -> object:
    """Return a cached response, or fetch and store one.

    Two tiers: an in-process dict, then JSON on disk. A warm process never
    touches the filesystem; a fresh one inherits whatever the last run fetched.

    Wall-clock (`time.time`) rather than `time.monotonic`, because monotonic
    clocks are not comparable across processes or restarts, and the disk tier
    has to survive both.

    The lock is deliberately NOT held across `loader()`: an HTTP call can take
    seconds, and blocking every other reader for that long would be worse than
    the only thing releasing it costs, which is that two concurrent misses on
    the same key may both fetch. That wastes a request; it cannot corrupt the
    cache or return anything stale.
    """
    if ttl <= 0:
        return loader()

    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]

    from_disk = _disk_read(key, ttl, now)
    if from_disk is not None:
        with _cache_lock:
            # Keep the disk entry's own age; promoting it with a fresh
            # timestamp would let a value renew itself forever.
            _cache[key] = (now - _disk_age(key, now), from_disk)
        return from_disk

    value = loader()
    stored = time.time()
    with _cache_lock:
        _cache[key] = (stored, value)
    _disk_write(key, value, stored)
    return value


def _disk_age(key: tuple, now: float) -> float:
    try:
        with _disk_path(key).open(encoding="utf-8") as fh:
            return max(0.0, now - float(json.load(fh)["stored_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def _ttl(use_cache: bool) -> float:
    return CACHE_TTL_SECONDS if use_cache else 0.0


def clear_cache() -> None:
    """Drop every cached response, in memory and on disk."""
    with _cache_lock:
        _cache.clear()
    if not DISK_CACHE_ENABLED:
        return
    try:
        for path in DISK_CACHE_DIR.glob("*.json"):
            path.unlink(missing_ok=True)
    except OSError:
        pass


def cache_info() -> dict:
    """Entry counts and keys for both tiers, for diagnostics and tests."""
    with _cache_lock:
        info = {"entries": len(_cache), "keys": sorted(str(k) for k in _cache)}
    info["ttl_seconds"] = CACHE_TTL_SECONDS
    info["disk_enabled"] = DISK_CACHE_ENABLED
    info["disk_dir"] = str(DISK_CACHE_DIR)
    try:
        info["disk_entries"] = len(list(DISK_CACHE_DIR.glob("*.json"))) if DISK_CACHE_ENABLED else 0
    except OSError:
        info["disk_entries"] = 0
    return info


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
            # `head` is a 128x128 square face crop, `smallmap` the 240x390 full
            # art. Both come back attached to the hero record itself, so the
            # name->image mapping is the API's, not something reconstructed by
            # pairing two separately-ordered lists.
            "head": hero_info.get("head"),
            "art": hero_info.get("smallmap"),
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
