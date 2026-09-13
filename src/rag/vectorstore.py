import os
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from chromadb.config import Settings

from src.rag.embedder import get_embedding_function

load_dotenv()

DEFAULT_PERSIST_DIR = "./vectorstore"
COLLECTION_NAME = "mlbb_guides"

_CHROMA_SETTINGS = Settings(anonymized_telemetry=False)

_cached_vectorstore = None


def _persist_dir() -> str:
    return os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR)


def build_vectorstore(chunks: list[Document]) -> Chroma:
   
    embedding_function = get_embedding_function()

    Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_function,
        persist_directory=_persist_dir(),
        client_settings=_CHROMA_SETTINGS,
    ).delete_collection()

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embedding_function,
        collection_name=COLLECTION_NAME,
        persist_directory=_persist_dir(),
        client_settings=_CHROMA_SETTINGS,
    )

    return vectorstore


def get_vectorstore() -> Chroma:
    
    global _cached_vectorstore
    if _cached_vectorstore is None:
        _cached_vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=get_embedding_function(),
            persist_directory=_persist_dir(),
            client_settings=_CHROMA_SETTINGS,
        )
    return _cached_vectorstore


def clear_vectorstore_cache() -> None:
    global _cached_vectorstore
    _cached_vectorstore = None
