import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from strands import tool

from radagent.tools.spotify import catalog, editing, playback
from radagent.tools.spotify.catalog import PAGE_LIMIT, SEARCH_LIMIT, Result
from radagent.tools.spotify.client import SpotifyError


SearchType = Literal["track", "album", "artist", "playlist", "show", "episode", "audiobook"]
LibraryKind = Literal["tracks", "albums", "artists", "playlists", "shows", "episodes", "audiobooks",
                      "recently_played", "top_tracks", "top_artists"]
ItemKind = Literal["track", "album", "artist", "playlist", "show", "episode", "audiobook", "chapter"]
PlayerAction = Literal["play", "pause", "next", "previous", "seek", "volume", "shuffle", "repeat", "queue",
                       "transfer"]
PlaylistAction = Literal["create", "add", "remove", "replace", "reorder", "update"]

# Offsets past this are well beyond any library Spotify pages through
MAX_OFFSET: int = 10_000



async def _run(name: str, work: Callable[[], Result | str]) -> AsyncIterator[dict[str, Any]]:
    """Run a tool's requests off the event loop, then yield its card (when it has one) and its result"""
    try:
        outcome = await asyncio.to_thread(work)
    except (SpotifyError, ValueError) as e:
        yield {"status": "error", "content": [{"text": f"{name} failed: {e}"}]}
        return
    except Exception as e:
        yield {"status": "error", "content": [{"text": f"{name} failed: {type(e).__name__}: {e}"}]}
        return

    card, text = outcome if isinstance(outcome, tuple) else (None, outcome)
    if card is not None and card["items"]:
        # The card goes to the client as a stream event; the last yield is the result the model sees
        yield card
    yield {"status": "success", "content": [{"text": text}]}


def _clamp(value: int, low: int, high: int) -> int:
    return min(max(value, low), high)



@tool
async def spotify_search(
    query: str,
    types: list[SearchType] | None = None,
    limit: int = 5,
    offset: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """Search Spotify for songs, albums, artists, playlists, podcasts (shows), episodes and audiobooks. Use it to find whatever the user wants to hear, save or put in a playlist, then hand the spotify: URIs from its results to the other spotify tools. The user sees the results as a Spotify card with cover art where each row opens in Spotify, so keep your reply short and don't list them again.

    The query takes Spotify's field filters: artist:, album:, track:, year: (a year or a range like 1990-1999), genre:, isrc:, upc:, tag:new (albums from the last two weeks) and tag:hipster (the least popular 10%). For an artist's popular songs, search tracks with artist:"Name" (this app can't use Spotify's top-tracks endpoint).

    Args:
        query: What to search for, e.g. "bohemian rhapsody" or 'artist:"Daft Punk" year:2001'.
        types: Which kinds of results to return; defaults to ["track"].
        limit: Results per kind, 1 to 10 (Spotify's cap for this app).
        offset: Skip this many results per kind, to see more.
    """
    query = " ".join(query.split())
    if not query:
        yield {"status": "error", "content": [{"text": "spotify_search needs a query."}]}
        return
    kinds = list(dict.fromkeys(types or ["track"]))
    work = lambda: catalog.search(query, kinds, _clamp(limit, 1, SEARCH_LIMIT), _clamp(offset, 0, 1_000))
    async for event in _run("spotify_search", work):
        yield event


@tool
async def spotify_library(
    kind: LibraryKind = "tracks",
    limit: int = 20,
    offset: int = 0,
    time_range: Literal["short_term", "medium_term", "long_term"] = "medium_term",
) -> AsyncIterator[dict[str, Any]]:
    """Look through the user's own Spotify: their liked songs, saved albums, followed artists, playlists (their own and ones they follow), saved podcasts, saved episodes, saved audiobooks, recently played songs, or their top songs and artists. Results carry spotify: URIs for the other spotify tools; playlists the user owns are marked as theirs. The user sees them as a Spotify card, so don't list them again unless asked.

    Args:
        kind: tracks (liked songs), albums, artists (followed), playlists, shows (podcasts), episodes, audiobooks, recently_played (the last 50 plays at most), top_tracks or top_artists.
        limit: How many to return, 1 to 50.
        offset: Skip this many, to page further (not for recently_played).
        time_range: For top_tracks and top_artists: short_term (about 4 weeks), medium_term (about 6 months) or long_term (about a year).
    """
    work = lambda: catalog.library(kind, _clamp(limit, 1, PAGE_LIMIT), _clamp(offset, 0, MAX_OFFSET), time_range)
    async for event in _run("spotify_library", work):
        yield event


@tool
async def spotify_lookup(
    item: str,
    kind: ItemKind | None = None,
    limit: int = 20,
    offset: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    """Open one Spotify item for its details and what's in it: a song, an album with its songs, an artist with their albums and singles, a playlist with its songs, a podcast with its episodes, an episode, an audiobook with its chapters, or a chapter. Use it for questions about something specific (what album is this on, how long is it, what's in this playlist) and to see a playlist's songs and their positions before editing it. The user sees it as a Spotify card, so don't repeat the list.

    Spotify only lists the songs of playlists the user owns or collaborates on; for anyone else's playlist you get its details but not its songs.

    Args:
        item: A spotify: URI or open.spotify.com link, e.g. one the user pasted or another spotify tool returned.
        kind: What `item` is, needed only when it's a bare 22-character ID.
        limit: How many songs, albums, episodes or chapters to list, 1 to 50.
        offset: Skip this many of them, to page further.
    """
    work = lambda: catalog.lookup(item, kind, _clamp(limit, 1, PAGE_LIMIT), _clamp(offset, 0, MAX_OFFSET))
    async for event in _run("spotify_lookup", work):
        yield event


@tool
async def spotify_now_playing(queue: bool = False) -> AsyncIterator[dict[str, Any]]:
    """See what's on the user's Spotify right now: the song or episode, whether it's playing or paused, how far in, the device and its volume, shuffle and repeat, and every device that has Spotify open (with IDs for spotify_player). Use it for "what's this song?", before relative changes like "turn it up", and to find where to play. The user sees what's playing as a Spotify card.

    Args:
        queue: Also list what plays next.
    """
    async for event in _run("spotify_now_playing", lambda: playback.now_playing(queue)):
        yield event


@tool
async def spotify_player(
    action: PlayerAction,
    uris: list[str] | None = None,
    context: str | None = None,
    start_at: int | str | None = None,
    position_ms: int | None = None,
    volume: int | None = None,
    volume_change: int | None = None,
    shuffle: bool | None = None,
    repeat: Literal["track", "context", "off"] | None = None,
    device: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Control Spotify playback on the user's devices (this needs Spotify Premium). Get URIs from spotify_search, spotify_library or spotify_lookup first.

    Actions:
    - play: with `uris`, play those songs or episodes; with `context`, play an album, playlist, artist or podcast, optionally from `start_at`; with neither, resume. `position_ms` starts partway in.
    - pause, next, previous.
    - seek: jump to `position_ms` in the current song.
    - volume: set `volume` (0 to 100), or change it by `volume_change` (e.g. 10 or -10).
    - shuffle: turn `shuffle` on (true) or off (false).
    - repeat: `repeat` "track" (this song), "context" (the album or playlist) or "off".
    - queue: add `uris` to the queue, after anything already queued.
    - transfer: move playback to `device`, keeping it playing or paused.

    Commands go to the active device unless `device` names another. Spotify can only reach devices that have it open; if none does, ask the user to open Spotify somewhere. To play several albums or playlists, play one and queue songs from the others.

    Args:
        action: What to do.
        uris: Songs or episodes (spotify: URIs or open.spotify.com links), for play and queue.
        context: An album, playlist, artist or show URI to play, for play.
        start_at: Where to start in `context`: a 0-based position (albums and playlists) or the URI of a song in it.
        position_ms: Milliseconds into the song, for play and seek.
        volume: The volume to set, 0 to 100.
        volume_change: How much to raise (positive) or lower (negative) the volume, in percentage points.
        shuffle: For shuffle: true or false.
        repeat: For repeat: track, context or off.
        device: The device to use, by name ("iPhone", "MacBook") or ID from spotify_now_playing; required for transfer.
    """
    work = lambda: playback.control(action, uris, context, start_at, position_ms, volume, volume_change, shuffle,
                                    repeat, device)
    async for event in _run("spotify_player", work):
        yield event


@tool
async def spotify_playlist(
    action: PlaylistAction,
    playlist: str | None = None,
    uris: list[str] | None = None,
    name: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    collaborative: bool | None = None,
    position: int | None = None,
    range_start: int | None = None,
    range_length: int | None = None,
    insert_before: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Create Spotify playlists for the user and edit the ones they own or collaborate on. Get song URIs from spotify_search, spotify_library or spotify_lookup first; spotify_lookup also shows a playlist's songs and their positions.

    Actions:
    - create: a new playlist called `name`, with an optional `description`, filled with `uris` when given. It's private unless `public` is true; `collaborative` ones are always private. The user sees it as a card.
    - add: add `uris` (songs or episodes) to `playlist`, at the end or at `position`.
    - remove: take every occurrence of `uris` out of `playlist`.
    - replace: make `uris` the whole of `playlist`; no `uris` empties it.
    - reorder: move `range_length` items (default 1) starting at `range_start` to just before `insert_before`.
    - update: change `playlist`'s `name`, `description`, `public` or `collaborative`.

    Positions count from 0. To delete a playlist (Spotify calls it unfollowing), use spotify_save with action "remove" on its URI.

    Args:
        action: What to do.
        playlist: The playlist's spotify: URI or open.spotify.com link; every action but create needs it.
        uris: Songs or episodes, as spotify: URIs or open.spotify.com links.
        name: The playlist's name, for create and update.
        description: The playlist's description, for create and update.
        public: Whether the playlist shows on the user's profile, for create and update.
        collaborative: Whether others the user invites can edit it, for create and update.
        position: Where to insert, for add; the end when omitted.
        range_start: The position of the first item to move, for reorder.
        range_length: How many items to move, for reorder.
        insert_before: The position to move them in front of, for reorder; use the playlist's length to move them to the end.
    """
    work = lambda: editing.playlist(action, playlist, uris, name, description, public, collaborative, position,
                                    range_start, range_length, insert_before)
    async for event in _run("spotify_playlist", work):
        yield event


@tool
async def spotify_save(
    action: Literal["save", "remove", "check"],
    items: list[str],
) -> AsyncIterator[dict[str, Any]]:
    """Save things to the user's Spotify library, take them out, or check whether they're there. Saving a song likes it (it goes in Liked Songs); saving an artist, user or playlist follows it; albums, podcasts, episodes and audiobooks are saved to the library. Removing a playlist the user owns deletes it from their library.

    Args:
        action: save, remove, or check (whether each item is saved or followed).
        items: spotify: URIs or open.spotify.com links, e.g. spotify:track:<id> or spotify:artist:<id>.
    """
    async for event in _run("spotify_save", lambda: editing.save(action, items)):
        yield event


@tool
async def spotify_api(
    method: Literal["GET", "POST", "PUT", "DELETE"],
    path: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Call any Spotify Web API endpoint as the user and get its raw JSON, for what the other spotify tools don't cover, e.g. the user's profile (GET /me), a playlist's cover art (GET /playlists/{id}/images) or an artist's compilations (GET /artists/{id}/albums?include_groups=compilation). Prefer the other spotify tools when one fits: their results are shaped for you and the user sees them as cards.

    The reference is https://developer.spotify.com/documentation/web-api. This app is in Spotify's Development Mode, which has lost: batch lookups (GET /tracks?ids=... and the like; fetch one at a time), browse categories, new releases and featured playlists, artist top tracks and related artists, recommendations, audio features, other users' profiles and playlists, and the per-type save, follow and check endpoints (use /me/library?uris=... instead). Playlist contents live under /playlists/{id}/items.

    Args:
        method: The HTTP method.
        path: The endpoint below https://api.spotify.com/v1, e.g. "/me/player/recently-played".
        query: Query parameters, e.g. {"limit": 10}.
        body: A JSON body, for POST and PUT endpoints that take one.
    """
    async for event in _run("spotify_api", lambda: editing.raw(method, path, query, body)):
        yield event
