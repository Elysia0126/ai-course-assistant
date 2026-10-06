"""Flashcard deck generation and spaced-repetition reviews."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, LLMError
from app.db.types import utcnow
from app.models import Course, Flashcard, FlashcardDeck
from app.services.embeddings import EmbeddingProvider
from app.services.llm import LLMBackend
from app.services.quizzes import select_sources, source_snapshot
from app.services.srs import Rating, ReviewState, schedule


def create_deck(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    llm: LLMBackend,
    course: Course,
    *,
    num_cards: int,
    document_ids: list[str] | None,
    topic: str | None,
) -> FlashcardDeck:
    sources = select_sources(
        session, settings, embedder, course.id, document_ids=document_ids, topic=topic, count=num_cards
    )
    draft = llm.generate_flashcards(course_name=course.name, sources=sources, num_cards=num_cards, topic=topic)

    cards: list[Flashcard] = []
    seen: set[str] = set()
    now = utcnow()
    for item in draft.cards:
        front, back = item.front.strip(), item.back.strip()
        if not front or not back or front.lower() in seen:
            continue
        seen.add(front.lower())
        source = sources[item.source_id - 1] if 1 <= item.source_id <= len(sources) else None
        cards.append(Flashcard(position=len(cards), front=front, back=back, source=source_snapshot(source), due_at=now))
        if len(cards) == num_cards:
            break

    if not cards:
        if llm.name == "offline":
            raise AppError(
                "Not enough text in the selected materials to build flashcards offline.", code="generation_failed"
            )
        raise LLMError("The model did not return any valid flashcards. Please try again.")

    deck = FlashcardDeck(
        course_id=course.id,
        title=(draft.title.strip() or "Flashcards")[:200],
        topic=topic,
        document_ids=document_ids or [],
        generator=f"{llm.name}:{llm.model}"[:80],
        cards=cards,
    )
    session.add(deck)
    session.commit()
    return deck


def due_cards(session: Session, deck_id: str, *, now: datetime | None = None, limit: int = 50) -> list[Flashcard]:
    now = now or utcnow()
    return list(
        session.scalars(
            select(Flashcard)
            .where(Flashcard.deck_id == deck_id, Flashcard.due_at <= now)
            .order_by(Flashcard.due_at, Flashcard.position)
            .limit(limit)
        )
    )


def review_card(session: Session, card: Flashcard, rating: Rating, *, now: datetime | None = None) -> Flashcard:
    now = now or utcnow()
    outcome = schedule(ReviewState(card.ease_factor, card.interval_days, card.repetitions, card.lapses), rating, now)
    card.ease_factor = outcome.state.ease_factor
    card.interval_days = outcome.state.interval_days
    card.repetitions = outcome.state.repetitions
    card.lapses = outcome.state.lapses
    card.due_at = outcome.due_at
    card.last_reviewed_at = now
    card.review_count += 1
    session.commit()
    return card
