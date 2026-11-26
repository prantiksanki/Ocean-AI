"""Document loading, chunking and retrieval (embeddings with BM25 fallback)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import llm

SUPPORTED = {".pdf", ".txt", ".md", ".csv"}


@dataclass
class Chunk:
    id: str
    source: str
    text: str


def load_documents(folder: str | Path) -> dict[str, str]:
    """Return {filename: text}. CSV rows are rendered as 'col: val' lines."""
    folder = Path(folder)
    docs: dict[str, str] = {}
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED:
            continue
        name = str(p.relative_to(folder)).replace("\\", "/")
        ext = p.suffix.lower()
        if ext == ".pdf":
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        elif ext == ".csv":
            with open(p, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            text = "\n".join("; ".join(f"{k}: {v}" for k, v in r.items()) for r in rows)
        else:
            text = p.read_text(encoding="utf-8", errors="ignore")
        if text.strip():
            docs[name] = text
    if not docs:
        raise FileNotFoundError(f"no readable documents in {folder}")
    return docs


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Paragraph/line-aware chunking with character overlap."""
    units = [u.strip() for u in re.split(r"\n\s*\n|\n", text) if u.strip()]
    chunks, cur = [], ""
    for u in units:
        if cur and len(cur) + len(u) + 1 > size:
            chunks.append(cur)
            cur = cur[-overlap:] + " " + u if overlap else u
        else:
            cur = f"{cur}\n{u}" if cur else u
        while len(cur) > size * 1.5:  # a single huge unit
            chunks.append(cur[:size])
            cur = cur[size - overlap:]
    if cur.strip():
        chunks.append(cur)
    return chunks


def build_chunks(docs: dict[str, str], size: int = 800, overlap: int = 120) -> list[Chunk]:
    out = []
    for name, text in docs.items():
        for i, c in enumerate(chunk_text(text, size, overlap)):
            out.append(Chunk(f"{name}#{i}", name, c))
    return out


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class Index:
    """Dense retrieval via Ollama embeddings; BM25 if embeddings are unavailable."""

    def __init__(self, chunks: list[Chunk], use_embeddings: bool | None = None):
        self.chunks = chunks
        self.dense = llm.embeddings_available() if use_embeddings is None else use_embeddings
        if self.dense:
            self.matrix = np.array(llm.embed([c.text[:1500] for c in chunks]), dtype=np.float32)
            self.matrix /= np.linalg.norm(self.matrix, axis=1, keepdims=True) + 1e-9
        from rank_bm25 import BM25Okapi
        self.bm25 = BM25Okapi([_tok(c.text) for c in chunks])

    def search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        bm = np.array(self.bm25.get_scores(_tok(query)), dtype=np.float32)
        if bm.max() > 0:
            bm = bm / bm.max()
        if self.dense:
            q = np.array(llm.embed([query])[0], dtype=np.float32)
            q /= np.linalg.norm(q) + 1e-9
            dense = self.matrix @ q
            score = 0.7 * dense + 0.3 * bm  # hybrid: dense + lexical
        else:
            score = bm
        idx = np.argsort(-score)[:top_k]
        return [(self.chunks[i], float(score[i])) for i in idx]


def keyword_overlap(topic: str, texts: list[str]) -> float:
    """Fraction of a topic's content words present in the given texts (cheap grounding signal)."""
    stop = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "about", "with", "is",
            "are", "what", "how", "policy", "questions", "information", "details"}
    words = {w for w in _tok(topic) if w not in stop and len(w) > 2}
    if not words:
        return 1.0
    hay = set(_tok(" ".join(texts)))
    return sum(1 for w in words if w in hay) / len(words)
