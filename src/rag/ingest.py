import time

from src.rag.note_loader import load_all_notes
from src.rag.chunker import chunk_guides
from src.rag.vectorstore import build_vectorstore, clear_vectorstore_cache


def run_ingestion():
    print("Loading notes from data/raw/...")
    documents = load_all_notes()
    print(f"  -> {len(documents)} note documents loaded.\n")

    if not documents:
        print("No notes found — nothing to ingest. Add content via "
              "`python -m src.rag.add_note \"...\"` or by placing files "
              "in data/raw/general/ or data/raw/heroes/<HeroName>/.")
        return

    print("Chunking notes...")
    chunks = chunk_guides(documents)
    print(f"  -> {len(chunks)} chunks created.\n")

    print("Embedding chunks and writing to Chroma...")
    start = time.time()
    build_vectorstore(chunks)
    clear_vectorstore_cache()
    elapsed = time.time() - start
    print(f"  -> Done in {elapsed:.1f}s.\n")

    print("Ingestion complete. Guide vector store is ready for querying.")


if __name__ == "__main__":
    run_ingestion()
