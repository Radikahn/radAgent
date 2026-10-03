import { memo, useEffect, useMemo, useState } from "react";
import Markdown, { type Components, type Options } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { openUrl } from "@tauri-apps/plugin-opener";
import type { ElementContent, Root } from "hast";
import { CodeBlock, WritingCode } from "./CodeBlock";
import { externalUrl, remarkLinkify } from "./linkify";

/** How much of `text` may show: while streaming only whole words, so a word never appears in pieces */
function revealLimit(text: string, live: boolean): number {
  if (!live) return text.length;
  return text.search(/\s\S*$/) + 1;
}

function wordEnd(text: string, from: number, limit: number): number {
  let end = from;
  while (end < limit && !/\s/.test(text[end])) end++;
  return end;
}

/**
 * Releases `text` a few words per frame at an even pace, however bursty the stream is: each frame closes a
 * fraction of the backlog, so a big chunk flows in quickly and a trickle still arrives a word at a time
 */
function useReveal(text: string, live: boolean): number {
  const [shown, setShown] = useState(() => (live ? 0 : text.length));
  const limit = revealLimit(text, live);

  useEffect(() => {
    if (shown >= limit) return;
    const frame = requestAnimationFrame(() => {
      const step = Math.max(2, Math.ceil((limit - shown) / 12));
      setShown(wordEnd(text, Math.min(limit, shown + step), limit));
    });
    return () => cancelAnimationFrame(frame);
  }, [text, shown, limit]);

  return Math.min(shown, limit);
}

/** Whether `text` ends inside a code fence that hasn't been closed yet */
const insideFence = (text: string) => (text.match(/^ {0,3}(```|~~~)/gm)?.length ?? 0) % 2 === 1;

/** Closes a code fence, inline code or bold run that's still streaming, so it renders styled, not as raw markers */
function closeOpenMarkdown(text: string): string {
  if (insideFence(text)) return text.endsWith("\n") ? `${text}\`\`\`` : `${text}\n\`\`\``;

  // Closers have to touch the last word; "**bold **" doesn't close
  const body = text.trimEnd();
  const paragraph = body.slice(body.lastIndexOf("\n\n") + 1);
  // Backticks inside a finished code block don't open anything
  if (/^ {0,3}(```|~~~)/m.test(paragraph)) return text;
  let closers = "";
  if ((paragraph.match(/`/g)?.length ?? 0) % 2 === 1) closers += "`";
  if ((paragraph.match(/\*\*/g)?.length ?? 0) % 2 === 1) closers += "**";
  return body + closers + text.slice(body.length);
}

function splitWords(children: ElementContent[]): ElementContent[] {
  return children.flatMap((child): ElementContent[] => {
    if (child.type === "element") {
      child.children = splitWords(child.children);
      return [child];
    }
    if (child.type !== "text") return [child];
    return child.value
      .split(/(\s+)/)
      .filter(Boolean)
      .map((piece) =>
        /^\s+$/.test(piece)
          ? { type: "text", value: piece }
          : { type: "element", tagName: "span", properties: { className: ["w"] }, children: [{ type: "text", value: piece }] },
      );
  });
}

/**
 * Rehype plugin: wraps every word in its own span. React keeps the spans already on screen as the text grows,
 * so only newly revealed words mount and play the fade-in
 */
function rehypeWords() {
  return (tree: Root) => {
    tree.children = splitWords(tree.children as ElementContent[]);
  };
}

const remarkPlugins = [remarkGfm, remarkLinkify];
// Code is highlighted first, so the word spans split its tokens like any other text. Blocks without a language
// stay plain, as do languages outside highlight.js's common set
const rehypePlugins: Options["rehypePlugins"] = [rehypeHighlight, rehypeWords];

const components: Components = {
  pre: CodeBlock,
  // A plain link would navigate the app's webview away; open it in the browser instead
  a: ({ href, children }) => {
    const url = href && externalUrl(href);
    return (
      <a
        href={url || href}
        onClick={(event) => {
          event.preventDefault();
          if (url) openUrl(url).catch(() => {});
        }}
      >
        {children}
      </a>
    );
  },
};

type Props = {
  text: string;
  live: boolean;
  /** Renderers to use in place of the defaults, e.g. for special links; keep the object stable across renders */
  overrides?: Components;
};

export const MagicText = memo(function MagicText({ text, live, overrides }: Props) {
  const shown = useReveal(text, live);
  const merged = useMemo(() => (overrides ? { ...components, ...overrides } : components), [overrides]);
  const markdown = closeOpenMarkdown(text.slice(0, shown));
  // The fence closed above belongs to the code block still being written, which ends where the Markdown does
  const writingEnd = live && insideFence(text.slice(0, shown)) ? markdown.length : null;
  return (
    <div className="markdown">
      <WritingCode.Provider value={writingEnd}>
        <Markdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={merged}>
          {markdown}
        </Markdown>
      </WritingCode.Provider>
    </div>
  );
});
