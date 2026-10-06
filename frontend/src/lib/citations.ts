/**
 * Turn bracketed citation markers like "[2]" or "[1, 3]" into Markdown links "[2](#cite-2)" so the
 * Markdown renderer can show them as interactive chips. Out-of-range numbers are left untouched, and
 * existing Markdown links ("[text](url)") and fenced code blocks are not modified.
 */
export function linkCitations(markdown: string, sourceCount: number): string {
  const parts = markdown.split(/(```[\s\S]*?```)/g);
  return parts
    .map((part) =>
      part.startsWith("```")
        ? part
        : part.replace(/\[(\d+(?:\s*[,，]\s*\d+)*)\](?!\()/g, (match, group: string) => {
            const numbers = group.split(/[,，]/).map((n) => Number(n.trim()));
            if (!numbers.every((n) => n >= 1 && n <= sourceCount)) return match;
            return numbers.map((n) => `[${n}](#cite-${n})`).join("");
          }),
    )
    .join("");
}

export function citationNumber(href: string | undefined): number | null {
  const match = href?.match(/^#cite-(\d+)$/);
  return match ? Number(match[1]) : null;
}

/** Citation numbers in order of first appearance. */
export function citedNumbers(markdown: string, sourceCount: number): number[] {
  const seen: number[] = [];
  for (const match of markdown.matchAll(/\[(\d+(?:\s*[,，]\s*\d+)*)\]/g)) {
    for (const part of match[1].split(/[,，]/)) {
      const n = Number(part.trim());
      if (n >= 1 && n <= sourceCount && !seen.includes(n)) seen.push(n);
    }
  }
  return seen;
}
