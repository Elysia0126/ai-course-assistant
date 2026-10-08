from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CurrentUser,
    DbSession,
    EmbedderDep,
    LLMDep,
    SettingsDep,
    get_card_or_404,
    get_course_or_404,
    get_deck_or_404,
)
from app.db.types import utcnow
from app.models import Flashcard, FlashcardDeck
from app.schemas.flashcard import (
    DeckDetail,
    DeckGenerateRequest,
    DeckSummary,
    FlashcardOut,
    ReviewRequest,
    StudySession,
)
from app.services.access import ensure_documents_in_course
from app.services.flashcards import create_deck, due_cards, review_card

router = APIRouter(tags=["flashcards"])


def _summary(deck: FlashcardDeck) -> DeckSummary:
    now = utcnow()
    return DeckSummary.model_validate(deck).model_copy(
        update={
            "card_count": len(deck.cards),
            "due_count": sum(1 for c in deck.cards if c.due_at <= now),
            "reviewed_count": sum(1 for c in deck.cards if c.review_count > 0),
        }
    )


@router.post(
    "/courses/{course_id}/decks",
    response_model=DeckDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a flashcard deck from course materials",
)
def generate_deck(
    course_id: str,
    payload: DeckGenerateRequest,
    db: DbSession,
    settings: SettingsDep,
    embedder: EmbedderDep,
    llm: LLMDep,
    user: CurrentUser,
) -> DeckDetail:
    course = get_course_or_404(db, course_id, user)
    ensure_documents_in_course(db, course.id, payload.document_ids)
    deck = create_deck(
        db,
        settings,
        embedder,
        llm,
        course,
        num_cards=payload.num_cards,
        document_ids=payload.document_ids,
        topic=payload.topic,
    )
    return _detail(deck)


def _detail(deck: FlashcardDeck) -> DeckDetail:
    return DeckDetail(**_summary(deck).model_dump(), cards=[FlashcardOut.model_validate(c) for c in deck.cards])


@router.get("/courses/{course_id}/decks", response_model=list[DeckSummary], summary="List flashcard decks")
def list_decks(course_id: str, db: DbSession, user: CurrentUser) -> list[DeckSummary]:
    get_course_or_404(db, course_id, user)
    decks = db.scalars(
        select(FlashcardDeck)
        .where(FlashcardDeck.course_id == course_id)
        .options(selectinload(FlashcardDeck.cards))
        .order_by(FlashcardDeck.created_at.desc())
    ).all()
    return [_summary(d) for d in decks]


@router.get("/decks/{deck_id}", response_model=DeckDetail, summary="Get a deck with all cards")
def get_deck(deck_id: str, db: DbSession, user: CurrentUser) -> DeckDetail:
    return _detail(get_deck_or_404(db, deck_id, user))


@router.get("/decks/{deck_id}/study", response_model=StudySession, summary="Cards due for review now")
def study(deck_id: str, db: DbSession, user: CurrentUser, limit: int = Query(default=50, ge=1, le=200)) -> StudySession:
    deck = get_deck_or_404(db, deck_id, user)
    cards = due_cards(db, deck.id, limit=limit)
    return StudySession(deck=_summary(deck), cards=[FlashcardOut.model_validate(c) for c in cards])


@router.post("/flashcards/{card_id}/review", response_model=FlashcardOut, summary="Record a review (SM-2)")
def review(card_id: str, payload: ReviewRequest, db: DbSession, user: CurrentUser) -> Flashcard:
    return review_card(db, get_card_or_404(db, card_id, user), payload.rating)


@router.post("/decks/{deck_id}/reset", response_model=DeckSummary, summary="Reset review progress for a deck")
def reset_deck(deck_id: str, db: DbSession, user: CurrentUser) -> DeckSummary:
    deck = get_deck_or_404(db, deck_id, user)
    now = utcnow()
    for card in deck.cards:
        card.ease_factor, card.interval_days, card.repetitions, card.lapses = 2.5, 0.0, 0, 0
        card.review_count, card.due_at, card.last_reviewed_at = 0, now, None
    db.commit()
    return _summary(deck)


@router.delete("/decks/{deck_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a deck")
def delete_deck(deck_id: str, db: DbSession, user: CurrentUser) -> Response:
    db.delete(get_deck_or_404(db, deck_id, user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
