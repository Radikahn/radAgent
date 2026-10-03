"""
Cards are the data contract between agent tools and the desktop client

A tool shows the user a card by yielding a dict with a `card` kind and a `version` (the tool must be an async
generator; its last yield is still the result the model sees). Strands emits each yield as a tool stream event,
the server (radagent.server) forwards the cards among them to the client as `card` events, and the client picks a
renderer by kind. Cards stay out of the tool result on purpose: the harness offloads or rewrites large results,
and the model only needs a short summary

Keep these types in step with `client/src/cards/contract.ts`. Bump `version` on breaking changes
"""
from typing import Any, Literal, TypedDict


class LatLon(TypedDict):
    lat: float
    lon: float


class PlaceLinks(TypedDict):
    osm: str
    google_maps: str
    apple_maps: str


class Place(TypedDict):
    id: str                     # Stable across searches, e.g. "osm:node:314461102"
    name: str
    category: str               # Human readable, e.g. "Cafe" or "Fast food"
    address: str | None
    location: LatLon
    distance_m: int | None      # From the search center; None when the search had no `near`
    phone: str | None
    website: str | None
    opening_hours: str | None   # OpenStreetMap syntax, e.g. "Mo-Fr 09:00-20:30; Sa-Su 09:00-19:00"
    links: PlaceLinks


class SearchCenter(TypedDict):
    label: str
    location: LatLon


class PlacesCard(TypedDict):
    card: Literal["places"]
    version: Literal[1]
    query: str
    near: SearchCenter | None
    places: list[Place]
    attribution: str


class SharedLink(TypedDict):
    url: str                    # Absolute http(s) URL
    title: str
    note: str | None            # One line on what's there


class LinksCard(TypedDict):
    card: Literal["links"]
    version: Literal[1]
    links: list[SharedLink]


class Video(TypedDict):
    id: str                     # YouTube video id
    url: str                    # https://www.youtube.com/watch?v=<id>
    title: str
    channel: str | None
    duration: str | None        # As YouTube shows it, e.g. "11:53"; None while live
    views: str | None           # As YouTube shows it, e.g. "3.3M views"
    published: str | None       # As YouTube shows it, e.g. "2 years ago"
    live: bool
    thumbnail: str              # 320x180 JPEG on i.ytimg.com


class VideosCard(TypedDict):
    card: Literal["videos"]
    version: Literal[1]
    query: str
    videos: list[Video]


class SpotifyItem(TypedDict):
    uri: str                    # e.g. "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"
    url: str | None             # https://open.spotify.com/<kind>/<id>; None for local files in a playlist
    kind: str                   # "track", "album", "artist", "playlist", "show", "episode", "audiobook", "chapter"
    title: str
    subtitle: str | None        # e.g. "Daft Punk · Discovery" or "Playlist · by Radman"
    detail: str | None          # Short and right-aligned, e.g. "3:44" or "12 songs"
    image: str | None           # Cover art on Spotify's CDN (*.scdn.co, *.spotifycdn.com)
    playing: bool               # The item playing right now


class SpotifyCard(TypedDict):
    card: Literal["spotify"]
    version: Literal[1]
    title: str                  # What the list is, e.g. "8 results" or "Playing on MacBook"
    subtitle: str | None        # e.g. the search query, or "20 of 1,204"
    items: list[SpotifyItem]



def is_card(data: Any) -> bool:
    """True when something a tool yielded is a card for the client rather than progress or its result"""
    return isinstance(data, dict) and isinstance(data.get("card"), str) and "version" in data
