from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_guides(
    documents: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 100,
) -> list[Document]:
   
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n## ", "\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_documents(documents)

    counts_per_source: dict[str, int] = {}
    for chunk in chunks:
        source = chunk.metadata.get("source", "unknown")
        counts_per_source[source] = counts_per_source.get(source, 0) + 1
        chunk.metadata["chunk_index"] = counts_per_source[source] - 1

    return chunks


if __name__ == "__main__":
    from src.rag.note_loader import load_all_notes

    docs = load_all_notes()
    chunks = chunk_guides(docs)

    print(f"Loaded {len(docs)} notes -> split into {len(chunks)} chunks.\n")
    for chunk in chunks[:3]:
        print("---")
        print(f"hero: {chunk.metadata.get('hero_name')} "
              f"(chunk {chunk.metadata.get('chunk_index')} of "
              f"{chunk.metadata.get('source')})")
        print(f"preview: {chunk.page_content[:120]!r}")
