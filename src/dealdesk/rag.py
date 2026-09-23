"""Retrieval over the borrower guides (knowledge/*.md).

Documents are chunked by markdown '##' section and ranked with BM25. Pure Python so it
runs anywhere (CI, Docker, a laptop) with no vector database; swap in embeddings later
behind the same `search()` interface.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(os.getenv("DEALDESK_KNOWLEDGE_DIR",
                               Path(__file__).resolve().parents[2] / "knowledge"))
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?%?")
_STOP = set("a an and are as at be by for from in is it of on or that the to with this".split())


@dataclass(frozen=True)
class Chunk:
    doc: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.doc} § {self.section}"


def _stem(t: str) -> str:
    """Light suffix stripping so 'exceptions'/'exception', 'approves'/'approval' match."""
    for suf in ("ation", "ing", "als", "al", "es", "ed", "s", "e"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def load_chunks(directory: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(directory.glob("*.md")):
        title, section, lines = path.stem, None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if section and lines:
                    chunks.append(Chunk(title, section, " ".join(lines).strip()))
                section, lines = line[3:].strip(), []
            elif line.strip():
                lines.append(line.strip())
        if section and lines:
            chunks.append(Chunk(title, section, " ".join(lines).strip()))
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.docs = [_tokens(f"{c.doc} {c.section} {c.section} {c.text}") for c in chunks]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        q = _tokens(query)
        scores = []
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            s = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1)
                    / (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                    for t in q if t in tf)
            scores.append((s, i))
        scores.sort(reverse=True)
        return [(self.chunks[i], round(s, 3)) for s, i in scores[:k] if s > 0]


@lru_cache(maxsize=1)
def default_index() -> BM25Index:
    return BM25Index(load_chunks())


def search(query: str, k: int = 3) -> list[dict]:
    return [{"citation": c.citation, "score": s, "text": c.text}
            for c, s in default_index().search(query, k)]
