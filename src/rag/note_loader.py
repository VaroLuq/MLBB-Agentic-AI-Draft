from pathlib import Path
from datetime import datetime
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

RAW_DIR = Path("data/raw")
GENERAL_DIR = RAW_DIR / "general"
HEROES_DIR = RAW_DIR / "heroes"

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".docx"}


def _load_single_file(path: Path, hero_name: str | None) -> list[Document]:
   
    suffix = path.suffix.lower()

    if suffix in (".md", ".txt"):
        text = path.read_text(encoding="utf-8")
        raw_docs = [Document(page_content=text)]
    elif suffix == ".pdf":
        raw_docs = PyPDFLoader(str(path)).load()
    elif suffix == ".docx":
        raw_docs = Docx2txtLoader(str(path)).load()
    else:
        return []  # unsupported type, silently skipped by the caller's check

    ingested_at = datetime.now().isoformat()
    for doc in raw_docs:
        doc.metadata.update({
            "source": str(path),
            "doc_type": "strategy_note",
            "hero_name": hero_name if hero_name else "general",
            "file_name": path.name,
            "ingested_at": ingested_at,
        })

    return raw_docs


def load_all_notes() -> list[Document]:

    documents: list[Document] = []

    if GENERAL_DIR.exists():
        for path in sorted(GENERAL_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                try:
                    documents.extend(_load_single_file(path, hero_name=None))
                except Exception as e:
                    print(f"[error] Failed to load {path.name}: {e}")

    if HEROES_DIR.exists():
        for hero_dir in sorted(HEROES_DIR.iterdir()):
            if not hero_dir.is_dir():
                continue
            hero_name = hero_dir.name
            for path in sorted(hero_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                    try:
                        documents.extend(_load_single_file(path, hero_name=hero_name))
                    except Exception as e:
                        print(f"[error] Failed to load {path.name}: {e}")

    return documents


if __name__ == "__main__":
    docs = load_all_notes()
    print(f"Loaded {len(docs)} note documents.\n")
    for doc in docs[:5]:
        print("---")
        print(f"hero_name: {doc.metadata.get('hero_name')}")
        print(f"source: {doc.metadata.get('source')}")
        print(f"preview: {doc.page_content[:150]!r}")

    if not docs:
        print("No notes found yet. Add a .md/.txt/.pdf/.docx file to "
              "data/raw/general/ or data/raw/heroes/<HeroName>/, or use "
              "`python -m src.rag.add_note` for a quick one-liner.")
