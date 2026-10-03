import { openUrl } from "@tauri-apps/plugin-opener";
import type { Place, PlacesCard } from "./contract";
import { External, hostname } from "./External";
import { StaticMap } from "./StaticMap";

const MAP_WIDTH = 264;
const MAP_HEIGHT = 132;
const USES_MILES = ["en-US", "en-LR", "my-MM"].includes(navigator.language);

function formatDistance(meters: number): string {
  if (USES_MILES) {
    const miles = meters / 1609.344;
    return miles < 0.1 ? `${Math.round(meters * 3.281)} ft` : `${miles.toFixed(miles < 10 ? 1 : 0)} mi`;
  }
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(meters < 10_000 ? 1 : 0)} km`;
}

function PlaceTile({ place }: { place: Place }) {
  const meta = [place.category, place.distance_m !== null && formatDistance(place.distance_m)].filter(Boolean);

  return (
    <article className="place">
      <button
        type="button"
        className="place-map"
        onClick={() => openUrl(place.links.apple_maps).catch(() => {})}
        title="Open in Maps"
      >
        <StaticMap location={place.location} width={MAP_WIDTH} height={MAP_HEIGHT} label={place.name} />
      </button>

      <div className="place-body">
        <h3 className="place-name" title={place.name}>
          {place.name}
        </h3>
        <p className="place-meta">{meta.join(" · ")}</p>
        {place.address && <p className="place-line">{place.address}</p>}
        {place.opening_hours && (
          <p className="place-line place-hours" title={place.opening_hours}>
            {place.opening_hours.split(/;\s*/).join("\n")}
          </p>
        )}
        {(place.phone || place.website) && (
          <p className="place-line place-contact">
            {place.phone && <External href={`tel:${place.phone.replace(/[^\d+]/g, "")}`}>{place.phone}</External>}
            {place.website && <External href={place.website}>{hostname(place.website)}</External>}
          </p>
        )}
      </div>

      <footer className="place-actions">
        <External href={place.links.apple_maps} className="place-action">
          Apple Maps
        </External>
        <External href={place.links.google_maps} className="place-action">
          Google Maps
        </External>
        <External href={place.links.osm} className="place-action">
          OSM
        </External>
      </footer>
    </article>
  );
}

export function PlacesCardView({ card }: { card: PlacesCard }) {
  if (card.places.length === 0) return null;
  const count = `${card.places.length} ${card.places.length === 1 ? "place" : "places"}`;

  return (
    <section className="places-card" aria-label={`Places for ${card.query}`}>
      <header className="places-header">
        <span>{count}</span>
        <span className="places-query">
          {card.query}
          {card.near && ` near ${card.near.label}`}
        </span>
      </header>
      <div className="places-strip">
        {card.places.map((place) => (
          <PlaceTile key={place.id} place={place} />
        ))}
      </div>
      <p className="places-attribution">{card.attribution}</p>
    </section>
  );
}
