// `/` search: finds text across the word spans MagicText splits replies into, and highlights it without touching the DOM

import { VIM_UI } from "./dom";

const SKIP = `script, style, svg, [aria-hidden=true], ${VIM_UI}`;

// Text in different blocks never runs together into one match
const BLOCK = "p, li, pre, h1, h2, h3, h4, h5, h6, td, th, blockquote, summary, button, div, section, article, header, footer";

/** Vim's smartcase: a query with a capital letter matches case exactly, otherwise case is ignored */
export const isCaseSensitive = (query: string) => /[A-Z]/.test(query);

/** Every rendered match of `query` under `root`, in document order */
export function findAll(root: Element, query: string): Range[] {
  if (!query) return [];
  const exact = isCaseSensitive(query);
  const needle = exact ? query : query.toLowerCase();

  const nodes: Text[] = [];
  const starts: number[] = [];
  let text = "";
  let block: Element | null = null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement?.closest(SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement?.closest(BLOCK) ?? null;
    if (parent !== block) {
      text += "\n";
      block = parent;
    }
    nodes.push(node as Text);
    starts.push(text.length);
    text += (node as Text).data;
  }

  const haystack = exact ? text : text.toLowerCase();
  // The text node holding character `offset`, by binary search over where each node starts
  const locate = (offset: number): [Text, number] => {
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (starts[middle] <= offset) low = middle;
      else high = middle - 1;
    }
    return [nodes[low], Math.min(offset - starts[low], nodes[low].data.length)];
  };

  const ranges: Range[] = [];
  for (let at = haystack.indexOf(needle); at >= 0; at = haystack.indexOf(needle, at + needle.length)) {
    const range = document.createRange();
    range.setStart(...locate(at));
    range.setEnd(...locate(at + needle.length - 1));
    range.setEnd(range.endContainer, range.endOffset + 1);
    // Text in a closed <details> or a hidden element can't be shown, so it isn't a match
    if (range.getClientRects().length) ranges.push(range);
  }
  return ranges;
}

/** The match to go to from `from`: the first one after it, or before it going backwards, wrapping around the ends */
export function nextMatch(matches: Range[], from: Range, backwards: boolean): { index: number; wrapped: boolean } {
  if (backwards) {
    for (let index = matches.length - 1; index >= 0; index--) {
      if (matches[index].compareBoundaryPoints(Range.START_TO_START, from) < 0) return { index, wrapped: false };
    }
    return { index: matches.length - 1, wrapped: true };
  }
  const index = matches.findIndex((match) => match.compareBoundaryPoints(Range.START_TO_START, from) > 0);
  return index < 0 ? { index: 0, wrapped: true } : { index, wrapped: false };
}

// The CSS Custom Highlight API paints ranges without wrapping them in elements, so React's DOM is left alone
const highlights = typeof CSS !== "undefined" && "highlights" in CSS ? CSS.highlights : null;

export function highlight(matches: Range[], current: Range | null) {
  if (!highlights) return;
  highlights.set("vim-search", new Highlight(...matches));
  if (current) highlights.set("vim-search-current", new Highlight(current));
  else highlights.delete("vim-search-current");
}

export function clearHighlight() {
  highlights?.delete("vim-search");
  highlights?.delete("vim-search-current");
}
