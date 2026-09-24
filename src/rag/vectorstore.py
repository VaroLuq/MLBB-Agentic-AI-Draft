import os
import threading

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from chromadb.config import Settings

from src.rag.embedder import get_embedding_function

load_dotenv()

DEFAULT_PERSIST_DIR = "./vectorstore"
COLLECTION_NAME = "mlbb_guides"

_cached_vectorstore = None
_vectorstore_lock = threading.Lock()


def _persist_dir() -> str:
    return os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR)


def _chroma_settings() -> Settings:
    """
    Build a fresh Settings object per call rather than sharing one
    module-level instance. Two things matter here, both found the
    hard way (a real "Could not connect to tenant default_tenant"
    crash from an empty-looking vectorstore/ directory):

    1. `is_persistent=True` must be set EXPLICITLY. langchain_chroma's
       Chroma.__init__ only copies `persist_directory` onto whatever
       client_settings you hand it — it does not default
       is_persistent to True the way its OTHER branch (the one taken
       when you pass persist_directory with no client_settings at
       all) does. chromadb.config.Settings defaults is_persistent to
       False. Net effect without this: every Chroma client silently
       became in-memory-only, despite persist_directory being set —
       ingestion would report success and write nothing to disk.
    2. A single shared Settings object, mutated in place across
       repeated Chroma() instantiations (build_vectorstore alone
       creates two, back-to-back), is exactly the kind of shared
       mutable state that trips chromadb's per-process system cache
       and produces confusing tenant/database errors. Cheap to avoid
       by just not sharing it.
    """
    return Settings(
        anonymized_telemetry=False,
        is_persistent=True,
        persist_directory=_persist_dir(),
    )


def build_vectorstore(chunks: list[Document]) -> Chroma:

    embedding_function = get_embedding_function()

    Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_function,
        persist_directory=_persist_dir(),
        client_settings=_chroma_settings(),
    ).delete_collection()

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embedding_function,
        collection_name=COLLECTION_NAME,
        persist_directory=_persist_dir(),
        client_settings=_chroma_settings(),
    )

    return vectorstore


def get_vectorstore() -> Chroma:
    # Locked because the web server warms this on a background thread at
    # startup while still accepting requests. Without the lock a request
    # arriving mid-warm-up saw `None`, started its own load, and paid the
    # full embedder cost again — which is exactly what made the first
    # recommendation after launch slow despite the warm-up existing.
    global _cached_vectorstore
    if _cached_vectorstore is not None:
        return _cached_vectorstore

    with _vectorstore_lock:
        if _cached_vectorstore is None:
            _cached_vectorstore = Chroma(
                collection_name=COLLECTION_NAME,
                embedding_function=get_embedding_function(),
                persist_directory=_persist_dir(),
                client_settings=_chroma_settings(),
            )
    return _cached_vectorstore


def clear_vectorstore_cache() -> None:
    # Deliberately does NOT clear the embedder: re-ingesting changes the
    # collection, not the model, so a rebuild should not pay a reload.
    global _cached_vectorstore
    with _vectorstore_lock:
        _cached_vectorstore = None
