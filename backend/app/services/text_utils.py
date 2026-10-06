"""Small, dependency-free text helpers shared by BM25, hashing embeddings, grading and the offline generator."""

import re
import unicodedata
from itertools import pairwise

STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because been before being below
    between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each
    few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
    him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't
    my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd
    she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's
    these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd
    we'll we're we've were weren't what what's when when's where where's which while who who's whom why why's with
    won't would wouldn't you you'd you'll you're you've your yours yourself yourselves also may might must shall
    will one two use used using via e.g i.e etc however thus therefore within without per
    explain describe define definition question answer tell give show example examples please
    """.split()  # noqa: SIM905 - a word list is far more readable than a 200-line literal
)

# Hiragana/Katakana, CJK Extension A, and CJK Unified Ideographs.
_CJK_CLASS = "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|" + _CJK_CLASS)
_CJK_RE = re.compile(_CJK_CLASS)
_SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])|\n{2,}")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def stem(token: str) -> str:
    """A deliberately tiny suffix stripper (roughly Porter step 1) so plurals and verb forms match in BM25."""
    if len(token) <= 3 or not token.isascii() or not token.isalpha():
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith(("sses", "ches", "shes", "xes")):
        return token[:-2]
    if token.endswith(("ss", "us", "is")):
        return token
    if token.endswith("s"):
        return token[:-1]
    for suffix in ("ing", "ed"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            base = token[: -len(suffix)]
            if base.endswith(("at", "iz", "bl", "uc", "v")):
                return base + "e"  # rated -> rate, optimized -> optimize
            if base[-1] == base[-2] and base[-1] not in "lsz":
                return base[:-1]  # stopped -> stop
            return base
    return token


def tokenize(text: str, *, remove_stopwords: bool = True, stemming: bool = True) -> list[str]:
    tokens = _WORD_RE.findall(normalize(text))
    if remove_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS and (len(t) > 1 or _CJK_RE.match(t))]
    if stemming:
        tokens = [stem(t) for t in tokens]
    return tokens


def cjk_bigrams(tokens: list[str]) -> list[str]:
    """Chinese/Japanese have no spaces; adjacent-character bigrams make keyword matching useful."""
    return [a + b for a, b in pairwise(tokens) if _CJK_RE.match(a) and _CJK_RE.match(b)]


def split_sentences(text: str) -> list[str]:
    parts = (p.strip() for p in _SENTENCE_RE.split(text))
    return [p for p in parts if p]


def clean_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    # Re-join words hyphenated across line breaks by PDF extraction: "gradi-\nent" -> "gradient".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_BULLET_START = re.compile(r"^\s*(?:[-•*▪●◦]|\d+[.)]|[a-z][.)])\s")


def reflow_lines(text: str) -> str:
    """Undo hard line wraps from PDF layout while keeping real line breaks (headings, bullets).

    A break is treated as a soft wrap when the next line continues the sentence: it starts in lowercase,
    or the current line ends mid-clause (comma, hyphen, open parenthesis) or is long and unpunctuated.
    """
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if out and out[-1] and stripped and not _BULLET_START.match(stripped):
            prev = out[-1]
            soft_wrap = (
                stripped[0].islower()
                or prev.endswith((",", ";", "(", "-", "–", "/"))
                or (len(prev) > 60 and not prev.endswith((".", "!", "?", ":", "。", "！", "？", "：")))
            )
            if soft_wrap:
                out[-1] = f"{prev} {stripped}"
                continue
        out.append(stripped)
    return "\n".join(out)


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"
