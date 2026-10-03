"""
Reading Spotify: catalog search, the user's library and listening, and single items with their contents

Each function returns the card the user sees and the text the model reads. Endpoints are the ones Development Mode
apps keep since February 2026: no batch lookups, artist top tracks, browse or other users' playlists, and search
returns at most 10 results per type
"""
from typing import Any

from radagent.cards import SpotifyCard, SpotifyItem
from radagent.tools.spotify.client import SpotifyError, call
from radagent.tools.spotify.items import about, clean, clip, count, duration, line, names, parse_ref, to_item


Result = tuple[SpotifyCard | None, str]

SEARCH_LIMIT: int = 10
PAGE_LIMIT: int = 50
# Followed artists page by cursor, so reaching an offset walks pages; this caps it at 1,000 artists
MAX_CURSOR_PAGES: int = 20
LONG_DESCRIPTION_CHARS: int = 600

CARD_NOTE: str = (
    "The user already sees these as a Spotify card with cover art (each row opens in Spotify), so don't list them "
    "again unless asked."
)
# Markets are the user's own, so results are what they can play
FROM_TOKEN: dict[str, str] = {"market": "from_token"}

_HEADINGS: dict[str, str] = {
    "track": "Songs", "album": "Albums", "artist": "Artists", "playlist": "Playlists", "show": "Podcasts",
    "episode": "Episodes", "audiobook": "Audiobooks",
}
_TIME_RANGES: dict[str, str] = {"short_term": "last 4 weeks", "medium_term": "last 6 months", "long_term": "last year"}

# kind: (path, the key each entry wraps its item in, card title)
_LIBRARY: dict[str, tuple[str, str | None, str]] = {
    "tracks": ("/me/tracks", "track", "Liked songs"),
    "albums": ("/me/albums", "album", "Saved albums"),
    "artists": ("/me/following", None, "Followed artists"),
    "playlists": ("/me/playlists", None, "Playlists"),
    "shows": ("/me/shows", "show", "Saved podcasts"),
    "episodes": ("/me/episodes", "episode", "Saved episodes"),
    "audiobooks": ("/me/audiobooks", "audiobook", "Saved audiobooks"),
    "recently_played": ("/me/player/recently-played", "track", "Recently played"),
    "top_tracks": ("/me/top/tracks", None, "Top songs"),
    "top_artists": ("/me/top/artists", None, "Top artists"),
}



def card(title: str, subtitle: str | None, items: list[SpotifyItem]) -> SpotifyCard:
    return {"card": "spotify", "version": 1, "title": title, "subtitle": subtitle, "items": items}


def _span(offset: int, shown: int, total: int | None) -> str:
    """e.g. "1–20 of 1,204" """
    end = f"{offset + 1}–{offset + shown}" if shown > 1 else f"{offset + 1}"
    return f"{end} of {total:,}" if isinstance(total, int) else end


def _more(offset: int, shown: int, total: int | None) -> str | None:
    if isinstance(total, int) and offset + shown < total:
        return f"{total - offset - shown:,} more with offset={offset + shown}."
    return None


def _resume(obj: dict[str, Any]) -> str | None:
    """Where the user left an episode or chapter"""
    point = obj.get("resume_point") or {}
    if point.get("fully_played"):
        return "played"
    position = duration(point.get("resume_position_ms"))
    return f"stopped at {position}" if position else None



# ---- Search ----

def search(query: str, types: list[str], limit: int, offset: int) -> Result:
    data = call("GET", "/search", {"q": query, "type": types, "limit": limit, "offset": offset, **FROM_TOKEN}) or {}

    rows: list[SpotifyItem] = []
    lines: list[str] = []
    more: list[str] = []
    for kind in types:
        page = data.get(kind + "s") or {}
        # Spotify leaves nulls in search results where items are unavailable
        found = [(obj, item) for obj in page.get("items") or [] if (item := to_item(obj))]
        if not found:
            continue
        lines.append(f"{_HEADINGS[kind]}:")
        for obj, item in found:
            rows.append(item)
            lines.append(line(len(rows), item))
            if kind in ("playlist", "show", "audiobook") and (description := about(obj)):
                lines.append(f"   {description}")
        if isinstance(page.get("total"), int) and page["total"] > offset + len(found):
            more.append(_HEADINGS[kind].lower())

    if not rows:
        return None, f"Nothing on Spotify matched {query!r}. Try other words or fewer filters."
    head = f"Found {count(len(rows), 'result')}. {CARD_NOTE}"
    if more:
        head += f" There are more {', '.join(more)} with offset={offset + limit}."
    return card(count(len(rows), "result") or "", query, rows), "\n".join([head, *lines])



# ---- The user's library ----

def _followed_artists(limit: int, offset: int) -> tuple[list[Any], int | None]:
    found: list[Any] = []
    after: str | None = None
    total: int | None = None
    for _ in range(MAX_CURSOR_PAGES):
        page = (call("GET", "/me/following", {"type": "artist", "limit": PAGE_LIMIT, "after": after}) or {})
        artists = page.get("artists") or {}
        total = artists.get("total", total)
        found += artists.get("items") or []
        after = (artists.get("cursors") or {}).get("after")
        if len(found) >= offset + limit or not after or not artists.get("items"):
            break
    return found[offset:offset + limit], total


def _library_notes(entry: dict[str, Any], obj: dict[str, Any], me: str | None) -> list[str | None]:
    notes: list[str | None] = []
    if isinstance(entry.get("added_at"), str):
        notes.append(f"saved {entry['added_at'][:10]}")
    if isinstance(entry.get("played_at"), str):
        notes.append(f"played {entry['played_at'][:16].replace('T', ' ')} UTC")
    if obj.get("type") == "playlist":
        if me and (obj.get("owner") or {}).get("id") == me:
            notes.append("the user's own")
        if obj.get("collaborative"):
            notes.append("collaborative")
        if isinstance(obj.get("public"), bool):
            notes.append("public" if obj["public"] else "private")
    if obj.get("type") in ("episode", "chapter"):
        notes.append(_resume(obj))
    return notes


def library(kind: str, limit: int, offset: int, time_range: str) -> Result:
    path, key, title = _LIBRARY[kind]
    if kind == "artists":
        entries, total = _followed_artists(limit, offset)
    else:
        query: dict[str, Any] = {"limit": limit, "offset": offset}
        if kind == "recently_played":
            # The last 50 plays, paged by time rather than offset
            query = {"limit": limit}
            offset = 0
        elif kind.startswith("top_"):
            query["time_range"] = time_range
            title = f"{title}, {_TIME_RANGES[time_range]}"
        page = call("GET", path, query) or {}
        entries, total = page.get("items") or [], page.get("total")
    # Marking the user's own playlists tells the model which ones it can edit
    me = (call("GET", "/me") or {}).get("id") if kind == "playlists" else None

    rows: list[SpotifyItem] = []
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        obj = entry[key] if key and isinstance(entry.get(key), dict) else entry
        if item := to_item(obj):
            rows.append(item)
            lines.append(line(offset + len(rows), item, *_library_notes(entry, obj, me)))

    if not rows:
        return None, f"Nothing in the user's {title.lower()}" + (f" past offset {offset}." if offset else ".")
    # Recently played has no total, so it's just counted
    span = _span(offset, len(rows), total) if isinstance(total, int) else None
    head = f"{title}, {span or count(len(rows), 'item')}. {CARD_NOTE}"
    if more := _more(offset, len(rows), total):
        head += f" {more}"
    return card(title, span, rows), "\n".join([head, *lines])



# ---- One item and its contents ----

def _contents(embedded: Any, path: str, limit: int, offset: int, query: dict[str, Any]) -> tuple[list[Any], int | None]:
    """A page of a collection's contents, from the first page Spotify embeds in the collection when that covers it"""
    if isinstance(embedded, dict) and isinstance(embedded.get("items"), list) and not embedded.get("offset"):
        items, total = embedded["items"], embedded.get("total")
        if offset + limit <= len(items) or (isinstance(total, int) and len(items) >= total):
            return items[offset:offset + limit], total
    page = call("GET", path, {**query, "limit": limit, "offset": offset}) or {}
    return page.get("items") or [], page.get("total")


def _collection(
    head: SpotifyItem,
    facts: list[str | None],
    label: str,
    entries: list[Any],
    total: int | None,
    offset: int,
    parent: dict[str, Any],
    unwrap: tuple[str, ...] = (),
) -> Result:
    """
    A collection's card (its own row, then its contents) and text (its facts, then numbered contents)

    Args:
        head: {SpotifyItem} The collection's own row
        facts: {list[str | None]} Lines about the collection; None lines are dropped
        label: {str} What the contents are, e.g. "Songs"
        entries: {list} The page of contents
        total: {int | None} How many there are in all
        offset: {int} Where the page starts
        parent: {dict} The collection, for the art and name simplified contents leave out
        unwrap: {tuple[str, ...]} Keys an entry may wrap its item in, e.g. a playlist's "item"
    """
    rows: list[SpotifyItem] = [head]
    lines: list[str] = []
    for number, entry in enumerate(entries, start = offset + 1):
        obj = next((entry[key] for key in unwrap if isinstance(entry, dict) and isinstance(entry.get(key), dict)),
                   entry)
        item = to_item(obj, parent = parent)
        if item is None:
            # Kept, so the numbers still match positions in the collection
            lines.append(f"{number}. (unavailable)")
            continue
        rows.append(item)
        lines.append(line(number, item, _resume(obj) if item["kind"] in ("episode", "chapter") else None))

    text = [fact for fact in facts if fact]
    if lines:
        text.append(f"{label} {_span(offset, len(entries), total)}:")
        text += lines
        if more := _more(offset, len(entries), total):
            text.append(more)
    text.append(CARD_NOTE)
    return card(head["title"], head["subtitle"], rows), "\n".join(text)


def _uris(objs: Any) -> str | None:
    found = [f"{clean(obj.get('name'))} {obj['uri']}" for obj in objs or [] if isinstance(obj, dict) and obj.get("uri")]
    return ", ".join(found) or None


def _head(obj: Any) -> SpotifyItem:
    """The looked-up item's own row"""
    item = to_item(obj)
    if item is None:
        raise SpotifyError(404, "Spotify returned nothing for that item")
    return item


def _single(obj: dict[str, Any], facts: list[str | None]) -> Result:
    item = _head(obj)
    text = [fact for fact in facts if fact] + [CARD_NOTE]
    return card(item["title"], item["subtitle"], [item]), "\n".join(text)


def lookup(ref: str, kind: str | None, limit: int, offset: int) -> Result:
    kind, item_id = parse_ref(ref, kind)

    if kind == "track":
        obj = call("GET", f"/tracks/{item_id}", FROM_TOKEN)
        album = obj.get("album") or {}
        return _single(obj, [
            f"Song: {clean(obj.get('name'))} {obj.get('uri')}",
            f"Artists: {_uris(obj.get('artists'))}",
            f"Album: {clean(album.get('name'))} ({album.get('album_type')}, released {album.get('release_date')}) "
            f"{album.get('uri')}",
            f"Track {obj.get('track_number')} on disc {obj.get('disc_number')}, {duration(obj.get('duration_ms'))}"
            + (", explicit" if obj.get("explicit") else ""),
            f"ISRC {isrc}" if (isrc := (obj.get("external_ids") or {}).get("isrc")) else None,
            "Not playable in the user's country" if obj.get("is_playable") is False else None,
        ])

    if kind == "album":
        obj = call("GET", f"/albums/{item_id}", FROM_TOKEN)
        entries, total = _contents(obj.get("tracks"), f"/albums/{item_id}/tracks", limit, offset, FROM_TOKEN)
        return _collection(_head(obj), [
            f"Album: {clean(obj.get('name'))} ({obj.get('album_type')}, released {obj.get('release_date')}, "
            f"{count(obj.get('total_tracks'), 'song')}) {obj.get('uri')}",
            f"Artists: {_uris(obj.get('artists'))}",
        ], "Songs", entries, total, offset, obj)

    if kind == "artist":
        obj = call("GET", f"/artists/{item_id}")
        page = call("GET", f"/artists/{item_id}/albums",
                    {"include_groups": "album,single", "limit": limit, "offset": offset, **FROM_TOKEN}) or {}
        return _collection(_head(obj), [
            f"Artist: {clean(obj.get('name'))} {obj.get('uri')}",
            f"Genres: {', '.join(obj['genres'])}" if obj.get("genres") else None,
            f"For their popular songs, spotify_search tracks with artist:\"{clean(obj.get('name'))}\".",
        ], "Albums and singles", page.get("items") or [], page.get("total"), offset, obj)

    if kind == "playlist":
        query = {**FROM_TOKEN, "additional_types": "track,episode"}
        obj = call("GET", f"/playlists/{item_id}", query)
        me = (call("GET", "/me") or {}).get("id")
        owner = obj.get("owner") or {}
        # Renamed from `tracks` to `items` in February 2026
        embedded = obj.get("items") if isinstance(obj.get("items"), dict) else obj.get("tracks")
        hidden = False
        try:
            entries, total = _contents(embedded, f"/playlists/{item_id}/items", limit, offset, query)
        except SpotifyError as e:
            if e.status != 403:
                raise
            entries, total, hidden = [], None, True
        flags = ["public" if obj.get("public") else "private", "collaborative" if obj.get("collaborative") else None,
                 count((embedded or {}).get("total"), "song")]
        return _collection(_head(obj), [
            f"Playlist: {clean(obj.get('name'))} ({', '.join(flag for flag in flags if flag)}) {obj.get('uri')}",
            "Owned by the user, who can edit it." if owner.get("id") == me
            else f"Owned by {clean(owner.get('display_name')) or owner.get('id')}"
                 + (" and collaborative, so the user can edit it." if obj.get("collaborative") else
                    "; the user can't edit it."),
            f"Description: {about(obj)}" if about(obj) else None,
            "Spotify only lists the songs of playlists the user owns or collaborates on, so this one's songs aren't "
            "available; it can still be played with spotify_player." if hidden else None,
            "Numbered from 1; spotify_playlist positions count from 0." if entries else None,
        ], "Songs", entries, total, offset, obj, unwrap = ("item", "track"))

    if kind == "show":
        obj = call("GET", f"/shows/{item_id}", FROM_TOKEN)
        entries, total = _contents(obj.get("episodes"), f"/shows/{item_id}/episodes", limit, offset, FROM_TOKEN)
        return _collection(_head(obj), [
            f"Podcast: {clean(obj.get('name'))} ({count(obj.get('total_episodes'), 'episode')}) {obj.get('uri')}",
            f"Description: {about(obj)}" if about(obj) else None,
        ], "Episodes (newest first)", entries, total, offset, obj)

    if kind == "episode":
        obj = call("GET", f"/episodes/{item_id}", FROM_TOKEN)
        show = obj.get("show") or {}
        return _single(obj, [
            f"Episode: {clean(obj.get('name'))} {obj.get('uri')}",
            f"Podcast: {clean(show.get('name'))} {show.get('uri')}",
            f"Released {obj.get('release_date')}, {duration(obj.get('duration_ms'))}"
            + (", explicit" if obj.get("explicit") else "") + (f", {resume}" if (resume := _resume(obj)) else ""),
            f"Description: {clip(clean(obj.get('description')), LONG_DESCRIPTION_CHARS)}"
            if obj.get("description") else None,
        ])

    if kind == "audiobook":
        obj = call("GET", f"/audiobooks/{item_id}", FROM_TOKEN)
        entries, total = _contents(obj.get("chapters"), f"/audiobooks/{item_id}/chapters", limit, offset, FROM_TOKEN)
        return _collection(_head(obj), [
            f"Audiobook: {clean(obj.get('name'))} by {names(obj.get('authors'))}, read by "
            f"{names(obj.get('narrators'))} ({count(obj.get('total_chapters'), 'chapter')}) {obj.get('uri')}",
            f"Description: {about(obj)}" if about(obj) else None,
        ], "Chapters", entries, total, offset, obj)

    if kind == "chapter":
        obj = call("GET", f"/chapters/{item_id}", FROM_TOKEN)
        book = obj.get("audiobook") or {}
        return _single(obj, [
            f"Chapter {obj.get('chapter_number')}: {clean(obj.get('name'))} {obj.get('uri')}",
            f"Audiobook: {clean(book.get('name'))} {book.get('uri')}",
            f"{duration(obj.get('duration_ms'))}" + (f", {resume}" if (resume := _resume(obj)) else ""),
        ])

    raise ValueError("Spotify no longer lets apps look up user profiles; spotify_api GET /me gives the user's own.")
