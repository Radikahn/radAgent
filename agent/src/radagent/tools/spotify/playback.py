"""
Spotify playback: what's playing where, and the controls (play, pause, skip, seek, volume, shuffle, repeat, queue,
moving playback between devices). The controls need Spotify Premium, and only reach devices that have Spotify open
"""
from typing import Any

from radagent.cards import SpotifyItem
from radagent.tools.spotify.catalog import CARD_NOTE, Result, card
from radagent.tools.spotify.client import SpotifyError, call
from radagent.tools.spotify.items import count, duration, line, to_item, to_uri


# What `context` can be, and what `uris` can hold
CONTEXT_KINDS: tuple[str, ...] = ("album", "playlist", "artist", "show", "audiobook")
PLAYABLE_KINDS: tuple[str, ...] = ("track", "episode", "chapter")
MAX_PLAY_URIS: int = 100
MAX_QUEUE_URIS: int = 50

_REPEAT: dict[str, str] = {"track": "Repeat one", "context": "Repeat all", "off": "Repeat off"}



# ---- Devices ----

def devices() -> list[dict[str, Any]]:
    """The user's devices with Spotify open; restricted ones (some speakers, TVs) take no commands"""
    found = (call("GET", "/me/player/devices") or {}).get("devices") or []
    return [device for device in found if isinstance(device, dict) and device.get("id")]


def _device_line(device: dict[str, Any]) -> str:
    flags = [
        device.get("type"),
        "active" if device.get("is_active") else None,
        f"volume {device['volume_percent']}%" if isinstance(device.get("volume_percent"), int) else None,
        "no volume control" if device.get("supports_volume") is False else None,
        "takes no commands" if device.get("is_restricted") else None,
    ]
    return f"- {device.get('name')} ({', '.join(flag for flag in flags if flag)}) id={device['id']}"


def _device_list(found: list[dict[str, Any]]) -> str:
    if not found:
        return "No device has Spotify open; the user has to open it on a phone, computer or speaker first."
    return "Devices with Spotify open:\n" + "\n".join(_device_line(device) for device in found)


def find_device(wanted: str) -> dict[str, Any]:
    """
    The open device `wanted` names: its ID, its exact name, or part of its name ("iphone", "mac")

    Raises:
        ValueError: No device, or more than one, matches
    """
    found = devices()
    key = wanted.strip().casefold()
    for matches in (
        [device for device in found if device["id"] == wanted.strip()],
        [device for device in found if (device.get("name") or "").casefold() == key],
        [device for device in found if key in (device.get("name") or "").casefold()],
    ):
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"{wanted!r} matches several devices. {_device_list(matches)}")
    raise ValueError(f"No open Spotify device matches {wanted!r}. {_device_list(found)}")



# ---- Now playing ----

def now_playing(with_queue: bool) -> Result:
    # 204, which comes back as None, when nothing is playing
    state = call("GET", "/me/player", {"additional_types": "episode"}) or {}
    found = devices()
    device = state.get("device") or {}
    obj = state.get("item")
    playing = bool(state.get("is_playing"))

    rows: list[SpotifyItem] = []
    lines: list[str] = []
    if obj and (item := to_item(obj, playing = playing)):
        rows.append(item)
        position = duration(state.get("progress_ms")) or "0:00"
        lines.append(f"{'Playing' if playing else 'Paused'}: " + line(1, item, f"at {position}").removeprefix("1. "))
    elif state:
        kind = state.get("currently_playing_type")
        lines.append("An ad is playing." if kind == "ad" else "Spotify is open but isn't sharing what's playing.")
    else:
        lines.append("Nothing is playing.")

    settings: list[str | None] = []
    if state:
        name = device.get("name") or "an unknown device"
        lines.append(f"Device: {name} ({device.get('type')})"
                     + (f", volume {device['volume_percent']}%" if isinstance(device.get("volume_percent"), int) else ""))
        settings = [
            "Shuffle" if state.get("shuffle_state") else None,
            _REPEAT.get(state.get("repeat_state") or "off") if state.get("repeat_state") != "off" else None,
        ]
        lines.append(f"Shuffle {'on' if state.get('shuffle_state') else 'off'}, "
                     f"{_REPEAT.get(state.get('repeat_state') or 'off', 'Repeat off').lower()}")
        context = state.get("context") or {}
        if context.get("uri"):
            lines.append(f"Playing from the {context.get('type')} {context['uri']}")
    lines.append(_device_list(found))

    if with_queue:
        upcoming = [item for obj in (call("GET", "/me/player/queue") or {}).get("queue") or []
                    if (item := to_item(obj))]
        if upcoming:
            lines.append("Up next:")
            lines += [line(number, item) for number, item in enumerate(upcoming, start = 1)]
            rows += upcoming
        else:
            lines.append("Nothing is queued.")

    if not rows:
        return None, "\n".join(lines)
    lines.append(CARD_NOTE)
    title = f"{'Playing' if playing else 'Paused'} on {device.get('name')}" if device.get("name") else "Now playing"
    volume = f"Volume {device['volume_percent']}%" if isinstance(device.get("volume_percent"), int) else None
    subtitle = " · ".join(part for part in (*settings, volume) if part) or None
    return card(title, subtitle, rows), "\n".join(lines)



# ---- Controls ----

def _send(method: str, path: str, query: dict[str, Any], body: Any, device: dict[str, Any] | None,
          pick: bool = False) -> dict[str, Any] | None:
    """
    Send a command to `device`, or to the active device when None

    Args:
        pick: {bool} With no device active and exactly one open, send it there instead

    Returns:
        device: {dict | None} Where the command went, when that was a device of its own
    """
    try:
        call(method, path, {**query, "device_id": device["id"] if device else None}, body)
        return device
    except SpotifyError as e:
        if device or not pick or e.status != 404:
            raise
        found = [device for device in devices() if not device.get("is_restricted")]
        if len(found) != 1:
            raise ValueError(f"No device is active. {_device_list(found)} Pass `device` to choose one.") from None
        call(method, path, {**query, "device_id": found[0]["id"]}, body)
        return found[0]


def _on(device: dict[str, Any] | None) -> str:
    return f" on {device.get('name')}" if device else ""


def _current_volume(device: dict[str, Any] | None) -> int:
    target = device or next((found for found in devices() if found.get("is_active")), None)
    if not target or not isinstance(target.get("volume_percent"), int):
        raise ValueError("Couldn't read the current volume; pass `volume` instead.")
    return target["volume_percent"]


def control(
    action: str,
    uris: list[str] | None,
    context: str | None,
    start_at: int | str | None,
    position_ms: int | None,
    volume: int | None,
    volume_change: int | None,
    shuffle: bool | None,
    repeat: str | None,
    device_name: str | None,
) -> str:
    """Run one player action; returns what the model reads"""
    device = find_device(device_name) if device_name else None

    if action == "play":
        targets = [to_uri(ref, "track") for ref in uris or []]
        # A lone album or playlist passed as a URI is meant as the context
        if not context and len(targets) == 1 and targets[0].split(":")[1] in CONTEXT_KINDS:
            context, targets = targets[0], []
        if context and targets:
            raise ValueError("Pass either `uris` (songs or episodes) or `context` (an album, playlist, artist or "
                             "show), not both.")
        body: dict[str, Any] = {}
        if context:
            body["context_uri"] = to_uri(context, allowed = CONTEXT_KINDS)
        if targets:
            if wrong := [uri for uri in targets if uri.split(":")[1] not in PLAYABLE_KINDS]:
                raise ValueError(f"`uris` takes songs and episodes, not {', '.join(wrong)}; play an album, playlist, "
                                 f"artist or show with `context`.")
            body["uris"] = targets[:MAX_PLAY_URIS]
        if start_at is not None:
            if not body:
                raise ValueError("`start_at` needs `context` or `uris`.")
            if isinstance(start_at, int) or str(start_at).strip().isdigit():
                body["offset"] = {"position": int(start_at)}
            else:
                body["offset"] = {"uri": to_uri(str(start_at), "track", allowed = PLAYABLE_KINDS)}
        if position_ms is not None:
            body["position_ms"] = max(0, position_ms)
        sent_to = _send("PUT", "/me/player/play", {}, body or None, device, pick = True)
        started = "Started playing" if "context_uri" in body or "uris" in body else "Resumed playback"
        return f"{started}{_on(sent_to)}."

    if action == "pause":
        _send("PUT", "/me/player/pause", {}, None, device)
        return f"Paused{_on(device)}."

    if action == "next":
        _send("POST", "/me/player/next", {}, None, device)
        return "Skipped to the next item."

    if action == "previous":
        _send("POST", "/me/player/previous", {}, None, device)
        return "Went back to the previous item."

    if action == "seek":
        if position_ms is None:
            raise ValueError("seek needs `position_ms`.")
        _send("PUT", "/me/player/seek", {"position_ms": max(0, position_ms)}, None, device)
        return f"Jumped to {duration(position_ms) or '0:00'}."

    if action == "volume":
        if volume is None and volume_change is None:
            raise ValueError("volume needs `volume` (0 to 100) or `volume_change` (e.g. 10 or -10).")
        level = volume if volume is not None else _current_volume(device) + (volume_change or 0)
        level = min(max(level, 0), 100)
        _send("PUT", "/me/player/volume", {"volume_percent": level}, None, device)
        return f"Volume set to {level}%{_on(device)}."

    if action == "shuffle":
        if shuffle is None:
            raise ValueError("shuffle needs `shuffle` (true or false).")
        _send("PUT", "/me/player/shuffle", {"state": shuffle}, None, device)
        return f"Shuffle {'on' if shuffle else 'off'}."

    if action == "repeat":
        if repeat not in _REPEAT:
            raise ValueError('repeat needs `repeat`: "track", "context" or "off".')
        _send("PUT", "/me/player/repeat", {"state": repeat}, None, device)
        return f"{_REPEAT[repeat]}."

    if action == "queue":
        targets = [to_uri(ref, "track", allowed = PLAYABLE_KINDS) for ref in uris or []]
        if not targets:
            raise ValueError("queue needs `uris`: the songs or episodes to queue.")
        for uri in targets[:MAX_QUEUE_URIS]:
            _send("POST", "/me/player/queue", {"uri": uri}, None, device)
        return f"Queued {count(min(len(targets), MAX_QUEUE_URIS), 'item')}."

    if action == "transfer":
        if not device:
            raise ValueError("transfer needs `device`: the device to move playback to.")
        # Without `play`, playback stays playing or paused as it was
        call("PUT", "/me/player", None, {"device_ids": [device["id"]]})
        return f"Moved playback to {device.get('name')}."

    raise ValueError(f"Unknown action {action!r}.")
