"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { citationNumber, linkCitations } from "@/lib/citations";
import { cn } from "@/lib/format";

/** Renders an answer as Markdown (GFM + LaTeX) and turns [n] markers into clickable citation chips. */
export const Markdown = memo(function Markdown({
  content,
  sourceCount = 0,
  onCite,
  className,
}: {
  content: string;
  sourceCount?: number;
  onCite?: (n: number) => void;
  className?: string;
}) {
  return (
    <div className={cn("prose-answer text-slate-800", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a({ href, children }) {
            const n = citationNumber(href);
            if (n !== null) {
              return (
                <button
                  type="button"
                  onClick={() => onCite?.(n)}
                  className="mx-0.5 inline-flex h-4.5 min-w-4.5 -translate-y-0.5 items-center justify-center rounded-md bg-indigo-100 px-1 align-middle text-[11px] font-semibold text-indigo-700 transition hover:bg-indigo-600 hover:text-white"
                  aria-label={`Show source ${n}`}
                >
                  {n}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-indigo-600 underline underline-offset-2">
                {children}
              </a>
            );
          },
        }}
      >
        {linkCitations(content, sourceCount)}
      </ReactMarkdown>
    </div>
  );
});
