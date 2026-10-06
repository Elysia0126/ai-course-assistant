from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class DeckGenerateRequest(BaseModel):
    num_cards: int = Field(default=12, ge=1, le=40)
    document_ids: list[str] | None = None
    topic: str | None = Field(default=None, max_length=200)

    @field_validator("topic")
    @classmethod
    def _blank_topic(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("document_ids")
    @classmethod
    def _empty_docs(cls, value: list[str] | None) -> list[str] | None:
        return value or None


class FlashcardOut(ORMModel):
    id: str
    deck_id: str
    position: int
    front: str
    back: str
    source: dict[str, Any] | None
    ease_factor: float
    interval_days: float
    repetitions: int
    lapses: int
    review_count: int
    due_at: datetime
    last_reviewed_at: datetime | None


class DeckSummary(ORMModel):
    id: str
    course_id: str
    title: str
    topic: str | None
    generator: str
    created_at: datetime
    card_count: int = 0
    due_count: int = 0
    reviewed_count: int = 0


class DeckDetail(DeckSummary):
    cards: list[FlashcardOut]


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]


class StudySession(BaseModel):
    deck: DeckSummary
    cards: list[FlashcardOut]
