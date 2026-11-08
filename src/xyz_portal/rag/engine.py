"""Retrieval engine for the handbook chatbot.

The engine extracts text from a PDF, splits it into overlapping passages,
embeds the passages with a local Sentence Transformers model, and combines
semantic search with BM25 keyword search. Embeddings are cached on disk so
restarts are fast; keyword search still works if embeddings are unavailable.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pypdf import PdfReader

from ..config import RAG_CACHE_DIR
from .tracing import traceable

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 1100
CHUNK_OVERLAP = 180
DENSE_WEIGHT = 0.7
INDEX_VERSION = "2"
CACHE_DIR = RAG_CACHE_DIR

_model = None
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_TOC_ENTRY = re.compile(r"\.{4,}\s*\d+")

# Pages 1-20 are the original handbook. Appendix B (directory) and Appendix C
# (salary) start after that and are restricted by role.
PUBLIC_HANDBOOK_LAST_PAGE = 20
ACCESS_SCOPES = ("public", "directory", "full")
_SALARY_MARKERS = (
    "salary",
    "monthly gross",
    "annual salary",
    "compensation",
    "payroll",
    "provident fund",
)
_DIRECTORY_MARKERS = (
    "employee directory",
    "work email",
    "reports to",
    "department counts",
    "headcount",
    "xyz0",
)


@dataclass(frozen=True)
class Passage:
    """A searchable slice of the handbook."""

    id: int
    page: int
    text: str


@dataclass(frozen=True)
class SearchResult:
    """A passage plus its hybrid relevance score."""

    passage: Passage
    score: float


def passage_access_level(passage: Passage) -> str:
    """Classify a passage as public, directory-only, or salary data.

    The classification is deliberately conservative: anything after the main
    handbook that cannot be positively identified is treated as directory data.
    """
    if passage.page <= PUBLIC_HANDBOOK_LAST_PAGE:
        return "public"

    text = passage.text.lower()
    if any(marker in text for marker in _SALARY_MARKERS):
        return "salary"
    if any(marker in text for marker in _DIRECTORY_MARKERS):
        return "directory"
    return "directory"


def scope_allows(access_scope: str, passage_level: str) -> bool:
    """Return whether a retrieval scope may read a passage level."""
    if access_scope not in ACCESS_SCOPES:
        access_scope = "public"
    if access_scope == "full":
        return True
    if access_scope == "directory":
        return passage_level in ("public", "directory")
    return passage_level == "public"


def _trace_retrieval_inputs(inputs: dict) -> dict:
    """Log only the useful part of a `RagEngine.search` call."""
    query = inputs.get("query", "")
    return {
        "query": query if isinstance(query, str) else str(query),
        "top_k": inputs.get("top_k", 5),
        "access_scope": inputs.get("access_scope", "full"),
    }


def _trace_retrieval_outputs(results: list[SearchResult] | None) -> dict:
    """Summarize retrieved passages for the LangSmith retriever span."""
    results = results or []
    return {
        "count": len(results),
        "passages": [
            {
                "page": result.passage.page,
                "score": round(result.score, 4),
                "text": result.passage.text[:500],
            }
            for result in results
        ],
    }


def _get_embedding_model():
    """Load the embedding model once per process."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def clean_text(raw: str) -> str:
    """Normalize PDF text that was extracted one word per line."""
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\x00", " ").replace("\ufffd", "'")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Pages that open with a table of contents contain long dot leaders. Drop
    # everything up to the last TOC entry so contents listings never become
    # search results (page 2 also starts its introduction after the listing).
    toc_entries = list(_TOC_ENTRY.finditer(text))
    if len(toc_entries) >= 3:
        text = text[toc_entries[-1].end() :]
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _window_long_sentence(sentence: str, max_chars: int, overlap: int) -> list[str]:
    """Split a sentence that is longer than a full chunk by words."""
    words = sentence.split()
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        if current and current_len + len(word) + 1 > max_chars:
            pieces.append(" ".join(current))
            tail: list[str] = []
            tail_len = 0
            for previous in reversed(current):
                if tail_len + len(previous) + 1 > overlap:
                    break
                tail.insert(0, previous)
                tail_len += len(previous) + 1
            current = tail
            current_len = max(tail_len - 1, 0)
        current.append(word)
        current_len += len(word) + 1

    if current:
        pieces.append(" ".join(current))
    return pieces


def split_passages(
    text: str, max_chars: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split text at sentence boundaries with a small overlap."""
    sentences: list[str] = []
    for sentence in _SENTENCE_BREAK.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            sentences.extend(_window_long_sentence(sentence, max_chars, overlap))
        else:
            sentences.append(sentence)

    passages: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        if current and current_len + len(sentence) + 1 > max_chars:
            passages.append(" ".join(current).strip())
            tail: list[str] = []
            tail_len = 0
            for previous in reversed(current):
                if tail_len + len(previous) + 1 > overlap:
                    break
                tail.insert(0, previous)
                tail_len += len(previous) + 1
            current = tail
            current_len = max(tail_len - 1, 0)

        current.append(sentence)
        current_len += len(sentence) + 1

    if current:
        passages.append(" ".join(current).strip())

    return [passage for passage in passages if len(passage) >= 60]


class _BM25:
    """Small, dependency-free BM25 implementation."""

    def __init__(self, texts: list[str]) -> None:
        self._tokenized = [self._tokenize(text) for text in texts]
        self._lengths = [len(tokens) for tokens in self._tokenized]
        self._counts = [Counter(tokens) for tokens in self._tokenized]
        self._size = len(texts)
        self._avg_length = sum(self._lengths) / self._size if self._size else 0.0

        document_frequency: Counter[str] = Counter()
        for tokens in self._tokenized:
            document_frequency.update(set(tokens))

        self._idf = {
            term: math.log(1 + (self._size - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def scores(self, query: str) -> np.ndarray:
        scores = np.zeros(self._size, dtype=np.float32)
        terms = self._tokenize(query)
        if not terms or not self._size:
            return scores

        k1, b = 1.5, 0.75
        for term in terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for index, counts in enumerate(self._counts):
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                length_norm = 1 - b + b * self._lengths[index] / self._avg_length
                scores[index] += (
                    idf * frequency * (k1 + 1) / (frequency + k1 * length_norm)
                )
        return scores


class RagEngine:
    """Hybrid retriever over a single PDF."""

    def __init__(
        self,
        pdf_path: Path,
        passages: list[Passage],
        page_count: int,
        embeddings: np.ndarray | None,
        embedding_error: str | None = None,
    ) -> None:
        self.pdf_path = pdf_path
        self.passages = passages
        self.page_count = page_count
        self.embeddings = embeddings
        self.embedding_error = embedding_error
        self._bm25 = _BM25([passage.text for passage in passages])

    @property
    def search_mode(self) -> str:
        return (
            "Hybrid (semantic + keyword)"
            if self.embeddings is not None
            else "Keyword only"
        )

    @classmethod
    def load(cls, pdf_path: Path) -> RagEngine:
        """Load an index from cache, or build one from the PDF."""
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        fingerprint = hashlib.sha256()
        fingerprint.update(pdf_path.read_bytes())
        fingerprint.update(
            f"{INDEX_VERSION}|{EMBEDDING_MODEL}|{CHUNK_SIZE}|{CHUNK_OVERLAP}".encode()
        )
        cache_path = CACHE_DIR / f"{pdf_path.stem}-{fingerprint.hexdigest()[:16]}.npz"

        if cache_path.exists():
            try:
                with np.load(cache_path, allow_pickle=False) as data:
                    cached_texts = [str(text) for text in data["texts"]]
                    cached_pages = [int(page) for page in data["pages"]]
                    cached_embeddings = np.asarray(data["embeddings"], dtype=np.float32)
                    cached_page_count = int(data["page_count"])
                cached_passages = [
                    Passage(id=index, page=page, text=text)
                    for index, (text, page) in enumerate(
                        zip(cached_texts, cached_pages, strict=True)
                    )
                ]
                return cls(
                    pdf_path,
                    cached_passages,
                    cached_page_count,
                    cached_embeddings,
                )
            except (OSError, ValueError, KeyError):
                cache_path.unlink(missing_ok=True)

        reader = PdfReader(str(pdf_path))
        passages: list[Passage] = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = clean_text(page.extract_text() or "")
            if len(page_text) < 30:
                continue
            for chunk in split_passages(page_text):
                passages.append(Passage(id=len(passages), page=page_number, text=chunk))

        if not passages:
            raise ValueError("No readable text found in the PDF.")

        embeddings: np.ndarray | None = None
        embedding_error: str | None = None
        try:
            model = _get_embedding_model()
            embeddings = model.encode(
                [passage.text for passage in passages],
                batch_size=32,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).astype(np.float32)
        except Exception as exc:  # pragma: no cover
            embedding_error = str(exc)

        if embeddings is not None:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                cache_path,
                texts=np.array([passage.text for passage in passages]),
                pages=np.array([passage.page for passage in passages], dtype=np.int32),
                embeddings=embeddings,
                page_count=np.int32(len(reader.pages)),
            )

        return cls(
            pdf_path,
            passages,
            len(reader.pages),
            embeddings,
            embedding_error,
        )

    @traceable(
        run_type="retriever",
        name="handbook_retrieval",
        process_inputs=_trace_retrieval_inputs,
        process_outputs=_trace_retrieval_outputs,
    )
    def search(
        self,
        query: str,
        top_k: int = 5,
        access_scope: str = "full",
    ) -> list[SearchResult]:
        """Return the passages most relevant to a question.

        `access_scope` is enforced before ranking so restricted passages can
        never appear in results, prompts, or source citations.
        """
        query = query.strip()
        if not query or not self.passages:
            return []

        allowed = np.fromiter(
            (
                scope_allows(access_scope, passage_access_level(passage))
                for passage in self.passages
            ),
            dtype=bool,
            count=len(self.passages),
        )
        if not allowed.any():
            return []

        keyword_scores = self._bm25.scores(query)
        keyword_peak = float(keyword_scores.max()) if keyword_scores.size else 0.0
        if keyword_peak > 0:
            keyword_scores = keyword_scores / keyword_peak

        semantic_scores: np.ndarray | None = None
        if self.embeddings is not None:
            try:
                model = _get_embedding_model()
                query_vector = model.encode(
                    [query],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )[0].astype(np.float32)
                semantic_scores = self.embeddings @ query_vector
            except Exception as exc:  # pragma: no cover
                self.embedding_error = str(exc)

        if semantic_scores is not None:
            scores = (
                DENSE_WEIGHT * semantic_scores + (1 - DENSE_WEIGHT) * keyword_scores
            )
        else:
            scores = keyword_scores

        # Make restricted passages ineligible before selecting the top-k.
        scores = np.where(allowed, scores, -np.inf)
        top_k = max(1, min(int(top_k), len(self.passages)))
        order = np.argsort(scores)[::-1][:top_k]
        return [
            SearchResult(passage=self.passages[int(index)], score=float(scores[index]))
            for index in order
            if float(scores[index]) > 0
        ]

    @staticmethod
    def clear_cache(pdf_path: Path) -> None:
        """Delete cached embeddings for a document."""
        stem = Path(pdf_path).stem
        for cache_file in CACHE_DIR.glob(f"{stem}-*.npz"):
            cache_file.unlink(missing_ok=True)
