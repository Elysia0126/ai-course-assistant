from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, UTCDateTime, new_id, utcnow

if TYPE_CHECKING:
    from app.models.course import Course


class FlashcardDeck(Base):
    __tablename__ = "flashcard_decks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str | None] = mapped_column(String(200))
    document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    generator: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    course: Mapped["Course"] = relationship(back_populates="flashcard_decks")
    cards: Mapped[list["Flashcard"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", passive_deletes=True, order_by="Flashcard.position"
    )


class Flashcard(Base):
    """A card plus its SM-2 spaced-repetition state."""

    __tablename__ = "flashcards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deck_id: Mapped[str] = mapped_column(ForeignKey("flashcard_decks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    deck: Mapped[FlashcardDeck] = relationship(back_populates="cards")
