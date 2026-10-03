import { memo } from "react";
import type { AgentState, PageView, View } from "./state";
import { displayUrl, External, Favicon, hostname, PlatformIcon, PLATFORM_LABELS } from "./parts";

// Each agent's accent, so its window, notes and badges read as one; cycles past five agents
const HUES = [214, 152, 32, 282, 348];

export const agentHue = (index: number) => HUES[index % HUES.length];

function statusLabel(agent: AgentState): string {
  switch (agent.status) {
    case "starting":
      return "Starting";
    case "thinking":
      return "Thinking";
    case "searching":
      return "Searching";
    case "reading":
      return agent.view.kind === "page" && agent.view.status === "loading" ? "Opening" : "Reading";
    case "done":
      return "Done";
    case "failed":
      return "Failed";
  }
}

function AddressBar({ view }: { view: View }) {
  if (view.kind === "page") {
    const { host, rest } = displayUrl(view.finalUrl ?? view.url);
    return (
      <div className="window-address">
        <Favicon url={view.finalUrl ?? view.url} size={12} />
        <span className="address-text">
          <span className="address-host">{host}</span>
          {rest}
        </span>
        {view.status === "loading" && <span className="address-progress" />}
      </div>
    );
  }
  if (view.kind === "search") {
    return (
      <div className="window-address">
        <svg className="address-icon" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="7" cy="7" r="4.25" />
          <path d="m10.25 10.25 3.25 3.25" />
        </svg>
        <span className="address-text">{view.query}</span>
        {view.hits === null && <span className="address-progress" />}
      </div>
    );
  }
  return (
    <div className="window-address">
      <span className="address-text address-blank">New tab</span>
    </div>
  );
}

function SearchScreen({ view }: { view: Extract<View, { kind: "search" }> }) {
  return (
    <div className="screen screen-search">
      <div className="search-box">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="7" cy="7" r="4.25" />
          <path d="m10.25 10.25 3.25 3.25" />
        </svg>
        <span className="search-query">{view.query}</span>
      </div>
      {view.hits === null ? (
        <div className="search-hits">
          {[0, 1, 2, 3].map((row) => (
            <div key={row} className="search-hit skeleton" style={{ animationDelay: `${row * 120}ms` }}>
              <span className="skeleton-line" />
              <span className="skeleton-line short" />
            </div>
          ))}
        </div>
      ) : view.hits.length === 0 ? (
        <p className="screen-message">No results</p>
      ) : (
        <div className="search-hits">
          {view.hits.map((hit, index) => (
            <div key={hit.url} className="search-hit" style={{ animationDelay: `${index * 70}ms` }}>
              <Favicon url={hit.url} size={14} />
              <div className="search-hit-body">
                <span className="search-hit-title">{hit.title || hostname(hit.url)}</span>
                <span className="search-hit-url">
                  {hostname(hit.url)}
                  {hit.published && ` · ${hit.published}`}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PageScreen({ view, live }: { view: PageView; live: boolean }) {
  if (view.status === "loading") {
    return (
      <div className="screen screen-loading">
        <Favicon url={view.url} size={28} />
        <span className="screen-message shimmer">Opening {hostname(view.url)}</span>
      </div>
    );
  }
  if (view.status === "failed") {
    return (
      <div className="screen screen-failed">
        <Favicon url={view.url} size={28} />
        <span className="screen-message">Couldn't open {hostname(view.url)}</span>
        {view.error && <span className="screen-error">{view.error.split("\n")[0]}</span>}
      </div>
    );
  }
  if (!view.screenshot) {
    // No picture of it (a PDF, or a page only a plain fetch could read): show its text as a sheet of paper
    return (
      <div className={`screen screen-sheet ${live ? "reading" : ""}`}>
        <div className="sheet">
          <span className={`sheet-kind ${view.pdf ? "pdf" : ""}`}>{view.pdf ? "PDF" : "Text only"}</span>
          <span className="sheet-title">{view.title}</span>
          <p className="sheet-text">{view.excerpt}</p>
        </div>
      </div>
    );
  }
  // The screenshot pans down the page while it's being read, like eyes moving down it
  return (
    <div
      className={`screen screen-page ${live ? "reading" : ""}`}
      style={{ backgroundImage: `url("${view.screenshot}")` }}
      role="img"
      aria-label={view.title}
    />
  );
}

function Screen({ view, live }: { view: View; live: boolean }) {
  switch (view.kind) {
    case "search":
      return <SearchScreen view={view} />;
    case "page":
      return <PageScreen view={view} live={live} />;
    default:
      return (
        <div className="screen screen-loading">
          <span className="screen-message shimmer">Getting started</span>
        </div>
      );
  }
}

const viewKey = (view: View) =>
  view.kind === "page" ? `page:${view.url}:${view.status}` : view.kind === "search" ? `search:${view.query}` : "blank";

type Props = { agent: AgentState; hue: number; live: boolean; focused: boolean; onFocus: () => void };

/** One agent's browser window: what it's looking at, what it's saying, and what it has noted */
export const AgentWindow = memo(function AgentWindow({ agent, hue, live, focused, onFocus }: Props) {
  const { plan, view, notes } = agent;
  const working = live && agent.status !== "done" && agent.status !== "failed";
  const latestNote = notes[notes.length - 1];
  const viewing = view.kind === "page" && view.status === "loaded" ? view.finalUrl ?? view.url : null;

  return (
    <article
      className={`window status-${agent.status} ${focused ? "focused" : ""}`}
      style={{ ["--hue" as string]: hue }}
      aria-label={`${plan.name} agent`}
    >
      <header className="window-bar" onClick={onFocus} title={focused ? "Shrink" : "Enlarge"}>
        <span className="window-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="window-name">{plan.name}</span>
        <span className="window-platform">
          <PlatformIcon platform={plan.platform} />
          {PLATFORM_LABELS[plan.platform]}
        </span>
      </header>

      <AddressBar view={view} />

      <div className="window-viewport">
        {/* Keyed so each new page or search condenses in rather than swapping abruptly */}
        <div key={viewKey(view)} className="window-screen materialize">
          <Screen view={view} live={working} />
        </div>

        {latestNote && working && (
          <div key={notes.length} className="window-toast">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 13h2.5L13 5.5 10.5 3 3 10.5zM9.25 4.25l2.5 2.5" />
            </svg>
            <span>{latestNote.text}</span>
          </div>
        )}

        {!live && agent.status === "done" && (
          <div className="window-done">
            {notes.length} {notes.length === 1 ? "note" : "notes"} from {agent.pages.filter((page) => page.status === "loaded").length} pages
          </div>
        )}

        {viewing && (
          <External href={viewing} className="window-open" title="Open this page in your browser">
            ↗
          </External>
        )}
      </div>

      <footer className="window-status">
        <span key={statusLabel(agent)} className={`window-state materialize ${working ? "shimmer" : ""}`}>
          {statusLabel(agent)}
        </span>
        <span className="window-thought" title={agent.error || agent.thought || plan.brief}>
          {agent.error || agent.thought || plan.brief}
        </span>
        <span className="window-counts">
          <span title="Searches">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7" cy="7" r="4.25" />
              <path d="m10.25 10.25 3.25 3.25" />
            </svg>
            {agent.queries.length}
          </span>
          <span title="Pages read">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 2.5h5.5L12.5 5.5v8H4zM9.5 2.5v3h3" />
            </svg>
            {agent.pages.length}
          </span>
          <span title="Notes">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 13h2.5L13 5.5 10.5 3 3 10.5zM9.25 4.25l2.5 2.5" />
            </svg>
            {notes.length}
          </span>
        </span>
      </footer>
    </article>
  );
});
