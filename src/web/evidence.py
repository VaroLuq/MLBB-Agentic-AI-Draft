"""
Works out, for each recommended hero, what supporting evidence actually
appeared in the context the agent was given: the live tier list, the live
counter/synergy data for the picks already made, and the retrieved notes.

This is derived after the fact from draft_agent's own output
(live_stats_summary / retrieved_notes), so it changes nothing about how
recommendations are produced. It exists because the reliability work found
that a model can ignore live data it was handed (the Aamon/exp trace) —
so the UI should say plainly which picks are backed by data and which
rest on model knowledge alone, instead of every rationale sounding equally sure.
"""
import re

_TIER = re.compile(r"^Current top win-rate heroes")
_COUNTER = re.compile(r"^Strong counters to enemy hero (.+?):\s*$")
_SYNERGY = re.compile(r"^Good teammates for ally hero (.+?):\s*$")
_ENTRY = re.compile(r"^- (.+?)(?: \(|: )")
_NOTE_TAG = re.compile(r"(?m)^\[([^\]\n]+)\] ")


def _live_stat_entries(summary: str) -> list[tuple[str, str, str | None]]:
    """(hero, kind, subject) for every entry line, tagged by the section it sits under."""
    entries = []
    kind, subject = None, None
    for line in (summary or "").splitlines():
        if _TIER.match(line):
            kind, subject = "tier", None
        elif m := _COUNTER.match(line):
            kind, subject = "counter", m.group(1)
        elif m := _SYNERGY.match(line):
            kind, subject = "synergy", m.group(1)
        elif kind and (m := _ENTRY.match(line)):
            entries.append((m.group(1).strip(), kind, subject))
    return entries


def _note_chunks(retrieved_notes: str) -> list[tuple[str, str]]:
    """(tag, text) per retrieved note chunk; the tag is the hero_name metadata."""
    parts = _NOTE_TAG.split(retrieved_notes or "")
    # split() with one capture group yields: [preamble, tag, text, tag, text, ...]
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _mentions(text: str, hero: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(hero)}(?!\w)", text, re.IGNORECASE) is not None


def evidence_for(hero: str, live_stats_summary: str, retrieved_notes: str) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    def add(kind: str, label: str, subject: str | None = None) -> None:
        if (kind, subject) not in seen:
            seen.add((kind, subject))
            found.append({"kind": kind, "label": label})

    for name, kind, subject in _live_stat_entries(live_stats_summary):
        if name.lower() != hero.lower():
            continue
        if kind == "counter":
            add("counter", f"Counters {subject}", subject)
        elif kind == "synergy":
            add("synergy", f"Pairs with {subject}", subject)
        else:
            add("tier", "Top win rate this week")

    for tag, text in _note_chunks(retrieved_notes):
        if tag.lower() == hero.lower() or _mentions(text, hero):
            add("note", "In your notes")
            break

    return found
