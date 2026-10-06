from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel

QuestionTypeLiteral = Literal["mcq", "true_false", "short_answer"]


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(default=5, ge=1, le=20)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    question_types: list[QuestionTypeLiteral] = Field(
        default_factory=lambda: ["mcq", "true_false", "short_answer"], min_length=1
    )
    document_ids: list[str] | None = None
    topic: str | None = Field(default=None, max_length=200)

    @field_validator("question_types")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("topic")
    @classmethod
    def _blank_topic(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("document_ids")
    @classmethod
    def _empty_docs(cls, value: list[str] | None) -> list[str] | None:
        return value or None


class QuizQuestionOut(ORMModel):
    """A question as shown to the student — deliberately without the answer."""

    id: str
    position: int
    question_type: str
    prompt: str
    options: list[str]
    source: dict[str, Any] | None


class QuizSummary(ORMModel):
    id: str
    course_id: str
    title: str
    difficulty: str
    topic: str | None
    generator: str
    created_at: datetime
    question_count: int = 0
    attempt_count: int = 0
    best_score: float | None = None


class QuizDetail(QuizSummary):
    questions: list[QuizQuestionOut]


class AttemptRequest(BaseModel):
    answers: dict[str, str] = Field(description="question_id → answer (option text, True/False, or free text)")


class QuestionResult(BaseModel):
    question_id: str
    given: str
    correct: bool
    score: float
    correct_answer: str
    explanation: str
    feedback: str
    source: dict[str, Any] | None


class AttemptOut(ORMModel):
    id: str
    quiz_id: str
    score: float
    correct_count: int
    total: int
    results: list[QuestionResult]
    created_at: datetime
