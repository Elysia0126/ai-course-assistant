from fastapi import APIRouter, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, SettingsDep, get_course_or_404
from app.db.types import utcnow
from app.models import ChatSession, Chunk, Course, Document, DocumentStatus, Flashcard, FlashcardDeck, Quiz
from app.schemas.course import CourseCreate, CourseOut, CourseStats, CourseUpdate
from app.services.documents import delete_course_files

router = APIRouter(prefix="/courses", tags=["courses"])


def course_stats(db: Session, course_ids: list[str]) -> dict[str, CourseStats]:
    """All dashboard counters in a handful of grouped queries (no N+1)."""
    stats = {cid: CourseStats() for cid in course_ids}
    if not course_ids:
        return stats

    for cid, total, ready in db.execute(
        select(
            Document.course_id,
            func.count(Document.id),
            func.sum(case((Document.status == DocumentStatus.READY, 1), else_=0)),
        )
        .where(Document.course_id.in_(course_ids))
        .group_by(Document.course_id)
    ):
        stats[cid].document_count = total
        stats[cid].ready_document_count = int(ready or 0)

    simple_counts = [
        ("chunk_count", Chunk.course_id, Chunk.id),
        ("quiz_count", Quiz.course_id, Quiz.id),
        ("deck_count", FlashcardDeck.course_id, FlashcardDeck.id),
        ("chat_count", ChatSession.course_id, ChatSession.id),
    ]
    for attr, course_col, id_col in simple_counts:
        for cid, count in db.execute(
            select(course_col, func.count(id_col)).where(course_col.in_(course_ids)).group_by(course_col)
        ):
            setattr(stats[cid], attr, count)

    for cid, count in db.execute(
        select(FlashcardDeck.course_id, func.count(Flashcard.id))
        .join(Flashcard, Flashcard.deck_id == FlashcardDeck.id)
        .where(FlashcardDeck.course_id.in_(course_ids), Flashcard.due_at <= utcnow())
        .group_by(FlashcardDeck.course_id)
    ):
        stats[cid].due_card_count = count
    return stats


def to_out(course: Course, stats: CourseStats) -> CourseOut:
    out = CourseOut.model_validate(course)
    out.stats = stats
    return out


@router.get("", response_model=list[CourseOut], summary="List courses with dashboard stats")
def list_courses(db: DbSession) -> list[CourseOut]:
    courses = db.scalars(select(Course).order_by(Course.updated_at.desc())).all()
    stats = course_stats(db, [c.id for c in courses])
    return [to_out(c, stats[c.id]) for c in courses]


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED, summary="Create a course")
def create_course(payload: CourseCreate, db: DbSession) -> CourseOut:
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    return to_out(course, CourseStats())


@router.get("/{course_id}", response_model=CourseOut, summary="Get one course")
def get_course(course_id: str, db: DbSession) -> CourseOut:
    course = get_course_or_404(db, course_id)
    return to_out(course, course_stats(db, [course.id])[course.id])


@router.patch("/{course_id}", response_model=CourseOut, summary="Update course details")
def update_course(course_id: str, payload: CourseUpdate, db: DbSession) -> CourseOut:
    course = get_course_or_404(db, course_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name" and not value:
            continue
        setattr(course, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return to_out(course, course_stats(db, [course.id])[course.id])


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a course and all its data")
def delete_course(course_id: str, db: DbSession, settings: SettingsDep) -> Response:
    course = get_course_or_404(db, course_id)
    db.delete(course)
    db.commit()
    delete_course_files(settings, course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
