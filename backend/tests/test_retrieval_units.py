from datetime import UTC, datetime, timedelta

import numpy as np

from app.services.chat import extract_citations
from app.services.embeddings import HashEmbeddingProvider
from app.services.llm.openai_backend import extract_json_object
from app.services.quizzes import grade_short_answer
from app.services.retrieval import _TSV_ENTRY, BM25, reciprocal_rank_fusion
from app.services.srs import ReviewState, schedule
from app.services.text_utils import tokenize


def test_tokenize_stems_and_drops_stopwords() -> None:
    assert tokenize("What are the learning rates?") == ["learn", "rate"]
    # CJK text is tokenised per character so Chinese questions still get keyword matches.
    assert tokenize("梯度下降") == ["梯", "度", "下", "降"]


def test_bm25_prefers_documents_with_rare_query_terms() -> None:
    corpus = [tokenize(t) for t in ["the learning rate controls step size", "dropout zeroes activations", "learning"]]
    scores = BM25(corpus).scores(tokenize("what does dropout do"))
    assert int(np.argmax(scores)) == 1
    assert scores[0] == 0


def test_tsvector_text_parsing_for_bm25() -> None:
    tsv = "'adam':12,30B 'default':15 'o''neil':3 'rate':7,8,9"
    freqs = {m.group(1).replace("''", "'"): m.group(2).count(",") + 1 for m in _TSV_ENTRY.finditer(tsv)}
    assert freqs == {"adam": 2, "default": 1, "o'neil": 1, "rate": 3}


def test_rrf_rewards_items_ranked_well_by_both_retrievers() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60)
    assert max(fused, key=fused.__getitem__) == "b"


def test_hash_embeddings_are_normalised_and_similarity_tracks_overlap() -> None:
    provider = HashEmbeddingProvider(384)
    docs = provider.embed_documents(["gradient descent learning rate", "dropout regularization technique"])
    assert np.allclose(np.linalg.norm(docs, axis=1), 1.0)
    query = provider.embed_query("how to choose the learning rate for gradient descent")
    assert float(docs[0] @ query) > float(docs[1] @ query)


def test_extract_citations_dedupes_and_ignores_out_of_range() -> None:
    answer = "Gradient descent [1] uses a learning rate [2][1]. Adam [3, 9] is adaptive [7]."
    assert extract_citations(answer, n_sources=3) == [1, 2, 3]


def test_extract_json_object_handles_fences_and_prose() -> None:
    assert extract_json_object('```json\n{"title": "x", "cards": []}\n```') == {"title": "x", "cards": []}
    assert extract_json_object('Sure! Here it is: {"a": 1} Hope that helps.') == {"a": 1}


def test_short_answer_grading_by_key_term_recall() -> None:
    reference = "Dropout randomly sets a fraction of activations to zero during training."
    score, feedback = grade_short_answer("It randomly zeroes a fraction of the activations while training", reference)
    assert score >= 0.5
    assert "key terms" in feedback
    assert grade_short_answer("It is about databases", reference)[0] == 0.0


def test_sm2_schedule_grows_intervals_and_resets_on_lapse() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first = schedule(ReviewState(), "good", now)
    assert first.state.interval_days == 1 and first.due_at == now + timedelta(days=1)
    second = schedule(first.state, "good", now)
    assert second.state.interval_days == 6
    third = schedule(second.state, "good", now)
    assert third.state.interval_days > 6
    easy = schedule(second.state, "easy", now)
    assert easy.state.interval_days > third.state.interval_days

    lapse = schedule(third.state, "again", now)
    assert lapse.state.repetitions == 0 and lapse.state.lapses == 1
    assert lapse.due_at - now == timedelta(minutes=10)
    assert lapse.state.ease_factor < third.state.ease_factor


def test_ease_factor_has_a_floor() -> None:
    state = ReviewState()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(20):
        state = schedule(state, "again", now).state
    assert state.ease_factor == 1.3
