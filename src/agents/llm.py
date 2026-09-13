import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_BASE_URL = "http://localhost:11434"

_cached_llm = None


def get_llm(temperature: float = 0.2) -> ChatOllama:
    global _cached_llm
    if _cached_llm is None:
        model = os.getenv("OLLAMA_MODEL", DEFAULT_MODEL)
        base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        _cached_llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    return _cached_llm
