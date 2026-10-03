import { isLinksCard, isPlacesCard, isSpotifyCard, isVideosCard } from "./contract";
import { LinksCardView } from "./LinksCard";
import { PlacesCardView } from "./PlacesCard";
import { SpotifyCardView } from "./SpotifyCard";
import { VideosCardView } from "./VideosCard";
import "./cards.css";

export type { Card } from "./contract";

/** Renders whatever card a tool sent; kinds this client doesn't know yet render nothing */
export function CardView({ card }: { card: unknown }) {
  if (isPlacesCard(card)) return <PlacesCardView card={card} />;
  if (isLinksCard(card)) return <LinksCardView card={card} />;
  if (isVideosCard(card)) return <VideosCardView card={card} />;
  if (isSpotifyCard(card)) return <SpotifyCardView card={card} />;
  return null;
}
