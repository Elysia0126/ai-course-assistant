from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, UTCDateTime, new_id, utcnow

if TYPE_CHECKING:
    from app.models.course import Course


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    difficulty: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(200))
    document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    generator: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    course: Mapped["Course"] = relationship(back_populates="quizzes")
    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", passive_deletes=True, order_by="QuizQuestion.position"
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", passive_deletes=True, order_by="QuizAttempt.created_at"
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSONType, default=list)
    correct_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), index=True)
    answers: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    score: Mapped[float] = mapped_column(Float)
    correct_count: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    quiz: Mapped[Quiz] = relationship(back_populates="attempts")
