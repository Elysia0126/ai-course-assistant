import json
from collections.abc import Iterator

from fastapi import APIRouter, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import (
    CurrentUser,
    DbSession,
    EmbedderDep,
    LLMDep,
    SessionFactoryDep,
    SettingsDep,
    get_chat_or_404,
    get_course_or_404,
)
from app.core.errors import LLMError
from app.models import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ChatSessionDetail,
    ChatSessionOut,
    SearchRequest,
    SearchResponse,
)
from app.schemas.common import SourceRef
from app.services.chat import ChatEvent, ensure_course_ready, resolve_session, run_chat
from app.services.embeddings import embedding_signature
from app.services.retrieval import HybridRetriever

router = APIRouter(tags=["chat"])


def _sse(event: ChatEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.post(
    "/courses/{course_id}/chat/stream",
    summary="Ask a question (Server-Sent Events stream)",
    description="Streams `meta`, `sources`, many `token` events, then `done` (or `error`). Each event's data is JSON.",
    response_class=StreamingResponse,
)
def chat_stream(
    course_id: str,
    payload: ChatRequest,
    db: DbSession,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
    llm: LLMDep,
    user: CurrentUser,
) -> StreamingResponse:
    # Authenticate, authorise and validate up front so failures get real HTTP status codes before the first
    # event (the session/CSRF checks already ran as dependencies).
    ensure_course_ready(db, course_id, payload.document_ids, embedding_signature(embedder), owner_id=user.id)
    resolve_session(db, course_id, payload.session_id)
    owner_id = user.id
    db.close()

    def events() -> Iterator[str]:
        for event in run_chat(
            session_factory,
            settings,
            embedder,
            llm,
            owner_id=owner_id,
            course_id=course_id,
            question=payload.question,
            session_id=payload.session_id,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
        ):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-transform stops proxies/compression middleware (incl. Next.js) from buffering the stream;
        # no-store keeps a private answer out of every cache.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/courses/{course_id}/chat", response_model=ChatResponse, summary="Ask a question (single JSON response)")
def chat(
    course_id: str,
    payload: ChatRequest,
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    embedder: EmbedderDep,
    llm: LLMDep,
    user: CurrentUser,
) -> ChatResponse:
    sources: list[dict] = []
    low_confidence = False
    for event in run_chat(
        session_factory,
        settings,
        embedder,
        llm,
        owner_id=user.id,
        course_id=course_id,
        question=payload.question,
        session_id=payload.session_id,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
    ):
        if event.event == "sources":
            sources = event.data["sources"]
            low_confidence = event.data["low_confidence"]
        elif event.event == "error":
            raise LLMError(event.data["message"], code=event.data["code"])
        elif event.event == "done":
            cited = set(event.data["cited"])
            message = ChatMessageOut(
                id=event.data["message_id"],
                role="assistant",
                content=event.data["content"],
                sources=[SourceRef(**{**s, "cited": s["index"] in cited}) for s in sources],
                meta=event.data["meta"],
                created_at=event.data["created_at"],
            )
            return ChatResponse(session_id=event.data["session_id"], message=message, low_confidence=low_confidence)
    raise LLMError("The answer stream ended unexpectedly.")


@router.get("/courses/{course_id}/chat/sessions", response_model=list[ChatSessionOut], summary="List chat sessions")
def list_sessions(course_id: str, db: DbSession, user: CurrentUser) -> list[ChatSessionOut]:
    get_course_or_404(db, course_id, user)
    rows = db.execute(
        select(ChatSession, func.count(ChatMessage.id))
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.course_id == course_id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    ).all()
    out = []
    for session, count in rows:
        item = ChatSessionOut.model_validate(session)
        item.message_count = count
        out.append(item)
    return out


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetail, summary="Get a chat transcript")
def get_session(session_id: str, db: DbSession, user: CurrentUser) -> ChatSessionDetail:
    chat = get_chat_or_404(db, session_id, user)
    detail = ChatSessionDetail.model_validate(chat)
    detail.message_count = len(chat.messages)
    return detail


@router.delete("/chat/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a chat")
def delete_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    chat = get_chat_or_404(db, session_id, user)
    db.delete(chat)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/courses/{course_id}/search",
    response_model=SearchResponse,
    tags=["search"],
    summary="Hybrid search over course materials (retrieval inspector)",
)
def search(
    course_id: str,
    payload: SearchRequest,
    db: DbSession,
    settings: SettingsDep,
    embedder: EmbedderDep,
    user: CurrentUser,
) -> SearchResponse:
    ensure_course_ready(db, course_id, payload.document_ids, embedding_signature(embedder), owner_id=user.id)
    result = HybridRetriever(db, settings, embedder).search(
        course_id, payload.query, top_k=payload.top_k, document_ids=payload.document_ids, mode=payload.mode
    )
    return SearchResponse(
        results=[SourceRef(**chunk.to_source(i)) for i, chunk in enumerate(result.chunks, start=1)],
        low_confidence=result.low_confidence,
        best_vector_score=round(result.best_vector_score, 4),
    )
