"""Deterministic, key-free backend built from simple NLP heuristics.

It exists so the product works end-to-end before an API key is configured, and so the test suite is
hermetic. Answers are extractive (the most relevant source sentences, with citations); quizzes and
flashcards come from definition patterns ("X is …"), cloze deletions of key terms, and term swaps.
"""

import math
import random
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from app.services.llm.base import (
    CardDraft,
    ChatTurn,
    DeckDraft,
    Difficulty,
    QuestionDraft,
    QuestionType,
    QuizDraft,
)
from app.services.retrieval import RetrievedChunk
from app.services.text_utils import STOPWORDS, split_sentences, stem, tokenize, truncate

_BULLET_RE = re.compile(r"^\s*(?:[-•*▪●◦]|\d+[.)])\s+")
_DEFINITION_RE = re.compile(
    r"^(?:an?\s+|the\s+)?(?P<term>[A-Za-z][\w\-/() ]{1,60}?)\s+"
    r"(?:is defined as|refers to|is|are|means|describes)\s+(?P<definition>.{15,400}?)\.?$",
    re.IGNORECASE,
)
_COLON_RE = re.compile(r"^(?P<term>[A-Za-z][\w\-/() ]{1,50}):\s+(?P<definition>.{15,300}?)\.?$")
_NOTES_PREFIX = re.compile(r"^speaker notes:\s*", re.IGNORECASE)
# Sentences starting with these depend on context the reader can't see ("It prevents …").
_BAD_TERM_START = frozenset(
    "this it that these there they which what here each one our we you he she its their such all most some "
    "many when if how".split()
)
# Labels that look like "Term: definition" but are document structure, not concepts.
_STRUCTURAL_TERMS = frozenset(
    "lecture chapter week slide section part unit module topic agenda outline summary overview note notes tip "
    "tips example examples fix fixes hint warning goal goals objective objectives reading readings".split()
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{3,}")

OFFLINE_NOTE = (
    "\n\n> _Offline mode: this answer was extracted directly from your materials. Set `ANTHROPIC_API_KEY` "
    "(or an OpenAI-compatible provider) for generated explanations._"
)


@dataclass
class _Candidate:
    text: str
    source_id: int


@dataclass
class _Definition:
    term: str
    definition: str
    source_id: int


def _candidates(sources: list[RetrievedChunk]) -> list[_Candidate]:
    out: list[_Candidate] = []
    for i, src in enumerate(sources, start=1):
        for sentence in split_sentences(src.content):
            for line in sentence.split("\n"):
                line = _NOTES_PREFIX.sub("", _BULLET_RE.sub("", line)).strip()
                if line:
                    out.append(_Candidate(line, i))
    return out


def _is_concept_term(term: str) -> bool:
    words = term.lower().split()
    return (
        1 <= len(words) <= 6
        and words[0] not in _BAD_TERM_START
        and words[0] not in _STRUCTURAL_TERMS
        and not any(ch.isdigit() for ch in term)
    )


def _good_sentence(text: str) -> bool:
    words = text.split()
    digits = sum(ch.isdigit() for ch in text)
    return 40 <= len(text) <= 280 and len(words) >= 6 and digits < len(text) * 0.2


def _definitions(candidates: list[_Candidate]) -> list[_Definition]:
    found: list[_Definition] = []
    seen: set[str] = set()
    for cand in candidates:
        match = _DEFINITION_RE.match(cand.text) or _COLON_RE.match(cand.text)
        if not match:
            continue
        term = match.group("term").strip(" -")
        definition = match.group("definition").strip()
        if not _is_concept_term(term) or term.lower() in seen:
            continue
        if len(definition.split()) < 4:
            continue
        seen.add(term.lower())
        found.append(_Definition(term, definition[0].upper() + definition[1:], cand.source_id))
    return found


def _key_terms(sources: list[RetrievedChunk], definitions: list[_Definition]) -> list[str]:
    """Rank single-word terms by tf-idf across the sources; definition terms go first."""
    doc_freq: Counter[str] = Counter()
    term_freq: Counter[str] = Counter()
    for src in sources:
        words = [w.lower() for w in _WORD_RE.findall(src.content)]
        words = [w for w in words if w not in STOPWORDS and len(w) >= 5]
        term_freq.update(words)
        doc_freq.update(set(words))
    n = max(len(sources), 1)
    scored = sorted(term_freq, key=lambda w: term_freq[w] * math.log(1 + n / doc_freq[w]), reverse=True)
    terms: list[str] = []
    seen_stems: set[str] = set()
    for term in [d.term for d in definitions] + scored:
        key = " ".join(stem(t) for t in term.lower().split())
        if key not in seen_stems:
            seen_stems.add(key)
            terms.append(term)
    return terms


def _display(term: str) -> str:
    return term if term.isupper() else term.lower()


def _contains(text: str, term: str) -> re.Match[str] | None:
    return re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)


def _distractors(answer: str, pool: list[str], sentence: str, rng: random.Random, k: int = 3) -> list[str]:
    answer_stem = stem(answer.lower())
    options = [
        t
        for t in pool[:40]
        if stem(t.lower()) != answer_stem and not _contains(sentence, t) and t.lower() not in answer.lower()
    ]
    rng.shuffle(options)
    return options[:k]


class OfflineBackend:
    name = "offline"
    model = "extractive-heuristics"

    def __init__(self, seed: int | None = None):
        self.seed = seed

    # --- Q&A ---------------------------------------------------------------------

    def stream_answer(
        self, *, course_name: str, question: str, sources: list[RetrievedChunk], history: list[ChatTurn]
    ) -> Iterator[str]:
        if not sources:
            text = (
                "I couldn't find anything about this in the uploaded course materials. Try rephrasing the "
                "question or upload the lecture that covers it."
            )
        else:
            text = self._extractive_answer(question, sources) + OFFLINE_NOTE
        # Emit word-sized pieces so the UI exercises the same streaming path as real providers.
        for match in re.finditer(r"\S+\s*", text):
            yield match.group(0)

    def _extractive_answer(self, question: str, sources: list[RetrievedChunk]) -> str:
        q_terms = set(tokenize(question))
        # Keep self-contained statements: no headings/fragments, and nothing that opens with a pronoun
        # ("It prevents …") whose referent was in a sentence the reader won't see.
        candidates = [
            c
            for c in _candidates(sources)
            if len(c.text) >= 25 and len(c.text.split()) >= 6 and c.text.split()[0].lower() not in _BAD_TERM_START
        ]
        term_sets = [set(tokenize(c.text)) for c in candidates]
        doc_freq = Counter(t for terms in term_sets for t in terms)
        n = max(len(candidates), 1)

        scored: list[tuple[float, int, str]] = []
        for cand, terms in zip(candidates, term_sets, strict=True):
            overlap = q_terms & terms
            if not overlap:
                continue
            # Rare shared terms ("vanish") matter more than ubiquitous ones ("gradient"); higher-ranked
            # sources and definition-like sentences get a boost.
            score = sum(math.log(1 + n / (1 + doc_freq[t])) for t in overlap) / math.sqrt(len(terms) + 1)
            score += 0.4 / cand.source_id
            if _DEFINITION_RE.match(cand.text):
                score += 0.3
            scored.append((score, cand.source_id, cand.text))

        scored.sort(key=lambda item: item[0], reverse=True)
        picked: list[tuple[int, str]] = []
        seen: set[str] = set()
        for _, source_id, text in scored:
            key = text.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            picked.append((source_id, text))
            if len(picked) == 4:
                break
        if not picked:
            picked = [(i, truncate(src.content, 240)) for i, src in enumerate(sources[:2], start=1)]

        lines = [f"- {truncate(text, 320)} [{source_id}]" for source_id, text in picked]
        return "Here is what your course materials say about this:\n\n" + "\n".join(lines)

    # --- Quiz ----------------------------------------------------------------------

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
        rng = random.Random(self.seed)
        candidates = _candidates(sources)
        definitions = _definitions(candidates)
        terms = _key_terms(sources, definitions)
        sentences = [c for c in candidates if _good_sentence(c.text)]
        rng.shuffle(sentences)
        rng.shuffle(definitions)

        used_sentences: set[str] = set()
        used_terms: set[str] = set()
        questions: list[QuestionDraft] = []

        def next_sentence_with_term() -> tuple[_Candidate, str] | None:
            for cand in sentences:
                if cand.text in used_sentences:
                    continue
                for term in terms[:60]:
                    if term.lower() in used_terms or len(term) < 4:
                        continue
                    if _contains(cand.text, term):
                        used_sentences.add(cand.text)
                        used_terms.add(term.lower())
                        return cand, term
            return None

        def make_mcq() -> QuestionDraft | None:
            for definition in definitions:
                if definition.term.lower() in used_terms:
                    continue
                distractors = _distractors(definition.term, terms, definition.definition, rng)
                if len(distractors) < 3:
                    break
                used_terms.add(definition.term.lower())
                options = [_display(definition.term)] + [_display(d) for d in distractors]
                rng.shuffle(options)
                return QuestionDraft(
                    type="mcq",
                    question=f"Which term matches this description? “{definition.definition}”",
                    options=options,
                    answer=_display(definition.term),
                    explanation=f"The materials define {definition.term} as: {definition.definition}",
                    source_id=definition.source_id,
                )
            found = next_sentence_with_term()
            if not found:
                return None
            cand, term = found
            distractors = _distractors(term, terms, cand.text, rng)
            if len(distractors) < 3:
                return None
            match = _contains(cand.text, term)
            assert match is not None
            blanked = cand.text[: match.start()] + "_____" + cand.text[match.end() :]
            options = [_display(term)] + [_display(d) for d in distractors]
            rng.shuffle(options)
            return QuestionDraft(
                type="mcq",
                question=f"Fill in the blank: {blanked}",
                options=options,
                answer=_display(term),
                explanation=f"From the materials: “{cand.text}”",
                source_id=cand.source_id,
            )

        def make_true_false() -> QuestionDraft | None:
            found = next_sentence_with_term()
            if not found:
                return None
            cand, term = found
            make_false = rng.random() < 0.5
            statement = cand.text
            if make_false:
                swaps = _distractors(term, terms, cand.text, rng, k=1)
                if swaps:
                    match = _contains(cand.text, term)
                    assert match is not None
                    statement = cand.text[: match.start()] + _display(swaps[0]) + cand.text[match.end() :]
                else:
                    make_false = False
            return QuestionDraft(
                type="true_false",
                question=f"True or false: {statement}",
                options=["True", "False"],
                answer="False" if make_false else "True",
                explanation=f"The materials state: “{cand.text}”",
                source_id=cand.source_id,
            )

        def make_short_answer() -> QuestionDraft | None:
            for definition in definitions:
                if definition.term.lower() in used_terms:
                    continue
                used_terms.add(definition.term.lower())
                return QuestionDraft(
                    type="short_answer",
                    question=f"In your own words, what is {definition.term}?",
                    options=[],
                    answer=definition.definition,
                    explanation=f"{definition.term}: {definition.definition}",
                    source_id=definition.source_id,
                )
            for i, src in enumerate(sources, start=1):
                key = f"section:{i}"
                summary = _section_summary(src)
                if not src.section or not summary or key in used_sentences:
                    continue
                used_sentences.add(key)
                return QuestionDraft(
                    type="short_answer",
                    question=f"Summarize the key idea of “{src.section}”.",
                    options=[],
                    answer=summary,
                    explanation="Compare your answer with the key points in the cited source.",
                    source_id=i,
                )
            return None

        makers = {"mcq": make_mcq, "true_false": make_true_false, "short_answer": make_short_answer}
        exhausted: set[str] = set()
        cycle = 0
        while len(questions) < num_questions and len(exhausted) < len(question_types):
            qtype = question_types[cycle % len(question_types)]
            cycle += 1
            if qtype in exhausted:
                continue
            question = makers[qtype]()
            if question is None:
                exhausted.add(qtype)
            else:
                questions.append(question)

        title = f"Practice quiz: {topic}" if topic else f"Practice quiz — {_deck_label(sources)}"
        return QuizDraft(title=title[:200], questions=questions)

    # --- Flashcards --------------------------------------------------------------------

    def generate_flashcards(
        self, *, course_name: str, sources: list[RetrievedChunk], num_cards: int, topic: str | None
    ) -> DeckDraft:
        rng = random.Random(self.seed)
        candidates = _candidates(sources)
        definitions = _definitions(candidates)
        terms = _key_terms(sources, definitions)
        cards: list[CardDraft] = []
        seen_fronts: set[str] = set()

        def add(front: str, back: str, source_id: int) -> None:
            if front.lower() not in seen_fronts and len(cards) < num_cards:
                seen_fronts.add(front.lower())
                cards.append(CardDraft(front=front, back=back, source_id=source_id))

        for definition in definitions:
            add(f"What is {definition.term}?", definition.definition, definition.source_id)

        sentences = [c for c in candidates if _good_sentence(c.text)]
        rng.shuffle(sentences)
        used_terms = {d.term.lower() for d in definitions}
        for cand in sentences:
            if len(cards) >= num_cards:
                break
            for term in terms[:40]:
                if term.lower() in used_terms:
                    continue
                match = _contains(cand.text, term)
                if match:
                    used_terms.add(term.lower())
                    blanked = cand.text[: match.start()] + "_____" + cand.text[match.end() :]
                    add(f"Fill in the blank: {blanked}", _display(term), cand.source_id)
                    break

        for i, src in enumerate(sources, start=1):
            summary = _section_summary(src)
            if src.section and summary:
                add(f"Key idea: {src.section}", summary, i)

        title = f"Flashcards: {topic}" if topic else f"Key concepts — {_deck_label(sources)}"
        return DeckDraft(title=title[:200], cards=cards)


def _section_summary(src: RetrievedChunk, limit: int = 280) -> str:
    """First two real sentences of a chunk (skipping its title line and speaker-notes labels)."""
    sentences = [c.text for c in _candidates([src]) if c.text != src.section and len(c.text.split()) >= 6]
    return truncate(" ".join(sentences[:2]), limit) if sentences else ""


def _deck_label(sources: list[RetrievedChunk]) -> str:
    names = Counter(src.filename.rsplit(".", 1)[0] for src in sources)
    if not names:
        return "course materials"
    top, _ = names.most_common(1)[0]
    return top if len(names) == 1 else f"{top} and {len(names) - 1} more"
