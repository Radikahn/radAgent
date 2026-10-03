import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "./contract";
import { citedIds, linkCitations, parseReport, sourceNumber } from "./parse";
import { hostname } from "./parts";
import "./print.css";

/** A finished report, as the exports need it */
export type ExportableReport = {
  title: string;
  /** The writer's Markdown, citing sources as [S1], [S2], ... */
  text: string;
  sources: Source[];
  agents: number;
  /** The day the research ran, e.g. "2026-10-02"; reports saved before runs were dated have none */
  date?: string;
};

export function formatDate(date: string | undefined): string {
  const day = date ? new Date(`${date}T00:00:00`) : new Date();
  return day.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

const remarkPlugins = [remarkGfm];

/**
 * The report laid out for paper: what the print panel turns into a PDF. It renders outside the app (see
 * exportReport.ts), in plain dark-on-white whatever the app's theme, with every citation a working link
 */
export function PrintSheet({ report }: { report: ExportableReport }) {
  const known = new Map(report.sources.map((source) => [source.id, source]));
  const { sections } = parseReport(report.text);

  const components: Components = {
    a: ({ href, children }) => {
      const source = href?.startsWith("#cite-") ? known.get(href.slice(6)) : undefined;
      if (source) {
        // Bracketed, so citations side by side read as [1][3] rather than running together as 13
        return (
          <sup className="print-cite">
            <a href={source.url}>[{children}]</a>
          </sup>
        );
      }
      return <a href={href}>{children}</a>;
    },
  };

  return (
    <article className="print-report">
      <header>
        <p className="print-kicker">Research report · {formatDate(report.date)}</p>
        <h1>{report.title}</h1>
        <p className="print-meta">
          {report.agents} research agents · {report.sources.length} sources
        </p>
      </header>

      {sections.map((section, index) => {
        const ids = citedIds(section.body, known);
        return (
          <section key={index} className={section.heading ? "print-section" : "print-section print-summary"}>
            {section.heading && <h2>{section.heading}</h2>}
            <Markdown remarkPlugins={remarkPlugins} components={components}>
              {linkCitations(section.body, known)}
            </Markdown>
            {ids.length > 0 && (
              <p className="print-cites">
                Sources:{" "}
                {ids.map((id, position) => {
                  const source = known.get(id)!;
                  return (
                    <span key={id}>
                      {position > 0 && " · "}
                      <a href={source.url}>
                        [{sourceNumber(id)}] {hostname(source.url)}
                      </a>
                    </span>
                  );
                })}
              </p>
            )}
          </section>
        );
      })}

      <section className="print-sources">
        <h2>Sources</h2>
        <ol>
          {report.sources.map((source) => (
            <li key={source.id} value={Number(sourceNumber(source.id))}>
              <a href={source.url}>{source.title}</a>
              {source.published && <span className="print-date"> ({source.published})</span>}
              <br />
              <span className="print-url">{source.url}</span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
