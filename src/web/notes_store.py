"""
File-backed CRUD over the curated strategy notes in data/raw/, for the
web app's Notebook view. This deliberately follows the folder convention
note_loader.py already owns (general/ and heroes/<Name>/) rather than
inventing a second store: the files on disk stay the single source of
truth, and ingestion keeps reading them exactly as before.

A note's id is its path relative to data/raw/ in posix form
("general/x.md", "heroes/Lolita/x.md"). Every id coming from the browser
is validated against that shape and re-resolved under RAW_DIR before any
read, write or delete — the API can delete files, so a crafted id must
never be able to reach outside the notes folders.
"""
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from src.rag.note_loader import RAW_DIR, GENERAL_DIR, HEROES_DIR, SUPPORTED_SUFFIXES

EDITABLE_SUFFIXES = {".md", ".txt"}

# add_note.py names files "<YYYYMMDD>_<HHMMSS>_<slug>.md" in local time.
_TIMESTAMP_PREFIX = re.compile(r"^(\d{8})_(\d{6})_")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
# Hero folder names: letters/digits first, then letters, digits, space, dot,
# apostrophe, hyphen ("Popol and Kupa", "Chang'e", "X.Borg", "Yi Sun-shin").
_HERO_NAME = re.compile(r"^\w[\w .'\-]{0,63}$")


class NoteNotFound(Exception):
    pass


class NoteNotEditable(Exception):
    pass


class InvalidHero(Exception):
    pass


def validate_hero(hero: str | None) -> str | None:
    """None/empty means a general note; anything else must look like a hero folder name."""
    if hero is None or not str(hero).strip():
        return None
    hero = str(hero).strip()
    if not _HERO_NAME.match(hero):
        raise InvalidHero(f"'{hero}' isn't a valid hero name.")
    return hero


def _note_files():
    """Yield (path, hero_or_None) for every supported note file, general first."""
    if GENERAL_DIR.exists():
        for path in sorted(GENERAL_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield path, None
    if HEROES_DIR.exists():
        for hero_dir in sorted(HEROES_DIR.iterdir()):
            if not hero_dir.is_dir():
                continue
            for path in sorted(hero_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                    yield path, hero_dir.name


def _note_id(path: Path) -> str:
    return path.relative_to(RAW_DIR).as_posix()


def _resolve(note_id: str) -> Path:
    if "\\" in note_id or "\x00" in note_id:
        raise NoteNotFound(note_id)
    parts = note_id.split("/")
    is_general = len(parts) == 2 and parts[0] == "general"
    is_hero = len(parts) == 3 and parts[0] == "heroes" and _HERO_NAME.match(parts[1])
    if not (is_general or is_hero):
        raise NoteNotFound(note_id)

    root = RAW_DIR.resolve()
    resolved = RAW_DIR.joinpath(*parts).resolve()
    if root not in resolved.parents:
        raise NoteNotFound(note_id)
    if resolved.suffix.lower() not in SUPPORTED_SUFFIXES or not resolved.is_file():
        raise NoteNotFound(note_id)
    return resolved


def _created_at(path: Path) -> datetime:
    match = _TIMESTAMP_PREFIX.match(path.name)
    if match:
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _title_and_snippet(text: str, fallback: str) -> tuple[str, str]:
    """
    Notes written through the app open with a generic "# Lolita note"
    heading, so the most specific leading heading wins over it; when
    every heading is generic (or absent) the first sentence of the body
    becomes the title instead, since that's what actually identifies the note.
    """
    headings: list[str] = []
    body: list[str] = []
    still_in_headings = True
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _HEADING.match(line)
        if match and still_in_headings:
            headings.append(match.group(1))
            continue
        still_in_headings = False
        body.append(line.strip())

    specific = [h for h in headings if not re.search(r"\bnote$", h, re.IGNORECASE)]
    body_text = " ".join(body)

    if specific:
        title = specific[-1].replace("_", " ").strip()
        title = title[:1].upper() + title[1:]
    elif body_text:
        first_sentence = re.split(r"(?<=[.!?])\s", body_text, maxsplit=1)[0]
        title = first_sentence if len(first_sentence) <= 64 else first_sentence[:61].rstrip() + "..."
    else:
        title = fallback

    return title, body_text[:180]


def list_notes() -> list[dict]:
    notes = []
    for path, hero in _note_files():
        suffix = path.suffix.lower()
        editable = suffix in EDITABLE_SUFFIXES
        title, snippet = path.stem, ""
        if editable:
            try:
                title, snippet = _title_and_snippet(path.read_text(encoding="utf-8"), path.stem)
            except (OSError, UnicodeDecodeError):
                pass
        notes.append({
            "id": _note_id(path),
            "hero": hero,
            "file_name": path.name,
            "suffix": suffix,
            "editable": editable,
            "title": title,
            "snippet": snippet,
            "created": _created_at(path).isoformat(timespec="seconds"),
            "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })
    notes.sort(key=lambda n: n["updated"], reverse=True)
    return notes


def read_note(note_id: str) -> dict:
    path = _resolve(note_id)
    suffix = path.suffix.lower()
    editable = suffix in EDITABLE_SUFFIXES
    parts = note_id.split("/")
    hero = parts[1] if parts[0] == "heroes" else None
    content = path.read_text(encoding="utf-8") if editable else None
    title, _ = _title_and_snippet(content or "", path.stem) if editable else (path.stem, "")
    return {
        "id": note_id,
        "hero": hero,
        "file_name": path.name,
        "suffix": suffix,
        "editable": editable,
        "title": title,
        "content": content,
        "created": _created_at(path).isoformat(timespec="seconds"),
        "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def write_note(note_id: str, content: str) -> None:
    path = _resolve(note_id)
    if path.suffix.lower() not in EDITABLE_SUFFIXES:
        raise NoteNotEditable(note_id)
    path.write_text(content, encoding="utf-8")


def delete_note(note_id: str) -> None:
    _resolve(note_id).unlink()


# --- Knowledge-base freshness -------------------------------------------
#
# Editing or deleting a note doesn't touch the vector store; retrieval keeps
# serving the old chunks until the knowledge base is rebuilt. The Notebook
# view surfaces that gap, so we remember a fingerprint of the notes as they
# were at the last rebuild done through this app. (Rebuilds run from the CLI
# don't record one; they read as stale until rebuilt here — the safe direction.)

def _persist_dir() -> Path:
    return Path(os.getenv("CHROMA_PERSIST_DIR", "./vectorstore"))


def _signature() -> str:
    digest = hashlib.sha1()
    for path, _ in _note_files():
        stat = path.stat()
        digest.update(f"{_note_id(path)}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
    return digest.hexdigest()


def mark_rebuilt() -> None:
    directory = _persist_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".notes_signature").write_text(_signature(), encoding="utf-8")


def kb_is_stale() -> bool:
    signature_file = _persist_dir() / ".notes_signature"
    if signature_file.exists():
        return signature_file.read_text(encoding="utf-8").strip() != _signature()

    # No fingerprint yet (first run of the web app, or only ever rebuilt from
    # the CLI). Comparing modified-times here would look reassuring but can't
    # see deleted notes, which may still be indexed — so "unknown" reads as
    # stale until one rebuild through the app records a fingerprint.
    has_notes = any(True for _ in _note_files())
    has_index = (_persist_dir() / "chroma.sqlite3").exists()
    return has_notes or has_index
