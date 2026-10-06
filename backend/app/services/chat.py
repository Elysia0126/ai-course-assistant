"""Retrieval-augmented question answering with persisted chat sessions and validated citations."""

import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, NoMaterialsError, NotFoundError
from app.db.session import session_scope
from app.db.types import utcnow
from app.models import ChatMessage, ChatSession, Chunk, Course, Document, DocumentStatus
from app.services.embeddings import EmbeddingProvider
from app.services.llm import ChatTurn, LLMBackend
from app.services.retrieval import HybridRetriever
from app.services.text_utils import truncate

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 6
HISTORY_CHARS = 2000
_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*)\]")


def extract_citations(answer: str, n_sources: int) -> list[int]:
    """Citation numbers used in the answer, in order of first appearance, ignoring out-of-range ones."""
    cited: list[int] = []
    for match in _CITATION_RE.finditer(answer):
        for part in re.split(r"[,，]", match.group(1)):
            number = int(part.strip())
            if 1 <= number <= n_sources and number not in cited:
                cited.append(number)
    return cited


@dataclass
class ChatEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)


def ensure_course_ready(session: Session, course_id: str, document_ids: list[str] | None = None) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found.")
    query = (
        select(func.count(Chunk.id))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.course_id == course_id, Document.status == DocumentStatus.READY)
    )
    if document_ids:
        query = query.where(Chunk.document_id.in_(document_ids))
    if not session.scalar(query):
        raise NoMaterialsError(
            "There are no processed materials to search yet. Upload lecture notes or slides first."
            if not document_ids
            else "None of the selected documents are ready yet."
        )
    return course


def resolve_session(session: Session, course_id: str, session_id: str | None) -> ChatSession | None:
    if session_id is None:
        return None
    chat = session.get(ChatSession, session_id)
    if chat is None or chat.course_id != course_id:
        raise NotFoundError("Chat session not found.")
    return chat


def run_chat(
    session_factory: sessionmaker[Session],
    settings: Settings,
    embedder: EmbeddingProvider,
    llm: LLMBackend,
    *,
    course_id: str,
    question: str,
    session_id: str | None,
    document_ids: list[str] | None,
    top_k: int | None,
) -> Iterator[ChatEvent]:
    """Stream the whole answer lifecycle as events: meta → sources → token* → done (or error)."""
    started = time.perf_counter()
    with session_scope(session_factory) as db:
        course = ensure_course_ready(db, course_id, document_ids)
        chat = resolve_session(db, course_id, session_id)

        history: list[ChatTurn] = []
        if chat is None:
            chat = ChatSession(course_id=course_id, title=truncate(question, 80))
            db.add(chat)
            db.flush()
        else:
            previous = db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_MESSAGES)
            ).all()
            history = [ChatTurn(m.role, truncate(m.content, HISTORY_CHARS)) for m in reversed(previous)]  # type: ignore[arg-type]
            # The API expects the conversation to start with a user turn.
            while history and history[0].role != "user":
                history.pop(0)

        user_message = ChatMessage(session_id=chat.id, role="user", content=question, sources=[], meta={})
        db.add(user_message)
        chat.updated_at = utcnow()
        db.commit()
        yield ChatEvent("meta", {"session_id": chat.id, "user_message_id": user_message.id, "title": chat.title})

        retrieval = HybridRetriever(db, settings, embedder).search(
            course_id, question, top_k=top_k, document_ids=document_ids
        )
        sources = [chunk.to_source(i) for i, chunk in enumerate(retrieval.chunks, start=1)]
        yield ChatEvent("sources", {"sources": sources, "low_confidence": retrieval.low_confidence})

        parts: list[str] = []
        try:
            for delta in llm.stream_answer(
                course_name=course.name, question=question, sources=retrieval.chunks, history=history
            ):
                parts.append(delta)
                yield ChatEvent("token", {"text": delta})
        except AppError as exc:
            logger.warning("Answer generation failed: %s", exc.message)
            yield ChatEvent("error", {"code": exc.code, "message": exc.message})
            return
        except Exception:
            logger.exception("Answer generation crashed")
            yield ChatEvent("error", {"code": "internal_error", "message": "The answer could not be generated."})
            return

        answer = "".join(parts).strip()
        cited = extract_citations(answer, len(sources))
        for source in sources:
            source["cited"] = source["index"] in cited

        meta = {
            "provider": llm.name,
            "model": llm.model,
            "low_confidence": retrieval.low_confidence,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        assistant_message = ChatMessage(
            session_id=chat.id, role="assistant", content=answer, sources=sources, meta=meta
        )
        db.add(assistant_message)
        db.commit()
        yield ChatEvent(
            "done",
            {
                "session_id": chat.id,
                "message_id": assistant_message.id,
                "content": answer,
                "cited": cited,
                "meta": meta,
                "created_at": assistant_message.created_at.isoformat(),
            },
        )
