"""In-memory vector store over the markdown runbooks.

Uses OpenAI embeddings when a key is present, otherwise a deterministic offline
embedding (see llm.embed). Cosine similarity over the chunks; swap in Chroma or
pgvector if the corpus grows.
"""
from __future__ import annotations
import os
import glob
from dataclasses import dataclass
from typing import List
import numpy as np

from ..llm import embed

_RUNBOOK_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "runbooks")


@dataclass
class Chunk:
    source: str
    text: str
    vec: np.ndarray


class RunbookStore:
    def __init__(self) -> None:
        self.chunks: List[Chunk] = []

    def build(self) -> "RunbookStore":
        docs = []
        for path in sorted(glob.glob(os.path.join(_RUNBOOK_DIR, "*.md"))):
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            name = os.path.basename(path)
            for para in _chunk(text):
                docs.append((name, para))
        if not docs:
            return self
        vecs = embed([d[1] for d in docs])
        for (name, para), v in zip(docs, vecs):
            self.chunks.append(Chunk(name, para, np.array(v, dtype=np.float32)))
        return self

    def search(self, query: str, k: int = 3) -> List[dict]:
        if not self.chunks:
            return []
        q = np.array(embed([query])[0], dtype=np.float32)
        scored = []
        for c in self.chunks:
            denom = (np.linalg.norm(q) * np.linalg.norm(c.vec)) or 1.0
            score = float(np.dot(q, c.vec) / denom)
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"source": c.source, "text": c.text, "score": round(s, 3)}
                for s, c in scored[:k]]


def _chunk(text: str) -> List[str]:
    # split on blank lines, keep headed sections together, drop tiny fragments
    blocks, cur = [], []
    for line in text.splitlines():
        if line.strip() == "" and cur:
            blocks.append("\n".join(cur).strip())
            cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if len(b) > 40]


_STORE: RunbookStore | None = None


def get_store() -> RunbookStore:
    global _STORE
    if _STORE is None:
        _STORE = RunbookStore().build()
    return _STORE
