"""Document ingestion pipeline: parse → chunk → embed → index.

Runs as a FastAPI background task. Status moves pending → processing → ready | failed, and the old
chunks of a re-processed document are swapped out in the same transaction that marks it ready, so
search never sees a half-indexed document.
"""

import logging
import time
from pathlib import Path

from sqlalchemy import delete, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import session_scope
from app.db.types import utcnow
from app.models import Chunk, Document, DocumentStatus
from app.services.chunking import chunk_document
from app.services.embeddings import EmbeddingProvider
from app.services.parsing import parse_document

logger = logging.getLogger(__name__)


def embedding_text(filename: str, section: str | None, content: str) -> str:
    """Contextual chunk header: prefixing the document and section title improves retrieval of terse chunks."""
    title = Path(filename).stem.replace("_", " ")
    header = f"{title} — {section}" if section else title
    return f"{header}\n{content}"


def ingest_document(
    session_factory: sessionmaker[Session],
    settings: Settings,
    embedder: EmbeddingProvider,
    document_id: str,
) -> None:
    started = time.perf_counter()
    with session_scope(session_factory) as session:
        document = session.get(Document, document_id)
        if document is None:
            logger.warning("Ingestion skipped: document %s no longer exists", document_id)
            return
        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        session.commit()

        try:
            parsed = parse_document(Path(document.storage_path), document.file_type)
            drafts = chunk_document(parsed, settings.chunk_size, settings.chunk_overlap)
            if not drafts:
                raise AppError("The document did not contain enough text to index.", code="document_parsing_failed")

            vectors = embedder.embed_documents(
                [embedding_text(document.filename, d.section, d.content) for d in drafts]
            )

            session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            session.add_all(
                Chunk(
                    document_id=document.id,
                    course_id=document.course_id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    page_number=draft.page_number,
                    section=(draft.section or None) and draft.section[:300],
                    char_count=len(draft.content),
                    embedding=vector,
                )
                for draft, vector in zip(drafts, vectors, strict=True)
            )
            document.page_count = parsed.page_count
            document.chunk_count = len(drafts)
            document.status = DocumentStatus.READY
            document.processed_at = utcnow()
            session.commit()
            logger.info("Indexed %s: %d chunks in %.2fs", document.filename, len(drafts), time.perf_counter() - started)
        except Exception as exc:
            session.rollback()
            message = exc.message if isinstance(exc, AppError) else "Unexpected error while processing the file."
            if not isinstance(exc, AppError):
                logger.exception("Ingestion failed for %s", document_id)
            else:
                logger.warning("Ingestion failed for %s: %s", document_id, message)
            session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.FAILED, error_message=message, processed_at=utcnow())
            )
            session.commit()


def fail_interrupted_documents(session_factory: sessionmaker[Session]) -> int:
    """Documents left mid-processing by a crash/restart are marked failed so users can retry them."""
    with session_scope(session_factory) as session:
        result = session.execute(
            update(Document)
            .where(Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]))
            .values(status=DocumentStatus.FAILED, error_message="Processing was interrupted. Click retry.")
        )
        session.commit()
        return result.rowcount or 0
