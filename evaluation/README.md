# Retrieval evaluation

A small, hand-labelled benchmark for the retrieval layer, used to compare retrieval strategies (an ablation of
vector-only vs keyword-only vs hybrid RRF) and to catch regressions in CI.

- **Corpus:** the demo course in [`sample_data/`](../sample_data) — a 6-page PDF lecture, an 8-slide PPTX deck with
  speaker notes and a Markdown study guide (23 chunks).
- **Questions:** [`retrieval_questions.json`](retrieval_questions.json) — 33 questions:
  - 16 **lexical** (use the material's own terms, e.g. *"What is gradient clipping?"*),
  - 12 **paraphrase** (phrased like a student, without the key term, e.g. *"How do shortcut paths help signals reach
    the first layers of a very deep network?"* → residual connections, slide 7),
  - 5 **unanswerable** (not covered, e.g. *"Explain how the Krebs cycle produces ATP."*).
- **Relevance:** a hit is a retrieved chunk from a labelled location — file + page/slide, or file + Markdown
  section — not a substring match, so the citation location itself is being tested.
- **Metrics:** Recall@k (a relevant chunk in the top k) and MRR over the 28 answerable questions; for the
  low-confidence flag, the share of unanswerable questions flagged and of answerable questions falsely flagged.

## Results (2026-10-07)

Production configuration — local `BAAI/bge-small-en-v1.5` embeddings, PostgreSQL 16 + pgvector (HNSW) and in-database
BM25 over the full-text index:

| Retriever | Recall@1 | Recall@3 | Recall@5 | MRR | Recall@1 (paraphrase) | MRR (paraphrase) |
|---|---|---|---|---|---|---|
| vector only | 0.75 | 0.89 | **1.00** | 0.83 | 0.58 | 0.73 |
| keyword only (BM25) | **0.86** | **0.96** | 0.96 | **0.92** | **0.75** | **0.85** |
| **hybrid (RRF)** | **0.86** | **0.96** | **1.00** | **0.92** | **0.75** | **0.85** |

Low-confidence flag: **5/5 unanswerable questions flagged, 0/28 false alarms.**

| Configuration | Hybrid Recall@1 | Hybrid Recall@5 | Hybrid MRR | Unanswerable flagged / false alarms |
|---|---|---|---|---|
| bge-small + PostgreSQL/pgvector + BM25 (above) | 0.86 | 1.00 | 0.92 | 100% / 0% |
| bge-small + SQLite (numpy + in-process BM25) | 0.86 | 1.00 | 0.92 | 100% / 0% |
| feature hashing + SQLite (CI configuration) | 0.82 | 1.00 | 0.89 | 80% / 7% |

Full per-question output: [`results/`](results).

### What the numbers say

- **Hybrid is the most robust choice.** It matches the best single retriever on rank-1 accuracy and is the only
  configuration that finds every answerable question in the top 5. Vector search alone misses rank 1 a quarter of
  the time (7/28); keyword search alone ranks a paraphrased question (*"My model memorizes the training set…"*) only
  6th, where the vector ranking puts it 1st and fusion lifts it back into the top 5.
- **Semantic embeddings make the low-confidence flag reliable.** With bge-small every off-topic question fell below
  the similarity threshold and no answerable one did; lexical hashing vectors (the test configuration) cannot
  separate them as well.
- **The evaluation found a real bug.** The first PostgreSQL run ranked keywords with `ts_rank_cd`, which has no IDF:
  common course words ("gradient", "training") drowned out the term a question was actually about (keyword Recall@1
  0.64, MRR 0.79). Replacing it with BM25 computed from the GIN-indexed `tsvector` (per-term document frequencies,
  term frequencies parsed from the vector) raised it to 0.86 / 0.92 — the same quality as the in-process BM25.

### Caveats

This is a 23-chunk corpus with questions written by the developer, so absolute numbers are optimistic and small
differences (one question = 0.036 Recall) are not significant. It is a regression and ablation harness, not a claim
of general accuracy. Next steps: real course materials, questions written by students, more unanswerable and
near-miss questions, and answer-faithfulness scoring once an LLM key is configured.

## Reproduce

```bash
cd backend
python scripts/evaluate_retrieval.py                                     # hashing + SQLite (seconds, no downloads)
python scripts/evaluate_retrieval.py --embedding fastembed               # local semantic model
python scripts/evaluate_retrieval.py --embedding fastembed --database-url postgresql+psycopg://…/course_assistant_test
```

CI runs the first command with `--min-hybrid-recall5 0.9` so a retrieval regression fails the build.
