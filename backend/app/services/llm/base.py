"""Task-level interface every generation backend implements.

Keeping the interface at the level of *tasks* (answer, quiz, flashcards) rather than raw completions
lets the offline backend implement the same contract with heuristics, so the whole app — and the test
suite — runs without any API key.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

from app.services.llm import prompts
from app.services.retrieval import RetrievedChunk

QuestionType = Literal["mcq", "true_false", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]


class QuestionDraft(BaseModel):
    type: QuestionType
    question: str
    options: list[str]
    answer: str
    explanation: str
    source_id: int


class QuizDraft(BaseModel):
    title: str
    questions: list[QuestionDraft]


class CardDraft(BaseModel):
    front: str
    back: str
    source_id: int


class DeckDraft(BaseModel):
    title: str
    cards: list[CardDraft]


@dataclass
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


class LLMBackend(Protocol):
    name: str
    model: str

    def stream_answer(
        self, *, course_name: str, question: str, sources: list[RetrievedChunk], history: list[ChatTurn]
    ) -> Iterator[str]: ...

    def generate_quiz(
        self,
        *,
        course_name: str,
        sources: list[RetrievedChunk],
        num_questions: int,
        difficulty: Difficulty,
        question_types: list[QuestionType],
        topic: str | None,
    ) -> QuizDraft: ...

    def generate_flashcards(
        self, *, course_name: str, sources: list[RetrievedChunk], num_cards: int, topic: str | None
    ) -> DeckDraft: ...


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class PromptedBackend(ABC):
    """Shared prompt construction for real LLM providers; subclasses supply two primitives."""

    name: str
    model: str
    answer_max_tokens = 16000
    structured_max_tokens = 16000

    @abstractmethod
    def _stream_text(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> Iterator[str]: ...

    @abstractmethod
    def _structured(self, system: str, user: str, schema: type[SchemaT], max_tokens: int) -> SchemaT: ...

    def stream_answer(
        self, *, course_name: str, question: str, sources: list[RetrievedChunk], history: list[ChatTurn]
    ) -> Iterator[str]:
        messages = [{"role": turn.role, "content": turn.content} for turn in history]
        messages.append({"role": "user", "content": prompts.answer_user_message(question, sources)})
        yield from self._stream_text(prompts.answer_system_prompt(course_name), messages, self.answer_max_tokens)

    def generate_quiz(
        self,
        *,
        course_name: str,
        sources: list[RetrievedChunk],
        num_questions: int,
        difficulty: Difficulty,
        question_types: list[QuestionType],
        topic: str | None,
    ) -> QuizDraft:
        return self._structured(
            prompts.quiz_system_prompt(course_name),
            prompts.quiz_user_message(sources, num_questions, difficulty, question_types, topic),
            QuizDraft,
            self.structured_max_tokens,
        )

    def generate_flashcards(
        self, *, course_name: str, sources: list[RetrievedChunk], num_cards: int, topic: str | None
    ) -> DeckDraft:
        return self._structured(
            prompts.flashcards_system_prompt(course_name),
            prompts.flashcards_user_message(sources, num_cards, topic),
            DeckDraft,
            self.structured_max_tokens,
        )
