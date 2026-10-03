import type { LinksCard, SharedLink } from "./contract";
import { External, hostname } from "./External";

function LinkRow({ link }: { link: SharedLink }) {
  const host = hostname(link.url);
  return (
    // The full URL shows on hover, so a title can't hide where a link really goes
    <External href={link.url} className="link-row" title={link.url}>
      <span className="link-mark" aria-hidden="true">
        {host.charAt(0)}
      </span>
      <span className="link-text">
        <span className="link-title">{link.title}</span>
        {link.note && <span className="link-note">{link.note}</span>}
        <span className="link-host">{host}</span>
      </span>
      <span className="link-arrow" aria-hidden="true">
        ↗
      </span>
    </External>
  );
}

export function LinksCardView({ card }: { card: LinksCard }) {
  // Only web links open; anything else in a card is dropped rather than handed to the system opener
  const links = card.links.filter((link) => /^https?:\/\//i.test(link.url));
  if (links.length === 0) return null;

  return (
    <nav className="links-card" aria-label="Links">
      {links.map((link) => (
        <LinkRow key={link.url} link={link} />
      ))}
    </nav>
  );
}
