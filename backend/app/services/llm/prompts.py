"""Prompt templates. Sources are numbered so the model can cite them as [n] (answers) or source_id (quizzes)."""

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape, quoteattr

if TYPE_CHECKING:
    from app.services.retrieval import RetrievedChunk


def format_sources(sources: list["RetrievedChunk"]) -> str:
    blocks = []
    for i, src in enumerate(sources, start=1):
        attrs = f"id={quoteattr(str(i))} file={quoteattr(src.filename)}"
        if src.location:
            attrs += f" location={quoteattr(src.location)}"
        if src.section and src.section != src.location:
            attrs += f" section={quoteattr(src.section)}"
        blocks.append(f"<source {attrs}>\n{escape(src.content)}\n</source>")
    return "<sources>\n" + "\n".join(blocks) + "\n</sources>"


def answer_system_prompt(course_name: str) -> str:
    return f"""You are a teaching assistant for the course "{course_name}". Students ask questions about their \
course materials, and each question arrives with numbered excerpts retrieved from the materials they uploaded.

How to answer:
- Base the answer on the provided sources. Cite them inline with bracketed numbers such as [1] or [2][3], placed \
right after the sentence or claim they support. Only cite source numbers that exist.
- If the sources do not contain the answer, say so plainly, share what the sources do cover that is related, and \
suggest what material the student could look for. Never invent facts, page numbers, or citations.
- Teach, don't just state: give the direct answer first, then a short explanation, the key steps, or a small \
example when it helps understanding.
- Format with Markdown. Write math in LaTeX using $...$ inline and $$...$$ for display equations.
- Reply in the same language as the student's question.
- Latency-sensitive; begin your visible answer immediately."""


def answer_user_message(question: str, sources: list["RetrievedChunk"]) -> str:
    if not sources:
        return f"No relevant excerpts were found in the course materials for this question.\n\nQuestion: {question}"
    return f"{format_sources(sources)}\n\nQuestion: {question}"


def quiz_system_prompt(course_name: str) -> str:
    return f"""You are an experienced instructor writing assessment questions for the course "{course_name}". \
Every question must be answerable from the provided source excerpts alone, test understanding rather than \
trivia about wording, and have exactly one defensible correct answer."""


_DIFFICULTY_GUIDE = {
    "easy": "recall of key definitions, facts, and terminology",
    "medium": "understanding and application: explain why, compare concepts, apply an idea to a small example",
    "hard": "analysis: multi-step reasoning, edge cases, trade-offs, or combining ideas from different sources",
}

_TYPE_GUIDE = {
    "mcq": 'mcq — exactly 4 options; "answer" is the exact text of the single correct option; distractors are '
    "plausible misconceptions, not jokes",
    "true_false": 'true_false — options are ["True", "False"]; "answer" is "True" or "False"; avoid trivially '
    "negated sentences",
    "short_answer": 'short_answer — options is []; "answer" is a concise model answer (1–3 sentences) containing '
    "the key terms a grader should look for",
}


def quiz_user_message(
    sources: list["RetrievedChunk"],
    num_questions: int,
    difficulty: str,
    question_types: list[str],
    topic: str | None,
) -> str:
    type_lines = "\n".join(f"- {_TYPE_GUIDE[t]}" for t in question_types)
    focus = f"Focus on this topic: {topic}\n" if topic else ""
    return f"""{format_sources(sources)}

Write a quiz of exactly {num_questions} questions at {difficulty} difficulty ({_DIFFICULTY_GUIDE[difficulty]}).
{focus}
Allowed question types (mix them when more than one is allowed):
{type_lines}

For every question also provide:
- "explanation": 1–3 sentences explaining why the answer is correct, grounded in the source.
- "source_id": the id of the source the question is based on.

Cover different sources and concepts rather than asking several questions about the same sentence. Give the quiz a \
short descriptive "title". Write in the language of the sources."""


def flashcards_system_prompt(course_name: str) -> str:
    return f"""You create high-quality study flashcards for the course "{course_name}" from the provided source \
excerpts. Good cards are atomic (one idea per card), phrased as a question or cue on the front, and have a concise, \
self-contained answer on the back."""


def flashcards_user_message(sources: list["RetrievedChunk"], num_cards: int, topic: str | None) -> str:
    focus = f"Focus on this topic: {topic}\n" if topic else ""
    return f"""{format_sources(sources)}

Create exactly {num_cards} flashcards.
{focus}
Guidelines:
- Prioritise definitions, key formulas, cause → effect relationships, comparisons, and common pitfalls.
- Front: a specific question or cue (no yes/no questions). Back: the answer in at most ~40 words; use LaTeX ($...$) \
for math.
- "source_id": the id of the source the card is based on.
- Spread cards across the sources. Give the deck a short descriptive "title". Write in the language of the sources."""
