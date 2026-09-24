import os
import threading

from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Constructing HuggingFaceEmbeddings loads the sentence-transformers model,
# which is the single most expensive thing this app does at startup —
# measured 27-35s for the Harrier embedder. It used to be rebuilt on every
# call, which mattered in two places: a knowledge-base rebuild clears the
# vectorstore cache and so paid a full reload, and a request arriving while
# the server's warm-up thread was still loading started a SECOND load rather
# than waiting for the first.
_cached_embeddings: HuggingFaceEmbeddings | None = None
_cached_model_name: str | None = None
_embedder_lock = threading.Lock()


def get_embedding_function() -> HuggingFaceEmbeddings:
    global _cached_embeddings, _cached_model_name
    model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL)

    # Double-checked: the common path never takes the lock, and a concurrent
    # first call blocks on the in-flight load instead of starting its own.
    if _cached_embeddings is not None and _cached_model_name == model_name:
        return _cached_embeddings

    with _embedder_lock:
        if _cached_embeddings is None or _cached_model_name != model_name:
            _cached_embeddings = HuggingFaceEmbeddings(
                model_name=model_name,
                encode_kwargs={"normalize_embeddings": True},
            )
            _cached_model_name = model_name
    return _cached_embeddings


def clear_embedder_cache() -> None:
    """Drop the loaded model. Only needed if EMBEDDING_MODEL changes in-process."""
    global _cached_embeddings, _cached_model_name
    with _embedder_lock:
        _cached_embeddings = None
        _cached_model_name = None
