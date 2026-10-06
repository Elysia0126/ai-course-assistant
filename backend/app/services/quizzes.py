"""Quiz generation (grounded in course chunks), answer normalisation, and grading."""

import random
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, LLMError, NoMaterialsError
from app.models import Course, Quiz, QuizAttempt, QuizQuestion
from app.services.embeddings import EmbeddingProvider
from app.services.llm import LLMBackend
from app.services.llm.base import QuestionDraft, QuestionType
from app.services.retrieval import HybridRetriever, RetrievedChunk, sample_study_chunks
from app.services.text_utils import tokenize

SHORT_ANSWER_PASS = 0.5
SHORT_ANSWER_PARTIAL = 0.25
_TRUE = {"true", "t", "yes", "correct", "对", "正确", "是"}
_FALSE = {"false", "f", "no", "incorrect", "错", "错误", "否"}
_OPTION_PREFIX = re.compile(r"^\s*(?:\(?[A-Da-d][).:]|[A-Da-d]\s*[-–])\s+")


def select_sources(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    course_id: str,
    *,
    document_ids: list[str] | None,
    topic: str | None,
    count: int,
) -> list[RetrievedChunk]:
    """Context for generation: topic-focused retrieval, or an even spread across the selected documents."""
    limit = max(6, min(count + 4, 14))
    if topic:
        chunks = (
            HybridRetriever(session, settings, embedder)
            .search(course_id, topic, top_k=limit, document_ids=document_ids)
            .chunks
        )
    else:
        chunks = sample_study_chunks(
            session, course_id, document_ids=document_ids, limit=limit, max_chars=settings.max_context_chars
        )
    if not chunks:
        raise NoMaterialsError("No processed materials found. Upload and process documents first.")
    return chunks


def source_snapshot(chunk: RetrievedChunk | None) -> dict[str, Any] | None:
    if chunk is None:
        return None
    snapshot = chunk.to_source(snippet_chars=240)
    for key in ("index", "score", "vector_score", "keyword_score", "cited"):
        snapshot.pop(key, None)
    return snapshot


def _clean_option(text: str) -> str:
    return _OPTION_PREFIX.sub("", text).strip()


def _normalize_bool(value: str) -> str | None:
    key = value.strip().lower().rstrip(".")
    if key in _TRUE:
        return "True"
    if key in _FALSE:
        return "False"
    return None


def normalize_question(draft: QuestionDraft, rng: random.Random) -> dict[str, Any] | None:
    """Validate and repair one generated question; return None if it is unusable."""
    prompt = draft.question.strip()
    if not prompt:
        return None

    if draft.type == "mcq":
        options: list[str] = []
        for option in (_clean_option(o) for o in draft.options):
            if option and option.lower() not in {o.lower() for o in options}:
                options.append(option)
        if len(options) < 2:
            return None
        answer = _clean_option(draft.answer)
        match = next((o for o in options if o.lower() == answer.lower()), None)
        if match is None and len(answer) == 1 and answer.upper() in "ABCD":
            index = "ABCD".index(answer.upper())
            match = options[index] if index < len(options) else None
        if match is None:
            return None
        rng.shuffle(options)  # LLMs over-place the right answer first; shuffle away position bias
        return {"question_type": "mcq", "prompt": prompt, "options": options[:6], "correct_answer": match}

    if draft.type == "true_false":
        answer = _normalize_bool(draft.answer)
        if answer is None:
            return None
        return {"question_type": "true_false", "prompt": prompt, "options": ["True", "False"], "correct_answer": answer}

    answer = draft.answer.strip()
    if not answer:
        return None
    return {"question_type": "short_answer", "prompt": prompt, "options": [], "correct_answer": answer}


def create_quiz(
    session: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    llm: LLMBackend,
    course: Course,
    *,
    num_questions: int,
    difficulty: str,
    question_types: list[QuestionType],
    document_ids: list[str] | None,
    topic: str | None,
) -> Quiz:
    sources = select_sources(
        session, settings, embedder, course.id, document_ids=document_ids, topic=topic, count=num_questions
    )
    draft = llm.generate_quiz(
        course_name=course.name,
        sources=sources,
        num_questions=num_questions,
        difficulty=difficulty,  # type: ignore[arg-type]
        question_types=question_types,
        topic=topic,
    )

    rng = random.Random()
    questions: list[QuizQuestion] = []
    seen_prompts: set[str] = set()
    for item in draft.questions:
        if item.type not in question_types or item.question.strip().lower() in seen_prompts:
            continue
        normalized = normalize_question(item, rng)
        if normalized is None:
            continue
        seen_prompts.add(item.question.strip().lower())
        source = sources[item.source_id - 1] if 1 <= item.source_id <= len(sources) else None
        questions.append(
            QuizQuestion(
                position=len(questions),
                explanation=item.explanation.strip(),
                source=source_snapshot(source),
                **normalized,
            )
        )
        if len(questions) == num_questions:
            break

    if not questions:
        if llm.name == "offline":
            raise AppError(
                "Not enough text in the selected materials to build questions offline. Add more material or "
                "configure an LLM provider.",
                code="generation_failed",
            )
        raise LLMError("The model did not return any valid questions. Please try again.")

    quiz = Quiz(
        course_id=course.id,
        title=(draft.title.strip() or "Practice quiz")[:200],
        difficulty=difficulty,
        topic=topic,
        document_ids=document_ids or [],
        generator=f"{llm.name}:{llm.model}"[:80],
        questions=questions,
    )
    session.add(quiz)
    session.commit()
    return quiz


def grade_short_answer(given: str, reference: str) -> tuple[float, str]:
    """Key-term recall against the reference answer. Transparent and deterministic, if not as nuanced as an LLM."""
    reference_terms = set(tokenize(reference))
    if not reference_terms:
        return (1.0, "") if given.strip() else (0.0, "")
    matched = reference_terms & set(tokenize(given))
    recall = len(matched) / len(reference_terms)
    if recall >= SHORT_ANSWER_PASS:
        score = 1.0
    elif recall >= SHORT_ANSWER_PARTIAL:
        score = 0.5
    else:
        score = 0.0
    feedback = f"Matched {len(matched)} of {len(reference_terms)} key terms"
    if matched:
        feedback += ": " + ", ".join(sorted(matched)[:8])
    return score, feedback


def grade_attempt(session: Session, quiz: Quiz, answers: dict[str, str]) -> QuizAttempt:
    results: list[dict[str, Any]] = []
    total_score = 0.0
    for question in quiz.questions:
        given = (answers.get(question.id) or "").strip()
        feedback = ""
        if not given:
            score = 0.0
            feedback = "No answer given."
        elif question.question_type == "short_answer":
            score, feedback = grade_short_answer(given, question.correct_answer)
        elif question.question_type == "true_false":
            score = 1.0 if _normalize_bool(given) == question.correct_answer else 0.0
        else:
            score = 1.0 if given.lower() == question.correct_answer.lower() else 0.0
        total_score += score
        results.append(
            {
                "question_id": question.id,
                "given": given,
                "correct": score >= 1.0,
                "score": score,
                "correct_answer": question.correct_answer,
                "explanation": question.explanation,
                "feedback": feedback,
                "source": question.source,
            }
        )

    total = len(quiz.questions)
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        answers=answers,
        results=results,
        score=round(100 * total_score / total, 1) if total else 0.0,
        correct_count=sum(1 for r in results if r["correct"]),
        total=total,
    )
    session.add(attempt)
    session.commit()
    return attempt
