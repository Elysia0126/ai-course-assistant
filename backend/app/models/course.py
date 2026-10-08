from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text, event
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
    # The single owner; documents, chunks, chats, quizzes and decks inherit access through the course.
    # Nullable only as a migration state: courses created before accounts existed have no owner, are visible
    # to nobody, and wait for `python -m app.cli assign-course`. New rows must have an owner (checked below,
    # and on PostgreSQL by the ck_courses_owner_required constraint).
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
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


@event.listens_for(Course, "before_insert")
@event.listens_for(Course, "before_update")
def _require_owner(_mapper: Any, _connection: Any, course: Course) -> None:
    if course.owner_id is None:
        raise ValueError("A course must have an owner.")
