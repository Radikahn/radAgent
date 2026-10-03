import { createContext, useContext, useEffect, useState, type ComponentProps } from "react";
import type { ExtraProps } from "react-markdown";
import type { Element, ElementContent } from "hast";
import { copyText } from "./clipboard";
import "./code.css";

/**
 * Where the code block still being written ends in the Markdown MagicText renders, while a reply streams; null when
 * every block is closed. That block says so in place of its copy button, which would copy half of it
 */
export const WritingCode = createContext<number | null>(null);

// How long the button says "Copied"
const COPIED_MS = 1600;

/** The code as written, from under the spans the highlighter and the word reveal split it into */
function textOf(node: ElementContent): string {
  if (node.type === "text") return node.value;
  return node.type === "element" ? node.children.map(textOf).join("") : "";
}

/** The file a fence names after its language, as in ```python src/app.py, or with title="…" or file=… */
function titleOf(meta: string | null | undefined): string | undefined {
  if (!meta) return undefined;
  const named = /\b(?:title|file(?:name)?)=(?:"([^"]*)"|'([^']*)'|(\S+))/.exec(meta);
  return (named ? (named[1] ?? named[2] ?? named[3]) : meta).trim() || undefined;
}

/**
 * A fenced code block in a reply: a header with its file's name or language and a copy button, over the
 * highlighted code. The labels are drawn by CSS from data-label, so they stay out of text that's selected, searched
 * or copied with the keyboard (yy)
 */
export function CodeBlock({ node, children, ...props }: ComponentProps<"pre"> & ExtraProps) {
  const writingEnd = useContext(WritingCode);
  const [copied, setCopied] = useState<"yes" | "failed" | null>(null);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(null), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  const code = node?.children.find((child): child is Element => child.type === "element" && child.tagName === "code");
  const classes = code?.properties.className;
  const language = (Array.isArray(classes) ? classes : [])
    .map(String)
    .find((name) => name.startsWith("language-"))
    ?.slice("language-".length);
  const title = titleOf(code?.data?.meta);
  const writing = writingEnd !== null && node?.position?.end.offset === writingEnd;

  function copy() {
    // The Markdown gives code a closing newline of its own
    const text = code ? textOf(code).replace(/\n$/, "") : "";
    copyText(text).then(
      () => setCopied("yes"),
      () => setCopied("failed"),
    );
  }

  const label = copied === "yes" ? "Copied" : copied === "failed" ? "Couldn't copy" : "Copy";
  return (
    <div className="code-block">
      <div className="code-head">
        {(title || language) && (
          <span className={`code-name ${title ? "code-file" : ""}`} data-label={title ?? language} title={title} />
        )}
        {title && language && <span className="code-language" data-label={language} />}
        {writing ? (
          <span className="code-writing shimmer">Writing</span>
        ) : (
          <button
            type="button"
            className={`code-copy ${copied ?? ""}`}
            onClick={copy}
            aria-label={copied ? label : "Copy code"}
            data-label={label}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              {copied === "yes" ? (
                <path d="M3.5 8.5l3 3 6-7" />
              ) : (
                <>
                  <rect x="5.5" y="5.5" width="8" height="8" rx="2" />
                  <path d="M10.5 3.5v-.25A1.75 1.75 0 0 0 8.75 1.5h-5.5A1.75 1.75 0 0 0 1.5 3.25v5.5c0 .97.78 1.75 1.75 1.75h.25" />
                </>
              )}
            </svg>
          </button>
        )}
      </div>
      <pre {...props}>{children}</pre>
    </div>
  );
}
