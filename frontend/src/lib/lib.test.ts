import { describe, expect, it } from "vitest";

import { citationNumber, citedNumbers, linkCitations } from "./citations";
import { deckToAnkiText, slugify } from "./export";
import { formatBytes, sourceLabel, timeAgo } from "./format";
import { formatInterval, nextIntervalDays } from "./srs";
import { SSEParser } from "./sse";

describe("SSEParser", () => {
  it("parses events split across arbitrary chunk boundaries", () => {
    const parser = new SSEParser();
    const stream = 'event: sources\ndata: {"n":1}\n\nevent: token\ndata: {"text":"Hel"}\n\nevent: token\ndata: {"text":"lo"}\n\n';
    const events = [stream.slice(0, 17), stream.slice(17, 50), stream.slice(50)].flatMap((chunk) => parser.push(chunk));
    expect(events.map((e) => e.event)).toEqual(["sources", "token", "token"]);
    expect(events.map((e) => JSON.parse(e.data))).toEqual([{ n: 1 }, { text: "Hel" }, { text: "lo" }]);
  });

  it("handles CRLF line endings, comments and multi-line data", () => {
    const parser = new SSEParser();
    const events = parser.push(": keep-alive\r\n\r\nevent: done\r\ndata: a\r\ndata: b\r\n\r\n");
    expect(events).toEqual([{ event: "done", data: "a\nb" }]);
  });
});

describe("citations", () => {
  it("links in-range markers and leaves everything else alone", () => {
    const md = "GD [1] uses a step [2][3]. Adam [1, 2] adapts. Bad [9]. A [link](https://x.y) stays.";
    expect(linkCitations(md, 3)).toBe(
      "GD [1](#cite-1) uses a step [2](#cite-2)[3](#cite-3). Adam [1](#cite-1)[2](#cite-2) adapts. Bad [9]. A [link](https://x.y) stays.",
    );
  });

  it("does not touch code blocks", () => {
    const md = "See [1].\n```python\nx = a[1]\n```";
    expect(linkCitations(md, 2)).toBe("See [1](#cite-1).\n```python\nx = a[1]\n```");
  });

  it("extracts citation numbers in order of appearance", () => {
    expect(citedNumbers("b [2] a [1] again [2] bad [7]", 3)).toEqual([2, 1]);
    expect(citationNumber("#cite-12")).toBe(12);
    expect(citationNumber("https://example.com")).toBeNull();
  });
});

describe("SM-2 preview", () => {
  const fresh = { ease_factor: 2.5, interval_days: 0, repetitions: 0 };
  it("mirrors the backend schedule", () => {
    expect(nextIntervalDays(fresh, "good")).toBe(1);
    expect(nextIntervalDays(fresh, "easy")).toBe(4);
    expect(nextIntervalDays({ ...fresh, repetitions: 1, interval_days: 1 }, "good")).toBe(6);
    expect(nextIntervalDays({ ease_factor: 2.5, interval_days: 6, repetitions: 2 }, "good")).toBe(15);
    expect(formatInterval(nextIntervalDays(fresh, "again"))).toBe("10m");
  });

  it("formats intervals compactly", () => {
    expect(formatInterval(0.5)).toBe("12h");
    expect(formatInterval(6)).toBe("6d");
    expect(formatInterval(90)).toBe("3mo");
  });
});

describe("Anki export", () => {
  it("writes tab-separated notes with Anki header directives and flattened fields", () => {
    const text = deckToAnkiText(
      [
        { front: "What is dropout?", back: "Randomly zeroes\tactivations\nduring training." },
        { front: "Adam β1?", back: "0.9" },
      ],
      "ML101",
    );
    expect(text.split("\n")).toEqual([
      "#separator:tab",
      "#html:false",
      "#tags column:3",
      "What is dropout?\tRandomly zeroes activations during training.\tML101",
      "Adam β1?\t0.9\tML101",
      "",
    ]);
    expect(slugify("Key concepts — Lecture 3!")).toBe("key-concepts-lecture-3");
  });
});

describe("format helpers", () => {
  it("formats sizes, locations and relative times", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
    expect(sourceLabel({ file_type: "pptx", page_number: 4, section: null })).toBe("Slide 4");
    expect(sourceLabel({ file_type: "pdf", page_number: 2, section: null })).toBe("Page 2");
    expect(sourceLabel({ file_type: "md", page_number: null, section: "Dropout" })).toBe("Dropout");
    const now = new Date("2026-01-01T12:00:00Z");
    expect(timeAgo("2026-01-01T11:59:50Z", now)).toBe("just now");
    expect(timeAgo("2026-01-01T09:00:00Z", now)).toBe("3h ago");
  });
});
