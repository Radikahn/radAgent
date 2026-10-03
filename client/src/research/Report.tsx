import { memo, useMemo } from "react";
import type { Components } from "react-markdown";
import { openUrl } from "@tauri-apps/plugin-opener";
import { MagicText } from "../chat/MagicText";
import type { AgentPlan, Source } from "./contract";
import { External, Favicon, hostname, PLATFORM_LABELS } from "./parts";
import { citedIds, linkCitations, parseReport } from "./parse";

function SourceBadge({ source, agent, hue }: { source: Source; agent?: AgentPlan; hue?: number }) {
  const foundBy = agent ? `\nFound by the ${agent.name} agent (${PLATFORM_LABELS[agent.platform]})` : "";
  return (
    <External
      href={source.url}
      className="source-badge materialize"
      title={`${source.title}\n${source.url}${foundBy}`}
    >
      <span className="badge-number" style={hue === undefined ? undefined : { ["--hue" as string]: hue }}>
        {source.id.slice(1)}
      </span>
      <Favicon url={source.url} size={14} />
      <span className="badge-host">{hostname(source.url)}</span>
      <span className="badge-title">{source.title}</span>
    </External>
  );
}

type Props = {
  text: string;
  sources: Source[];
  agents: AgentPlan[];
  hues: Map<string, number>;
  live: boolean;
};

/**
 * The finished (or still streaming) report: each section ends with badges linking to the sources it cites.
 * Its `#` title isn't drawn here; the research header shows it
 */
export const Report = memo(function Report({ text, sources, agents, hues, live }: Props) {
  const known = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const agentsById = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);
  const { sections } = parseReport(text);

  const overrides = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        const source = href?.startsWith("#cite-") ? known.get(href.slice(6)) : undefined;
        if (!source) return <>{children}</>;
        return (
          <sup className="cite">
            <a
              href={source.url}
              title={`${source.title}\n${hostname(source.url)}`}
              onClick={(event) => {
                event.preventDefault();
                openUrl(source.url).catch(() => {});
              }}
            >
              {children}
            </a>
          </sup>
        );
      },
    }),
    [known],
  );

  return (
    <article className="report">
      {sections.map((section, index) => {
        const ids = citedIds(section.body, known);
        return (
          // Sections only ever append, so the index is a stable key
          <section key={index} className={section.heading ? "report-section" : "report-section report-summary"}>
            {section.heading && <h2 className="materialize">{section.heading}</h2>}
            <MagicText
              text={linkCitations(section.body, known)}
              live={live && index === sections.length - 1}
              overrides={overrides}
            />
            {ids.length > 0 && (
              <div className="report-citations" aria-label="Sources for this section">
                {ids.map((id) => {
                  const source = known.get(id)!;
                  return <SourceBadge key={id} source={source} agent={agentsById.get(source.agent)} hue={hues.get(source.agent)} />;
                })}
              </div>
            )}
          </section>
        );
      })}

      {!live && sources.length > 0 && (
        <details className="report-sources">
          <summary>All {sources.length} sources</summary>
          <ol>
            {sources.map((source) => (
              <li key={source.id}>
                <External href={source.url} title={source.url}>
                  <Favicon url={source.url} size={14} />
                  <span className="badge-title">{source.title}</span>
                  <span className="badge-host">
                    {hostname(source.url)}
                    {source.published && ` · ${source.published}`}
                  </span>
                </External>
              </li>
            ))}
          </ol>
        </details>
      )}
    </article>
  );
});
