// Card payloads tools send inside `card` events; keep in step with agent/src/radagent/cards.py

export type LatLon = { lat: number; lon: number };

export type Place = {
  /** Stable across searches, e.g. "osm:node:314461102" */
  id: string;
  name: string;
  /** Human readable, e.g. "Cafe" or "Fast food" */
  category: string;
  address: string | null;
  location: LatLon;
  /** From the search center; null when the search had no `near` */
  distance_m: number | null;
  phone: string | null;
  website: string | null;
  /** OpenStreetMap syntax, e.g. "Mo-Fr 09:00-20:30; Sa-Su 09:00-19:00" */
  opening_hours: string | null;
  links: { osm: string; google_maps: string; apple_maps: string };
};

export type PlacesCard = {
  card: "places";
  version: 1;
  query: string;
  near: { label: string; location: LatLon } | null;
  places: Place[];
  attribution: string;
};

export type SharedLink = {
  /** Absolute http(s) URL */
  url: string;
  title: string;
  /** One line on what's there */
  note: string | null;
};

export type LinksCard = {
  card: "links";
  version: 1;
  links: SharedLink[];
};

export type Video = {
  /** YouTube video id */
  id: string;
  /** https://www.youtube.com/watch?v=<id> */
  url: string;
  title: string;
  channel: string | null;
  /** As YouTube shows it, e.g. "11:53"; null while live */
  duration: string | null;
  /** As YouTube shows it, e.g. "3.3M views" */
  views: string | null;
  /** As YouTube shows it, e.g. "2 years ago" */
  published: string | null;
  live: boolean;
  /** 320x180 JPEG on i.ytimg.com */
  thumbnail: string;
};

export type VideosCard = {
  card: "videos";
  version: 1;
  query: string;
  videos: Video[];
};

export type SpotifyItem = {
  /** e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh" */
  uri: string;
  /** https://open.spotify.com/<kind>/<id>; null for local files in a playlist */
  url: string | null;
  /** "track", "album", "artist", "playlist", "show", "episode", "audiobook" or "chapter" */
  kind: string;
  title: string;
  /** e.g. "Daft Punk · Discovery" or "Playlist · by Radman" */
  subtitle: string | null;
  /** Short and right-aligned, e.g. "3:44" or "12 songs" */
  detail: string | null;
  /** Cover art on Spotify's CDN (*.scdn.co, *.spotifycdn.com) */
  image: string | null;
  /** The item playing right now */
  playing: boolean;
};

export type SpotifyCard = {
  card: "spotify";
  version: 1;
  /** What the list is, e.g. "8 results" or "Playing on MacBook" */
  title: string;
  /** e.g. the search query, or "1–20 of 1,204" */
  subtitle: string | null;
  items: SpotifyItem[];
};

export type Card = PlacesCard | LinksCard | VideosCard | SpotifyCard;

/** Cards arrive untyped over the bridge; anything with an unknown kind or version is ignored rather than guessed at */
export function isPlacesCard(card: unknown): card is PlacesCard {
  if (typeof card !== "object" || card === null) return false;
  const value = card as Record<string, unknown>;
  return value.card === "places" && value.version === 1 && Array.isArray(value.places);
}

export function isLinksCard(card: unknown): card is LinksCard {
  if (typeof card !== "object" || card === null) return false;
  const value = card as Record<string, unknown>;
  return value.card === "links" && value.version === 1 && Array.isArray(value.links);
}

export function isVideosCard(card: unknown): card is VideosCard {
  if (typeof card !== "object" || card === null) return false;
  const value = card as Record<string, unknown>;
  return value.card === "videos" && value.version === 1 && Array.isArray(value.videos);
}

export function isSpotifyCard(card: unknown): card is SpotifyCard {
  if (typeof card !== "object" || card === null) return false;
  const value = card as Record<string, unknown>;
  return value.card === "spotify" && value.version === 1 && Array.isArray(value.items);
}
