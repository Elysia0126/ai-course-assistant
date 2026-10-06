from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, new_id, utcnow

if TYPE_CHECKING:
    from app.models.chat import ChatSession
    from app.models.document import Document
    from app.models.flashcard import FlashcardDeck
    from app.models.quiz import Quiz


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(50))
    term: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(20), default="indigo")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )
    quizzes: Mapped[list["Quiz"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )
    flashcard_decks: Mapped[list["FlashcardDeck"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )
