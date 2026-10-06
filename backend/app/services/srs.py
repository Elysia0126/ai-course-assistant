"""SM-2 spaced repetition (the algorithm behind classic Anki), with four answer buttons."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Rating = Literal["again", "hard", "good", "easy"]

# SM-2 grades answers 0–5; buttons map onto the passing/failing part of that scale.
QUALITY: dict[str, int] = {"again": 1, "hard": 3, "good": 4, "easy": 5}
MIN_EASE = 1.3
RELEARN_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class ReviewState:
    ease_factor: float = 2.5
    interval_days: float = 0.0
    repetitions: int = 0
    lapses: int = 0


@dataclass(frozen=True)
class ReviewOutcome:
    state: ReviewState
    due_at: datetime


def schedule(state: ReviewState, rating: Rating, now: datetime) -> ReviewOutcome:
    quality = QUALITY[rating]
    ease = state.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(MIN_EASE, round(ease, 3))

    if quality < 3:
        # Lapse: relearn soon, restart the repetition ladder.
        new_state = ReviewState(ease, 0.0, 0, state.lapses + 1)
        return ReviewOutcome(new_state, now + RELEARN_DELAY)

    if state.repetitions == 0:
        interval = {"hard": 1.0, "good": 1.0, "easy": 4.0}[rating]
    elif state.repetitions == 1:
        interval = {"hard": 3.0, "good": 6.0, "easy": 8.0}[rating]
    else:
        base = max(state.interval_days, 1.0)
        multiplier = {"hard": 1.2, "good": ease, "easy": ease * 1.3}[rating]
        interval = round(base * multiplier, 1)

    new_state = ReviewState(ease, interval, state.repetitions + 1, state.lapses)
    return ReviewOutcome(new_state, now + timedelta(days=interval))
