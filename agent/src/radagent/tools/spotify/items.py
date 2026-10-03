"""
Spotify references in and card rows out: parsing the URIs, links and IDs the model passes, and shaping Spotify's
objects into what the user sees (a card row) and what the model reads (one numbered line ending in the item's URI)
"""
import html
import re
from typing import Any

from radagent.cards import SpotifyItem


KINDS: tuple[str, ...] = ("track", "album", "artist", "playlist", "show", "episode", "audiobook", "chapter", "user")
OPEN_URL: str = "https://open.spotify.com/{kind}/{id}"

_KIND = "|".join(KINDS)
_URI = re.compile(rf"\Aspotify:({_KIND}):([A-Za-z0-9._-]+)\Z")
# Shared links may carry a locale ("/intl-de/") or come from the embed player, and usually end in "?si=..."
_LINK = re.compile(rf"\Ahttps?://open\.spotify\.com/(?:intl-[A-Za-z-]+/)?(?:embed/)?({_KIND})/([A-Za-z0-9._-]+)")
_ID = re.compile(r"\A[A-Za-z0-9]{22}\Z")
_TAG = re.compile(r"<[^>]+>")

# Images closest above this width make the 40 px card art sharp on retina screens
ART_WIDTH: int = 120
DESCRIPTION_CHARS: int = 200



# ---- References ----

def _a(kind: str) -> str:
    return f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}"


def parse_ref(ref: str, kind: str | None = None) -> tuple[str, str]:
    """
    The (kind, id) a reference names

    Args:
        ref: {str} A spotify: URI, an open.spotify.com link, or a bare 22-character ID
        kind: {str | None} What a bare ID is; also what the reference has to be, when given

    Raises:
        ValueError: `ref` isn't a Spotify reference, or names a different kind
    """
    ref = ref.strip()
    match = _URI.match(ref) or _LINK.match(ref)
    if match:
        found, item_id = match.group(1), match.group(2)
    elif kind and _ID.match(ref):
        found, item_id = kind, ref
    elif _ID.match(ref):
        raise ValueError(f"{ref!r} is a bare ID; pass it as a URI like spotify:track:{ref} so its kind is known.")
    else:
        raise ValueError(
            f"{ref!r} isn't a Spotify URI or link (like spotify:track:<id>). Find it with spotify_search first.")
    if kind and found != kind:
        raise ValueError(f"{ref!r} is {_a(found)}, not {_a(kind)}.")
    return found, item_id


def to_uri(ref: str, kind: str | None = None, allowed: tuple[str, ...] | None = None) -> str:
    """
    The spotify: URI for a reference

    Args:
        ref: {str} A spotify: URI, an open.spotify.com link, or a bare ID
        kind: {str | None} What a bare ID is
        allowed: {tuple | None} The kinds that make sense where the URI goes

    Raises:
        ValueError: `ref` isn't a Spotify reference, or isn't one of `allowed`
    """
    # `kind` only says what a bare ID is; a URI or link names its own kind, which `allowed` then checks
    found, item_id = parse_ref(ref, kind if _ID.match(ref.strip()) else None)
    if allowed and found not in allowed:
        raise ValueError(f"{ref!r} is {_a(found)}; this takes {', '.join(allowed)} URIs.")
    return f"spotify:{found}:{item_id}"



# ---- Shaping ----

def clean(text: Any) -> str | None:
    """Spotify text on one line, without the HTML and entities playlist descriptions carry"""
    if not isinstance(text, str):
        return None
    return " ".join(html.unescape(_TAG.sub(" ", text)).split()) or None


def clip(text: str | None, limit: int = DESCRIPTION_CHARS) -> str | None:
    return text[:limit - 1].rstrip() + "…" if text and len(text) > limit else text


def duration(ms: Any) -> str | None:
    """3:44, or 1:02:09 for long episodes"""
    if not isinstance(ms, int) or ms <= 0:
        return None
    minutes, seconds = divmod(round(ms / 1000), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def count(number: Any, word: str) -> str | None:
    if not isinstance(number, int):
        return None
    return f"{number:,} {word}{'' if number == 1 else 's'}"


def names(people: Any) -> str | None:
    """The names in a list of artists, authors or narrators"""
    found = [clean(person.get("name")) for person in people or [] if isinstance(person, dict)]
    return ", ".join(name for name in found if name) or None


def art(images: Any) -> str | None:
    """The smallest image that's still sharp in the card"""
    usable = [image for image in images or [] if isinstance(image, dict) and image.get("url")]
    sized = [image for image in usable if isinstance(image.get("width"), int)]
    if sized:
        sharp = [image for image in sized if image["width"] >= ART_WIDTH]
        return (min(sharp, key = lambda image: image["width"]) if sharp
                else max(sized, key = lambda image: image["width"]))["url"]
    # Playlist mosaics come without sizes
    return usable[0]["url"] if usable else None


def _joined(*parts: str | None) -> str | None:
    return " · ".join(part for part in parts if part) or None


def _total(page: Any) -> int | None:
    return page.get("total") if isinstance(page, dict) else None


def _open_url(uri: str) -> str | None:
    parts = uri.split(":")
    if len(parts) == 3 and parts[1] in KINDS:
        return OPEN_URL.format(kind = parts[1], id = parts[2])
    return None


def to_item(obj: Any, parent: dict[str, Any] | None = None, playing: bool = False) -> SpotifyItem | None:
    """
    A card row for any Spotify object, or None for the gaps Spotify leaves in its lists

    Args:
        obj: {Any} A track, album, artist, playlist, show, episode, audiobook, chapter or user object
        parent: {dict | None} The album, show or audiobook a simplified track, episode or chapter came from, for the
                cover art and name it leaves out
        playing: {bool} Mark the row as the one playing now
    """
    if not isinstance(obj, dict) or not obj.get("uri"):
        return None
    kind: str = obj.get("type") or obj["uri"].split(":")[1]
    parent = parent or {}
    images = obj.get("images")
    subtitle = detail = None

    if kind == "track":
        album = obj.get("album") or parent
        subtitle = _joined(names(obj.get("artists")), clean(album.get("name")))
        detail = duration(obj.get("duration_ms"))
        images = album.get("images")
    elif kind == "album":
        album_type = obj.get("album_type")
        subtitle = _joined(album_type.capitalize() if isinstance(album_type, str) else "Album",
                           names(obj.get("artists")), (obj.get("release_date") or "")[:4] or None)
        detail = count(obj.get("total_tracks"), "song")
    elif kind == "artist":
        subtitle = _joined("Artist", ", ".join(obj.get("genres") or []) or None)
    elif kind == "playlist":
        owner = clean((obj.get("owner") or {}).get("display_name"))
        subtitle = _joined("Playlist", f"by {owner}" if owner else None)
        # Renamed from `tracks` to `items` in February 2026
        detail = count(_total(obj.get("items")) or _total(obj.get("tracks")), "song")
    elif kind == "show":
        subtitle = _joined("Podcast", clean(obj.get("publisher")))
        detail = count(obj.get("total_episodes"), "episode")
    elif kind == "episode":
        show = obj.get("show") or parent
        subtitle = _joined(clean(show.get("name")), obj.get("release_date"))
        detail = duration(obj.get("duration_ms"))
        images = images or show.get("images")
    elif kind == "audiobook":
        subtitle = _joined("Audiobook", names(obj.get("authors")))
        detail = count(obj.get("total_chapters"), "chapter")
    elif kind == "chapter":
        book = obj.get("audiobook") or parent
        subtitle = clean(book.get("name"))
        detail = duration(obj.get("duration_ms"))
        images = images or book.get("images")
    elif kind == "user":
        subtitle = "Profile"

    return {
        "uri": obj["uri"],
        "url": (obj.get("external_urls") or {}).get("spotify") or _open_url(obj["uri"]),
        "kind": kind,
        "title": clean(obj.get("name")) or ("Local file" if obj.get("is_local") else "Untitled"),
        "subtitle": subtitle,
        "detail": detail,
        "image": art(images),
        "playing": playing,
    }


def line(number: int, item: SpotifyItem, *notes: str | None) -> str:
    """The model's line for a row: `1. Title — subtitle (detail; notes) spotify:kind:id`"""
    text = f"{number}. {item['title']}"
    if item["subtitle"]:
        text += f" — {item['subtitle']}"
    extras = [part for part in (item["detail"], *notes) if part]
    if extras:
        text += f" ({'; '.join(extras)})"
    return f"{text} {item['uri']}"


def about(obj: dict[str, Any]) -> str | None:
    """A clipped description, for the playlists, podcasts, episodes and audiobooks that have one"""
    return clip(clean(obj.get("description")))
