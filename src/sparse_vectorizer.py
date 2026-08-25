import json
import re
from pathlib import Path

from qdrant_client.models import SparseVector
from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25SparseVectorizer:
    """BM25 as a dot product, split across document and query vectors:
    doc_vector carries the term-frequency weight, query_vector carries the
    idf weight, so dot(doc_vector, query_vector) ~= the BM25 score.

    NOTE for a future file-upload feature (not implemented yet): idf/vocab/
    avgdl are fit globally over the whole corpus. Adding a new document
    later means re-fitting on ALL documents (existing + new) and
    re-upserting every existing chunk's sparse vector with the updated
    vectorizer — vectorizing just the new file against the old fitted
    vocab would silently drift the corpus-wide statistics.
    """

    def __init__(self) -> None:
        self.vocab: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.avgdl: float = 0.0
        self.k1: float = 1.5
        self.b: float = 0.75

    def fit(self, texts: list[str]) -> "BM25SparseVectorizer":
        tokenized = [_tokenize(text) for text in texts]
        bm25 = BM25Okapi(tokenized)
        self.idf = dict(bm25.idf)
        self.vocab = {term: index for index, term in enumerate(sorted(self.idf))}
        self.avgdl = bm25.avgdl
        self.k1 = bm25.k1
        self.b = bm25.b
        return self

    def doc_vector(self, text: str) -> SparseVector:
        tokens = _tokenize(text)
        doc_len = len(tokens)
        freqs: dict[str, int] = {}
        for token in tokens:
            if token in self.vocab:
                freqs[token] = freqs.get(token, 0) + 1

        length_norm = 1 - self.b + self.b * (doc_len / self.avgdl if self.avgdl else 0)
        indices = []
        values = []
        for term, freq in freqs.items():
            weight = (freq * (self.k1 + 1)) / (freq + self.k1 * length_norm)
            indices.append(self.vocab[term])
            values.append(weight)
        return SparseVector(indices=indices, values=values)

    def query_vector(self, text: str) -> SparseVector:
        tokens = _tokenize(text)
        freqs: dict[str, int] = {}
        for token in tokens:
            if token in self.vocab:
                freqs[token] = freqs.get(token, 0) + 1

        indices = []
        values = []
        for term, freq in freqs.items():
            indices.append(self.vocab[term])
            values.append(self.idf[term] * freq)
        return SparseVector(indices=indices, values=values)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "vocab": self.vocab,
            "idf": self.idf,
            "avgdl": self.avgdl,
            "k1": self.k1,
            "b": self.b,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "BM25SparseVectorizer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        instance = cls()
        instance.vocab = payload["vocab"]
        instance.idf = payload["idf"]
        instance.avgdl = payload["avgdl"]
        instance.k1 = payload["k1"]
        instance.b = payload["b"]
        return instance
