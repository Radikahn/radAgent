import type { Source } from "./contract";

/** How a report is read, shared by the view, the PDF and the text export so they all number sources alike */

export type Section = { heading: string | null; body: string };

// Citations as the writer puts them: [S3], or occasionally [S3, S7]
const CITATION = /\[(S\d+(?:\s*[,;]\s*S\d+)*)\]/g;

const splitIds = (ids: string) => ids.split(/\s*[,;]\s*/);

/** The number a source is cited by, e.g. "3" for "S3" */
export const sourceNumber = (id: string) => id.slice(1);

/** Splits the report at its `##` headings; the `#` title and the summary under it come first */
export function parseReport(text: string): { title: string | null; sections: Section[] } {
  let title: string | null = null;
  const sections: Section[] = [{ heading: null, body: "" }];
  for (const line of text.split("\n")) {
    const heading = /^(#{1,2})\s+(.+)/.exec(line);
    if (heading?.[1] === "#" && title === null && sections.length === 1 && !sections[0].body.trim()) {
      title = heading[2].trim();
    } else if (heading?.[1] === "##") {
      sections.push({ heading: heading[2].trim(), body: "" });
    } else {
      sections[sections.length - 1].body += `${line}\n`;
    }
  }
  return { title, sections: sections.filter((section) => section.heading !== null || section.body.trim()) };
}

/** The sources a section cites, in the order it first cites them; ids the writer made up are left out */
export function citedIds(body: string, known: Map<string, Source>): string[] {
  const ids: string[] = [];
  for (const match of body.matchAll(CITATION)) {
    for (const id of splitIds(match[1])) {
      if (known.has(id) && !ids.includes(id)) ids.push(id);
    }
  }
  return ids;
}

/** Turns each [S3] into a `#cite-S3` link, which the renderers draw as a superscript; made-up ids are dropped */
export function linkCitations(body: string, known: Map<string, Source>): string {
  return body.replace(CITATION, (_, ids: string) =>
    splitIds(ids)
      .filter((id) => known.has(id))
      .map((id) => `[${sourceNumber(id)}](#cite-${id})`)
      .join(""),
  );
}

/** Turns each [S3] into a plain [3], for text that has no links */
export function numberCitations(body: string, known: Map<string, Source>): string {
  return body.replace(CITATION, (_, ids: string) =>
    splitIds(ids)
      .filter((id) => known.has(id))
      .map((id) => `[${sourceNumber(id)}]`)
      .join(""),
  );
}
