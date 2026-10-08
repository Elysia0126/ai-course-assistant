"""Ownership-scoped lookups: the only way routes and services load user data by id.

Every resource belongs to exactly one course and every course to one user, so each lookup joins up to the
course and filters on its owner. Anything that isn't yours is reported as "not found" — the same answer as
for an id that doesn't exist — so ids of other users' data can't be probed (and guessing a UUID would not
help anyway).
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import ChatSession, Chunk, Course, Document, Flashcard, FlashcardDeck, Quiz


def owned_course(db: Session, course_id: str, owner_id: str) -> Course:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.owner_id == owner_id))
    if course is None:
        raise NotFoundError("Course not found.")
    return course


def owned_document(db: Session, document_id: str, owner_id: str) -> Document:
    document = db.scalar(
        select(Document)
        .join(Course, Course.id == Document.course_id)
        .where(Document.id == document_id, Course.owner_id == owner_id)
    )
    if document is None:
        raise NotFoundError("Document not found.")
    return document


def owned_chunk(db: Session, chunk_id: str, owner_id: str) -> Chunk:
    chunk = db.scalar(
        select(Chunk)
        .join(Course, Course.id == Chunk.course_id)
        .where(Chunk.id == chunk_id, Course.owner_id == owner_id)
    )
    if chunk is None:
        raise NotFoundError("This passage no longer exists — the document may have been re-indexed or deleted.")
    return chunk


def owned_chat(db: Session, session_id: str, owner_id: str) -> ChatSession:
    chat = db.scalar(
        select(ChatSession)
        .join(Course, Course.id == ChatSession.course_id)
        .where(ChatSession.id == session_id, Course.owner_id == owner_id)
    )
    if chat is None:
        raise NotFoundError("Chat session not found.")
    return chat


def owned_quiz(db: Session, quiz_id: str, owner_id: str) -> Quiz:
    quiz = db.scalar(
        select(Quiz).join(Course, Course.id == Quiz.course_id).where(Quiz.id == quiz_id, Course.owner_id == owner_id)
    )
    if quiz is None:
        raise NotFoundError("Quiz not found.")
    return quiz


def owned_deck(db: Session, deck_id: str, owner_id: str) -> FlashcardDeck:
    deck = db.scalar(
        select(FlashcardDeck)
        .join(Course, Course.id == FlashcardDeck.course_id)
        .where(FlashcardDeck.id == deck_id, Course.owner_id == owner_id)
    )
    if deck is None:
        raise NotFoundError("Flashcard deck not found.")
    return deck


def owned_card(db: Session, card_id: str, owner_id: str) -> Flashcard:
    card = db.scalar(
        select(Flashcard)
        .join(FlashcardDeck, FlashcardDeck.id == Flashcard.deck_id)
        .join(Course, Course.id == FlashcardDeck.course_id)
        .where(Flashcard.id == card_id, Course.owner_id == owner_id)
    )
    if card is None:
        raise NotFoundError("Flashcard not found.")
    return card


def ensure_documents_in_course(db: Session, course_id: str, document_ids: Iterable[str] | None) -> None:
    """Reject document filters that point outside the (already authorised) course."""
    wanted = set(document_ids or ())
    if not wanted:
        return
    found = set(db.scalars(select(Document.id).where(Document.course_id == course_id, Document.id.in_(wanted))))
    if found != wanted:
        raise NotFoundError("One or more selected documents were not found in this course.")
