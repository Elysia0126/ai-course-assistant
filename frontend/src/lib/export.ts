import type { Flashcard } from "./types";

/**
 * Anki-importable text: one note per line, front<TAB>back, with header directives that tell Anki
 * (2.1.55+) the separator and that fields are plain text. Tabs/newlines inside fields are flattened.
 */
export function deckToAnkiText(cards: Pick<Flashcard, "front" | "back">[], tag?: string): string {
  const clean = (text: string) => text.replace(/[\t\r\n]+/g, " ").trim();
  const header = ["#separator:tab", "#html:false", ...(tag ? ["#tags column:3"] : [])];
  const rows = cards.map((card) => [clean(card.front), clean(card.back), ...(tag ? [tag] : [])].join("\t"));
  return [...header, ...rows].join("\n") + "\n";
}

export function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s_-]+/g, "-")
      .slice(0, 60) || "flashcards"
  );
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
