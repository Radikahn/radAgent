import type { LatLon } from "./contract";

const TILE = 256;
// OpenStreetMap's own tiles, matching where the places come from; dark mode inverts them in cards.css
const TILE_URL = (z: number, x: number, y: number) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;

/** Web Mercator position of a point in pixels at `zoom` */
function project({ lat, lon }: LatLon, zoom: number): { x: number; y: number } {
  const scale = TILE * 2 ** zoom;
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

type Props = { location: LatLon; width: number; height: number; zoom?: number; label: string };

/** A map snippet centered on `location` with a pin, stitched from raster tiles so no map library is needed */
export function StaticMap({ location, width, height, zoom = 16, label }: Props) {
  const center = project(location, zoom);
  const left = center.x - width / 2;
  const top = center.y - height / 2;
  const tilesPerSide = 2 ** zoom;

  const tiles = [];
  for (let x = Math.floor(left / TILE); x <= Math.floor((left + width) / TILE); x++) {
    for (let y = Math.floor(top / TILE); y <= Math.floor((top + height) / TILE); y++) {
      if (y < 0 || y >= tilesPerSide) continue;
      // Wrap across the antimeridian
      const wrappedX = ((x % tilesPerSide) + tilesPerSide) % tilesPerSide;
      tiles.push(
        <img
          key={`${x}/${y}`}
          src={TILE_URL(zoom, wrappedX, y)}
          alt=""
          draggable={false}
          style={{ left: x * TILE - left, top: y * TILE - top, width: TILE, height: TILE }}
        />,
      );
    }
  }

  return (
    <div className="static-map" style={{ width, height }} role="img" aria-label={`Map showing ${label}`}>
      {tiles}
      <svg className="map-pin" viewBox="0 0 24 32" aria-hidden="true">
        <path d="M12 31s10-10.2 10-18.5C22 6.2 17.5 1 12 1S2 6.2 2 12.5C2 20.8 12 31 12 31Z" />
        <circle cx="12" cy="12.5" r="4" />
      </svg>
    </div>
  );
}
