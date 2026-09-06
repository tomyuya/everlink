import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders one manual (a markdown string read from board/content/) with GFM
 * tables / code fences / task lists, styled by the Tailwind typography plugin.
 * Pure presentational server component — no DB, no client state.
 */
export function ManualDoc({ source }: { source: string }) {
  return (
    <article className="prose prose-zinc max-w-none dark:prose-invert prose-headings:scroll-mt-24 prose-table:text-[13px] prose-code:before:content-none prose-code:after:content-none prose-pre:overflow-x-auto">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{source}</ReactMarkdown>
    </article>
  );
}
