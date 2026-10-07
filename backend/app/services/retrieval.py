"""Hybrid retrieval: dense vectors + keyword search, fused with Reciprocal Rank Fusion.

PostgreSQL path  – pgvector HNSW cosine search + a stored ``tsvector`` with a GIN index.
Portable path    – numpy cosine similarity + an in-process BM25 (used by SQLite in tests/dev).

Dense retrieval is good at paraphrases ("how do I pick a step size" ~ "learning rate"), keyword
retrieval is good at exact jargon, symbols and names ("Adam", "L2", "Bellman"); RRF combines the two
rankings without having to calibrate their very different score scales.
"""

import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError
from app.models import Chunk, Document, DocumentStatus
from app.services.embeddings import EmbeddingProvider, embedding_signature
from app.services.text_utils import cjk_bigrams, tokenize, truncate

SearchMode = Literal["hybrid", "vector", "keyword"]
# One entry of a tsvector's text form: 'lexeme':3,17B  (quotes inside lexemes are doubled).
_TSV_ENTRY = re.compile(r"'((?:[^']|'')+)':([0-9A-D,]+)")


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    file_type: str
    content: str
    page_number: int | None
    section: str | None
    chunk_index: int
    score: float = 0.0
    vector_score: float | None = None
    keyword_score: float | None = None

    @property
    def location(self) -> str | None:
        if self.page_number is not None:
            return f"slide {self.page_number}" if self.file_type == "pptx" else f"page {self.page_number}"
        return self.section

    def to_source(self, index: int | None = None, *, cited: bool = False, snippet_chars: int = 320) -> dict[str, Any]:
        return {
            "index": index,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "page_number": self.page_number,
            "section": self.section,
            "location": self.location,
            "snippet": truncate(self.content, snippet_chars),
            "score": round(self.score, 4),
            "vector_score": None if self.vector_score is None else round(self.vector_score, 4),
            "keyword_score": None if self.keyword_score is None else round(self.keyword_score, 4),
            "cited": cited,
        }


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    best_vector_score: float = 0.0
    low_confidence: bool = True


class BM25:
    """Okapi BM25 over pre-tokenised documents."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.term_freqs = [Counter(doc) for doc in corpus]
        self.doc_len = np.array([len(doc) for doc in corpus], dtype=np.float32)
        self.avgdl = float(self.doc_len.mean()) if len(corpus) else 0.0
        doc_freq: Counter[str] = Counter()
        for doc in corpus:
            doc_freq.update(set(doc))
        n = len(corpus)
        self.idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in doc_freq.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.term_freqs), dtype=np.float32)
        if not self.avgdl:
            return scores
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freqs in enumerate(self.term_freqs):
                tf = freqs.get(term)
                if tf:
                    norm = self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                    scores[i] += idf * tf * (self.k1 + 1) / (tf + norm)
        return scores


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            fused[item_id] += 1.0 / (k + rank)
    return dict(fused)


def _keyword_tokens(text_: str) -> list[str]:
    tokens = tokenize(text_)
    return tokens + cjk_bigrams(tokens)


def check_index_current(session: Session, course_id: str, document_ids: list[str] | None, signature: str) -> None:
    """Refuse to search vectors produced by a different embedding model than the one configured now."""
    stmt = select(func.count(Document.id)).where(
        Document.course_id == course_id,
        Document.status == DocumentStatus.READY,
        Document.embedding_signature.is_distinct_from(signature),
    )
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    stale = session.scalar(stmt)
    if stale:
        raise ConflictError(
            f"{stale} document(s) were indexed with a different embedding model than the one now configured. "
            "Re-index the course materials (Materials → Re-index all) before searching.",
            code="index_outdated",
        )


class HybridRetriever:
    def __init__(self, session: Session, settings: Settings, embedder: EmbeddingProvider):
        self.session = session
        self.settings = settings
        self.embedder = embedder
        self.use_pg = session.get_bind().dialect.name == "postgresql"

    def search(
        self,
        course_id: str,
        query: str,
        *,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        mode: SearchMode = "hybrid",
    ) -> RetrievalResult:
        """Rank chunks for a query. ``mode`` exists for ablations: vector-only, keyword-only or fused."""
        check_index_current(self.session, course_id, document_ids, embedding_signature(self.embedder))
        top_k = top_k or self.settings.retrieval_top_k
        n_candidates = max(self.settings.retrieval_candidates, top_k)
        query_vec = self.embedder.embed_query(query)

        if self.use_pg:
            vector_hits = self._vector_search_pg(course_id, query_vec, n_candidates, document_ids)
            keyword_hits = self._keyword_search_pg(course_id, query, n_candidates, document_ids)
            pool: dict[str, RetrievedChunk] = {}
        else:
            pool, vector_hits, keyword_hits = self._search_portable(
                course_id, query, query_vec, n_candidates, document_ids
            )

        rankings = {
            "hybrid": [[cid for cid, _ in vector_hits], [cid for cid, _ in keyword_hits]],
            "vector": [[cid for cid, _ in vector_hits]],
            "keyword": [[cid for cid, _ in keyword_hits]],
        }[mode]
        fused = reciprocal_rank_fusion(rankings, k=self.settings.rrf_k)
        ranked_ids = sorted(fused, key=fused.__getitem__, reverse=True)[:top_k]
        vector_scores = dict(vector_hits)
        keyword_scores = dict(keyword_hits)

        if self.use_pg:
            pool = self._load_chunks(ranked_ids)

        chunks: list[RetrievedChunk] = []
        for cid in ranked_ids:
            chunk = pool.get(cid)
            if chunk is None:
                continue
            chunk.score = fused[cid]
            chunk.vector_score = vector_scores.get(cid)
            chunk.keyword_score = keyword_scores.get(cid)
            chunks.append(chunk)

        best = max((score for _, score in vector_hits), default=0.0)
        return RetrievalResult(chunks=chunks, best_vector_score=best, low_confidence=best < self.embedder.min_relevance)

    # --- PostgreSQL ---------------------------------------------------------------

    def _filters(self, document_ids: list[str] | None) -> str:
        return " AND c.document_id IN :document_ids" if document_ids else ""

    def _bind(self, stmt: Any, document_ids: list[str] | None) -> Any:
        return stmt.bindparams(bindparam("document_ids", expanding=True)) if document_ids else stmt

    def _vector_search_pg(
        self, course_id: str, query_vec: np.ndarray, limit: int, document_ids: list[str] | None
    ) -> list[tuple[str, float]]:
        # A wider HNSW candidate list keeps recall high when the course filter discards neighbours.
        self.session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        stmt = text(
            "SELECT c.id, 1 - (c.embedding <=> CAST(:qvec AS vector)) AS score "
            "FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE c.course_id = :course_id AND d.status = 'ready' AND c.embedding IS NOT NULL"
            f"{self._filters(document_ids)} "
            "ORDER BY c.embedding <=> CAST(:qvec AS vector) LIMIT :limit"
        )
        params: dict[str, Any] = {
            "qvec": "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]",
            "course_id": course_id,
            "limit": limit,
        }
        if document_ids:
            params["document_ids"] = document_ids
        rows = self.session.execute(self._bind(stmt, document_ids), params).all()
        return [(row[0], float(row[1])) for row in rows]

    def _keyword_search_pg(
        self, course_id: str, query: str, limit: int, document_ids: list[str] | None
    ) -> list[tuple[str, float]]:
        """Okapi BM25 inside Postgres' full-text machinery.

        ``ts_rank_cd`` has no IDF, so ubiquitous course words ("gradient", "training") swamp the rare
        term a question is really about. Instead: (1) normalise the question with the same 'english'
        configuration as the stored tsvector, (2) pull candidates through the GIN index with an OR query,
        (3) get each term's document frequency with one index lookup per term, and (4) score candidates
        with BM25 using term frequencies parsed from their tsvectors.
        """
        lexemes: list[str] = list(
            self.session.scalars(
                text("SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', :q)))"), {"q": query}
            )
        )
        if not lexemes:
            return []

        scope = f"c.course_id = :course_id AND d.status = 'ready'{self._filters(document_ids)}"
        base: dict[str, Any] = {"course_id": course_id}
        if document_ids:
            base["document_ids"] = document_ids
        # Lexemes are already normalised, so build the tsquery directly (no second stemming pass).
        tsquery = " | ".join("'" + lx.replace("\\", "\\\\").replace("'", "''") + "'" for lx in lexemes)

        candidates = self.session.execute(
            self._bind(
                text(
                    "SELECT c.id, CAST(c.content_tsv AS text) FROM chunks c "
                    "JOIN documents d ON d.id = c.document_id "
                    f"WHERE {scope} AND c.content_tsv @@ CAST(:tsq AS tsquery) "
                    "ORDER BY ts_rank_cd(c.content_tsv, CAST(:tsq AS tsquery)) DESC LIMIT :pool"
                ),
                document_ids,
            ),
            {**base, "tsq": tsquery, "pool": max(limit * 5, 200)},
        ).all()
        if not candidates:
            return []

        n_docs, avgdl = self.session.execute(
            self._bind(
                text(
                    "SELECT count(*), coalesce(avg(length(c.content_tsv)), 0) FROM chunks c "
                    f"JOIN documents d ON d.id = c.document_id WHERE {scope}"
                ),
                document_ids,
            ),
            base,
        ).one()
        doc_freq = dict(
            self.session.execute(
                self._bind(
                    text(
                        "SELECT x, (SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                        f"WHERE {scope} AND c.content_tsv @@ CAST(quote_literal(x) AS tsquery)) "
                        "FROM unnest(CAST(:lexemes AS text[])) AS x"
                    ),
                    document_ids,
                ),
                {**base, "lexemes": lexemes},
            ).all()
        )

        k1, b = 1.5, 0.75
        avgdl = float(avgdl) or 1.0
        idf = {lx: math.log(1 + (n_docs - df + 0.5) / (df + 0.5)) for lx, df in doc_freq.items()}
        scored: list[tuple[str, float]] = []
        for chunk_id, tsv in candidates:
            freqs = {m.group(1).replace("''", "'"): m.group(2).count(",") + 1 for m in _TSV_ENTRY.finditer(tsv)}
            length = len(freqs)
            score = 0.0
            for lx in lexemes:
                tf = freqs.get(lx)
                if tf:
                    score += idf.get(lx, 0.0) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avgdl))
            if score > 0:
                scored.append((chunk_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _load_chunks(self, chunk_ids: list[str]) -> dict[str, RetrievedChunk]:
        if not chunk_ids:
            return {}
        rows = self.session.execute(
            select(
                Chunk.id,
                Chunk.document_id,
                Document.filename,
                Document.file_type,
                Chunk.content,
                Chunk.page_number,
                Chunk.section,
                Chunk.chunk_index,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(chunk_ids))
        ).all()
        return {row[0]: RetrievedChunk(*row) for row in rows}

    # --- Portable (SQLite / any SQL) -----------------------------------------------

    def _search_portable(
        self,
        course_id: str,
        query: str,
        query_vec: np.ndarray,
        limit: int,
        document_ids: list[str] | None,
    ) -> tuple[dict[str, RetrievedChunk], list[tuple[str, float]], list[tuple[str, float]]]:
        stmt = (
            select(
                Chunk.id,
                Chunk.document_id,
                Document.filename,
                Document.file_type,
                Chunk.content,
                Chunk.page_number,
                Chunk.section,
                Chunk.chunk_index,
                Chunk.embedding,
            )
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.course_id == course_id, Document.status == DocumentStatus.READY)
        )
        if document_ids:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        rows = self.session.execute(stmt).all()
        if not rows:
            return {}, [], []

        pool = {row[0]: RetrievedChunk(*row[:8]) for row in rows}
        ids = [row[0] for row in rows]

        vector_hits: list[tuple[str, float]] = []
        with_vectors = [(row[0], row[8]) for row in rows if row[8] is not None]
        if with_vectors:
            matrix = np.stack([vec for _, vec in with_vectors])
            sims = matrix @ query_vec
            order = np.argsort(-sims)[:limit]
            vector_hits = [(with_vectors[i][0], float(sims[i])) for i in order]

        bm25 = BM25([_keyword_tokens(f"{row[6] or ''} {row[4]}") for row in rows])
        kw_scores = bm25.scores(_keyword_tokens(query))
        order = np.argsort(-kw_scores)[:limit]
        keyword_hits = [(ids[i], float(kw_scores[i])) for i in order if kw_scores[i] > 0]
        return pool, vector_hits, keyword_hits


def sample_study_chunks(
    session: Session,
    course_id: str,
    *,
    document_ids: list[str] | None,
    limit: int,
    max_chars: int,
    seed: int | None = None,
) -> list[RetrievedChunk]:
    """Pick a spread of substantive chunks across the selected documents (for quizzes/flashcards).

    Chunks are taken at evenly spaced positions (with a random offset, so regenerating gives fresh
    material) and interleaved round-robin across documents so every lecture is represented.
    """
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Document.file_type,
            Chunk.content,
            Chunk.page_number,
            Chunk.section,
            Chunk.chunk_index,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.course_id == course_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at, Chunk.chunk_index)
    )
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = [RetrievedChunk(*row) for row in session.execute(stmt).all()]
    if not rows:
        return []

    rng = random.Random(seed)
    by_doc: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in rows:
        by_doc[chunk.document_id].append(chunk)

    per_doc_take = max(1, math.ceil(limit / len(by_doc)))
    picks_per_doc: list[list[RetrievedChunk]] = []
    for chunks in by_doc.values():
        substantive = [c for c in chunks if len(c.content) >= 200] or chunks
        take = min(per_doc_take, len(substantive))
        step = len(substantive) / take
        offset = rng.random() * step
        picks_per_doc.append([substantive[min(int(offset + i * step), len(substantive) - 1)] for i in range(take)])

    selected: list[RetrievedChunk] = []
    total_chars = 0
    for round_ in range(per_doc_take):
        for picks in picks_per_doc:
            if round_ < len(picks) and len(selected) < limit:
                chunk = picks[round_]
                if selected and total_chars + len(chunk.content) > max_chars:
                    continue
                selected.append(chunk)
                total_chars += len(chunk.content)
    return selected
