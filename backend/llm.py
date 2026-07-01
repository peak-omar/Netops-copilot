"""LLM + embeddings access with a no-key fallback so the demo always runs."""
from __future__ import annotations
import math
from typing import List

from . import config

_chat = None
_openai_client = None


def get_chat_model(temperature: float = 0.1):
    """Return a LangChain ChatOpenAI bound-ready model, or None in mock mode."""
    global _chat
    if config.USE_MOCK_LLM:
        return None
    if _chat is None:
        from langchain_openai import ChatOpenAI
        _chat = ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
        )
    return _chat


def _client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


# ---------------------------------------------------------------------------
# Embeddings for RAG. Falls back to a deterministic hashing embedding offline
# so the vector store still works (lower quality, but fully functional).
# ---------------------------------------------------------------------------
def embed(texts: List[str]) -> List[List[float]]:
    if not config.USE_MOCK_LLM:
        try:
            resp = _client().embeddings.create(
                model=config.OPENAI_EMBED_MODEL, input=texts
            )
            return [d.embedding for d in resp.data]
        except Exception:
            pass  # fall through to offline embedding
    return [_hash_embed(t) for t in texts]


def _hash_embed(text: str, dim: int = 256) -> List[float]:
    """Cheap deterministic bag-of-words embedding for offline mode."""
    vec = [0.0] * dim
    for tok in _tokenize(text):
        vec[hash(tok) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _tokenize(text: str) -> List[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]
