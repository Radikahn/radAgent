"""
Changing the user's Spotify: creating and editing playlists, saving and following, and raw Web API calls
"""
import json
import re
from typing import Any
from urllib.parse import parse_qsl

from radagent.tools.spotify.catalog import Result, card
from radagent.tools.spotify.client import call
from radagent.tools.spotify.items import count, parse_ref, to_item, to_uri


PLAYLIST_ITEM_KINDS: tuple[str, ...] = ("track", "episode")
SAVABLE_KINDS: tuple[str, ...] = ("track", "album", "artist", "playlist", "show", "episode", "audiobook", "user")
# Spotify's caps per request: playlist edits take 100 items, library edits 40 URIs
PLAYLIST_BATCH: int = 100
LIBRARY_BATCH: int = 40
MAX_PLAYLIST_URIS: int = 1_000
MAX_API_CHARS: int = 40_000

_API_PREFIX = re.compile(r"\A(?:https://api\.spotify\.com)?/?v1(?=/)")



def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[start:start + size] for start in range(0, len(items), size)]



# ---- Playlists ----

def _item_uris(uris: list[str] | None) -> list[str]:
    targets = [to_uri(ref, "track", allowed = PLAYLIST_ITEM_KINDS) for ref in uris or []]
    if len(targets) > MAX_PLAYLIST_URIS:
        raise ValueError(f"That's {len(targets)} items; pass at most {MAX_PLAYLIST_URIS} at a time.")
    return targets


def _add(playlist_id: str, uris: list[str], position: int | None) -> None:
    for start in range(0, len(uris), PLAYLIST_BATCH):
        body: dict[str, Any] = {"uris": uris[start:start + PLAYLIST_BATCH]}
        if position is not None:
            body["position"] = position + start
        call("POST", f"/playlists/{playlist_id}/items", None, body)


def playlist(
    action: str,
    ref: str | None,
    uris: list[str] | None,
    name: str | None,
    description: str | None,
    public: bool | None,
    collaborative: bool | None,
    position: int | None,
    range_start: int | None,
    range_length: int | None,
    insert_before: int | None,
) -> Result:
    if action == "create":
        if not name or not name.strip():
            raise ValueError("create needs a `name`.")
        targets = _item_uris(uris)
        # Spotify only takes collaborative playlists that are private
        shared = bool(collaborative)
        body: dict[str, Any] = {"name": name.strip(), "public": bool(public) and not shared, "collaborative": shared}
        if description and description.strip():
            body["description"] = description.strip()
        created = call("POST", "/me/playlists", None, body)
        _add(created["id"], targets, None)

        item = to_item(created)
        added = f" with {count(len(targets), 'item')}" if targets else ""
        text = (f"Created the {'public' if body['public'] else 'private'} playlist {body['name']!r}{added}: "
                f"{created['uri']}. The user sees it as a card that opens it in Spotify.")
        if item is None:
            return None, text
        item["detail"] = count(len(targets), "song")
        return card("New playlist", None, [item]), text

    if not ref:
        raise ValueError(f"{action} needs `playlist`: the playlist's URI or link.")
    playlist_id = parse_ref(ref, "playlist")[1]
    items_path = f"/playlists/{playlist_id}/items"

    if action == "add":
        targets = _item_uris(uris)
        if not targets:
            raise ValueError("add needs `uris`: the songs or episodes to add.")
        _add(playlist_id, targets, position)
        where = f" at position {position}" if position is not None else ""
        return None, f"Added {count(len(targets), 'item')} to the playlist{where}."

    if action == "remove":
        targets = _item_uris(uris)
        if not targets:
            raise ValueError("remove needs `uris`: the songs or episodes to take out.")
        for chunk in _chunks(targets, PLAYLIST_BATCH):
            call("DELETE", items_path, None, {"items": [{"uri": uri} for uri in chunk]})
        return None, f"Removed every occurrence of {count(len(targets), 'item')} from the playlist."

    if action == "replace":
        targets = _item_uris(uris)
        call("PUT", items_path, None, {"uris": targets[:PLAYLIST_BATCH]})
        _add(playlist_id, targets[PLAYLIST_BATCH:], None)
        return None, f"The playlist now holds just {count(len(targets), 'item')}." if targets else "Emptied the playlist."

    if action == "reorder":
        if range_start is None or insert_before is None:
            raise ValueError("reorder needs `range_start` and `insert_before`.")
        length = range_length or 1
        call("PUT", items_path, None, {"range_start": range_start, "insert_before": insert_before,
                                       "range_length": length})
        return None, f"Moved {count(length, 'item')} from position {range_start} to before position {insert_before}."

    if action == "update":
        changes = {key: value for key, value in (
            ("name", name.strip() if name else None),
            ("description", description),
            ("public", public),
            ("collaborative", collaborative),
        ) if value is not None}
        if not changes:
            raise ValueError("update needs at least one of `name`, `description`, `public` or `collaborative`.")
        call("PUT", f"/playlists/{playlist_id}", None, changes)
        return None, f"Updated the playlist's {', '.join(changes)}."

    raise ValueError(f"Unknown action {action!r}.")



# ---- The library ----

def save(action: str, refs: list[str]) -> Result:
    uris = [to_uri(ref, allowed = SAVABLE_KINDS) for ref in refs]
    if not uris:
        raise ValueError(f"{action} needs `items`: spotify: URIs or open.spotify.com links.")

    if action == "check":
        saved: list[Any] = []
        for chunk in _chunks(uris, LIBRARY_BATCH):
            saved += call("GET", "/me/library/contains", {"uris": chunk}) or []
        return None, "\n".join(f"{uri}: {'saved' if found else 'not saved'}" for uri, found in zip(uris, saved))

    method = {"save": "PUT", "remove": "DELETE"}.get(action)
    if method is None:
        raise ValueError(f"Unknown action {action!r}.")
    for chunk in _chunks(uris, LIBRARY_BATCH):
        call(method, "/me/library", {"uris": chunk})
    done = "Saved" if action == "save" else "Removed"
    return None, f"{done} {count(len(uris), 'item')} {'to' if action == 'save' else 'from'} the user's library."



# ---- Anything else ----

def raw(method: str, path: str, query: dict[str, Any] | None, body: Any) -> Result:
    path = _API_PREFIX.sub("", path.strip())
    if not path.startswith("/"):
        path = "/" + path
    if "?" in path:
        path, _, inline = path.partition("?")
        query = {**dict(parse_qsl(inline)), **(query or {})}
    if "://" in path or ".." in path or "#" in path or any(char.isspace() for char in path):
        raise ValueError("`path` must be a Web API path like /me/player, relative to https://api.spotify.com/v1.")

    data = call(method, path, query, body)
    if data is None:
        return None, "Spotify accepted the request; it returns no content."
    text = json.dumps(data, ensure_ascii = False, indent = 1)
    if len(text) > MAX_API_CHARS:
        text = (text[:MAX_API_CHARS] + f"\n… cut at {MAX_API_CHARS:,} of {len(text):,} characters; ask for less with "
                f"limit, or fields where the endpoint takes it.")
    return None, text
