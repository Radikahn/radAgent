import type { InlineCode, Link, Parents, PhrasingContent, Root, RootContent, Text } from "mdast";

// Bare domains only link with one of these endings: well-known ones that don't double as file extensions or
// words, so "agent.py", "README.md" or "look.at" stay plain text
const TLDS = [
  "com", "org", "net", "edu", "gov", "mil", "int", "info", "biz", "io", "ai", "dev", "app", "co", "me", "tv", "fm",
  "gg", "xyz", "tech", "site", "online", "store", "shop", "blog", "news", "cloud", "page", "wiki", "studio", "design",
  "us", "uk", "ca", "au", "nz", "ie", "de", "fr", "nl", "se", "dk", "fi", "es", "pt", "ch", "eu", "jp", "kr", "cn",
  "tw", "hk", "sg", "br", "mx", "ru", "za",
].join("|");

/**
 * A host with no scheme or "www.", e.g. "x.com/someone" or "maps.apple.com"; lowercase only, so names that
 * happen to look like hosts ("Terminal.app", "ASP.NET") don't become links
 */
const BARE_URL = String.raw`(?:[a-z\d](?:[a-z\d-]*[a-z\d])?\.)+(?:${TLDS})(?![\w-]|\.[a-z\d])(?::\d{1,5})?(?:[/?#][^\s<>]*)?`;

const BARE_URLS = new RegExp(BARE_URL, "g");
const WHOLE_BARE_URL = new RegExp(`^${BARE_URL}$`);
const WHOLE_URL = /^(?:https?:\/\/|www\.)[^\s<>]+$/i;
const HAS_SCHEME = /^[a-z][a-z\d+.-]*:/i;

/** A host glued to these is part of a longer word, path or email address rather than a link of its own */
const JOINED = /[\w@./:-]/;

const count = (text: string, char: string) => text.split(char).length - 1;

/** Drops what more likely ends the sentence than the URL: trailing punctuation, and a ")" the URL never opened */
function trimTrailing(url: string): string {
  let end = url.length;
  while (end > 0) {
    const char = url[end - 1];
    const unopened = char === ")" && count(url.slice(0, end), ")") > count(url.slice(0, end), "(");
    if (!/[.,:;!?'"*_~]/.test(char) && !unopened) break;
    end--;
  }
  return url.slice(0, end);
}

/** Where a link opens: as written when it has a scheme, over https when it's a bare host like "react.dev" */
export function externalUrl(href: string): string | undefined {
  if (HAS_SCHEME.test(href)) return href;
  if (href.startsWith("www.") || WHOLE_BARE_URL.test(href)) return `https://${href}`;
  return undefined;
}

function linkText(node: Text): PhrasingContent[] {
  const parts: PhrasingContent[] = [];
  let from = 0;
  for (const match of node.value.matchAll(BARE_URLS)) {
    if (match.index > 0 && JOINED.test(node.value[match.index - 1])) continue;
    const url = trimTrailing(match[0]);
    if (match.index > from) parts.push({ type: "text", value: node.value.slice(from, match.index) });
    parts.push({ type: "link", url: `https://${url}`, children: [{ type: "text", value: url }] });
    from = match.index + url.length;
  }
  if (!parts.length) return [node];
  if (from < node.value.length) parts.push({ type: "text", value: node.value.slice(from) });
  return parts;
}

function linkCode(node: InlineCode): Link {
  return { type: "link", url: externalUrl(node.value)!, children: [node] };
}

function linkify(node: Parents) {
  const children: RootContent[] = node.children;
  // Text only sits where phrasing content can, so swapping it for text and links keeps every parent valid
  node.children = children.flatMap((child): RootContent[] => {
    if (child.type === "text") return linkText(child);
    if (child.type === "inlineCode" && WHOLE_URL.test(child.value)) return [linkCode(child)];
    if ("children" in child && child.type !== "link" && child.type !== "linkReference") linkify(child);
    return [child];
  }) as typeof node.children;
}

/**
 * Remark plugin: links the URLs GFM leaves as plain text, which only links ones starting with a scheme or
 * "www.": bare domains like "x.com/someone", and inline code that's a whole URL like `https://example.com`
 */
export function remarkLinkify() {
  return (tree: Root) => linkify(tree);
}
