import { isLinksCard, isPlacesCard } from "./contract";
import { LinksCardView } from "./LinksCard";
import { PlacesCardView } from "./PlacesCard";
import "./cards.css";

export type { Card } from "./contract";

/** Renders whatever card a tool sent; kinds this client doesn't know yet render nothing */
export function CardView({ card }: { card: unknown }) {
  if (isPlacesCard(card)) return <PlacesCardView card={card} />;
  if (isLinksCard(card)) return <LinksCardView card={card} />;
  return null;
}
