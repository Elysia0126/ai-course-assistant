import type { Flashcard, Rating } from "./types";

/**
 * Client-side mirror of backend/app/services/srs.py, used only to preview the next interval on each
 * rating button. The server remains the source of truth for scheduling.
 */
const QUALITY: Record<Rating, number> = { again: 1, hard: 3, good: 4, easy: 5 };

export function nextIntervalDays(card: Pick<Flashcard, "ease_factor" | "interval_days" | "repetitions">, rating: Rating): number {
  const quality = QUALITY[rating];
  const ease = Math.max(1.3, card.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)));
  if (quality < 3) return 10 / (60 * 24); // relearn in 10 minutes
  if (card.repetitions === 0) return { hard: 1, good: 1, easy: 4, again: 0 }[rating];
  if (card.repetitions === 1) return { hard: 3, good: 6, easy: 8, again: 0 }[rating];
  const base = Math.max(card.interval_days, 1);
  const multiplier = { hard: 1.2, good: ease, easy: ease * 1.3, again: 0 }[rating];
  return Math.round(base * multiplier * 10) / 10;
}

export function formatInterval(days: number): string {
  if (days < 1 / 24) return `${Math.max(1, Math.round(days * 24 * 60))}m`;
  if (days < 1) return `${Math.round(days * 24)}h`;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}
