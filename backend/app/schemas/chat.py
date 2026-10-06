from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, SourceRef


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    document_ids: list[str] | None = Field(default=None, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank")
        return value

    @field_validator("document_ids")
    @classmethod
    def _empty_to_none(cls, value: list[str] | None) -> list[str] | None:
        return value or None


class ChatMessageOut(ORMModel):
    id: str
    role: str
    content: str
    sources: list[SourceRef]
    meta: dict[str, Any]
    created_at: datetime


class ChatResponse(BaseModel):
    session_id: str
    message: ChatMessageOut
    low_confidence: bool


class ChatSessionOut(ORMModel):
    id: str
    course_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=30)
    document_ids: list[str] | None = None


class SearchResponse(BaseModel):
    results: list[SourceRef]
    low_confidence: bool
    best_vector_score: float
