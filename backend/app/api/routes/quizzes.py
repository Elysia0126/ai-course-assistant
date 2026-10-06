from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, EmbedderDep, LLMDep, SettingsDep, get_course_or_404
from app.core.errors import AppError, NotFoundError
from app.models import Quiz
from app.schemas.quiz import AttemptOut, AttemptRequest, QuizDetail, QuizGenerateRequest, QuizSummary
from app.services.quizzes import create_quiz, grade_attempt

router = APIRouter(tags=["quizzes"])


def _summary_fields(quiz: Quiz) -> dict:
    scores = [a.score for a in quiz.attempts]
    return {
        "question_count": len(quiz.questions),
        "attempt_count": len(scores),
        "best_score": max(scores) if scores else None,
    }


def _detail(quiz: Quiz) -> QuizDetail:
    return QuizDetail.model_validate(quiz).model_copy(update=_summary_fields(quiz))


def _get_quiz(db: DbSession, quiz_id: str) -> Quiz:
    quiz = db.get(Quiz, quiz_id)
    if quiz is None:
        raise NotFoundError("Quiz not found.")
    return quiz


@router.post(
    "/courses/{course_id}/quizzes",
    response_model=QuizDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a quiz from course materials",
)
def generate_quiz(
    course_id: str,
    payload: QuizGenerateRequest,
    db: DbSession,
    settings: SettingsDep,
    embedder: EmbedderDep,
    llm: LLMDep,
) -> QuizDetail:
    course = get_course_or_404(db, course_id)
    quiz = create_quiz(
        db,
        settings,
        embedder,
        llm,
        course,
        num_questions=payload.num_questions,
        difficulty=payload.difficulty,
        question_types=payload.question_types,
        document_ids=payload.document_ids,
        topic=payload.topic,
    )
    return _detail(quiz)


@router.get("/courses/{course_id}/quizzes", response_model=list[QuizSummary], summary="List quizzes")
def list_quizzes(course_id: str, db: DbSession) -> list[QuizSummary]:
    get_course_or_404(db, course_id)
    quizzes = db.scalars(
        select(Quiz)
        .where(Quiz.course_id == course_id)
        .options(selectinload(Quiz.questions), selectinload(Quiz.attempts))
        .order_by(Quiz.created_at.desc())
    ).all()
    return [QuizSummary.model_validate(q).model_copy(update=_summary_fields(q)) for q in quizzes]


@router.get("/quizzes/{quiz_id}", response_model=QuizDetail, summary="Get a quiz (answers hidden)")
def get_quiz(quiz_id: str, db: DbSession) -> QuizDetail:
    return _detail(_get_quiz(db, quiz_id))


@router.delete("/quizzes/{quiz_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a quiz")
def delete_quiz(quiz_id: str, db: DbSession) -> Response:
    db.delete(_get_quiz(db, quiz_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/quizzes/{quiz_id}/attempts",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit answers and get graded results",
)
def submit_attempt(quiz_id: str, payload: AttemptRequest, db: DbSession) -> AttemptOut:
    quiz = _get_quiz(db, quiz_id)
    unknown = set(payload.answers) - {q.id for q in quiz.questions}
    if unknown:
        raise AppError("Answers reference questions that are not part of this quiz.", code="invalid_answers")
    return AttemptOut.model_validate(grade_attempt(db, quiz, payload.answers))


@router.get("/quizzes/{quiz_id}/attempts", response_model=list[AttemptOut], summary="Attempt history")
def list_attempts(quiz_id: str, db: DbSession) -> list[AttemptOut]:
    quiz = _get_quiz(db, quiz_id)
    return [AttemptOut.model_validate(a) for a in reversed(quiz.attempts)]
