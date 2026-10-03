import type { SpotifyCard, SpotifyItem } from "./contract";
import { External } from "./External";

// Only Spotify's own links open; anything else in a card is shown but not handed to the system opener
const isSpotifyLink = (url: string | null): url is string => !!url && /^https:\/\/open\.spotify\.com\//i.test(url);

function SpotifyRow({ item }: { item: SpotifyItem }) {
  const round = item.kind === "artist" || item.kind === "user";
  const body = (
    <>
      <span className={round ? "spotify-art round" : "spotify-art"}>
        {item.image ? (
          <img src={item.image} alt="" loading="lazy" draggable={false} />
        ) : (
          <span aria-hidden="true">♪</span>
        )}
      </span>
      <span className="spotify-text">
        <span className="spotify-title">
          {item.playing && <span className="spotify-now" aria-label="Playing now" />}
          {item.title}
        </span>
        {item.subtitle && <span className="spotify-subtitle">{item.subtitle}</span>}
      </span>
      {item.detail && <span className="spotify-detail">{item.detail}</span>}
    </>
  );

  return isSpotifyLink(item.url) ? (
    // Opens in the Spotify app when it's installed, the web player otherwise
    <External href={item.url} className="spotify-row" title={item.title}>
      {body}
    </External>
  ) : (
    <div className="spotify-row">{body}</div>
  );
}

export function SpotifyCardView({ card }: { card: SpotifyCard }) {
  if (card.items.length === 0) return null;

  return (
    <section className="spotify-card" aria-label={card.title}>
      <header className="places-header">
        <span>{card.title}</span>
        {card.subtitle && <span className="places-query">{card.subtitle}</span>}
      </header>
      <div className="spotify-list">
        {card.items.map((item, index) => (
          // A playlist can hold the same song twice
          <SpotifyRow key={`${index}:${item.uri}`} item={item} />
        ))}
      </div>
    </section>
  );
}
