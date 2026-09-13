import argparse
import re
from pathlib import Path
from datetime import datetime

RAW_DIR = Path("data/raw")


def _slugify(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:max_words]
    return "-".join(words) if words else "note"


def add_note(text: str, hero: str | None = None, title: str | None = None) -> Path:
    
    if hero:
        target_dir = RAW_DIR / "heroes" / hero
    else:
        target_dir = RAW_DIR / "general"

    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(title or text)
    file_path = target_dir / f"{timestamp}_{slug}.md"

    heading = title or (f"{hero} note" if hero else "General note")
    content = f"# {heading}\n\n{text}\n"
    file_path.write_text(content, encoding="utf-8")

    return file_path


def main():
    parser = argparse.ArgumentParser(
        description="Quickly add a Mobile Legends strategy note for RAG ingestion."
    )
    parser.add_argument("text", help="The note content itself.")
    parser.add_argument("--hero", default=None,
                         help="Tag this note to a specific hero (creates/uses "
                              "data/raw/heroes/<hero>/). Omit for general notes.")
    parser.add_argument("--title", default=None,
                         help="Optional short title for the note.")
    args = parser.parse_args()

    path = add_note(args.text, hero=args.hero, title=args.title)
    print(f"Note saved to: {path}")
    print("Run `python -m src.rag.ingest` to re-index and include it.")


if __name__ == "__main__":
    main()
