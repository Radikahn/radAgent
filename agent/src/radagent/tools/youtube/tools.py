import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.request import Request, urlopen

from strands import tool

from radagent.cards import Video, VideosCard


# YouTube's own search API, the one youtube.com calls from the browser; it needs no key. The client version only
# has to be one YouTube still accepts, and older ones keep working for a long time
SEARCH_URL: str = "https://www.youtube.com/youtubei/v1/search?prettyPrint=false"
CLIENT: dict[str, str] = {"clientName": "WEB", "clientVersion": "2.20250925.01.00", "hl": "en", "gl": "US"}
# The search filter for "Type: Video", which leaves out channels, playlists and movies
VIDEOS_ONLY: str = "EgIQAQ=="
USER_AGENT: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
TIMEOUT_S: int = 10

MAX_VIDEOS: int = 10
SNIPPET_CHARS: int = 200

# A fixed size every video has, unlike the signed URLs search returns
THUMBNAIL_URL: str = "https://i.ytimg.com/vi/{id}/mqdefault.jpg"
WATCH_URL: str = "https://www.youtube.com/watch?v={id}"



# ---- YouTube ----

def _post(query: str) -> dict[str, Any]:
    body = json.dumps({"context": {"client": CLIENT}, "query": query, "params": VIDEOS_ONLY}).encode()
    request = Request(SEARCH_URL, data = body, headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout = TIMEOUT_S) as response:
        return json.load(response)


def _renderers(data: Any) -> Iterator[dict[str, Any]]:
    """Every video result in the response, in page order, wherever the layout nests them"""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "videoRenderer" and isinstance(value, dict):
                yield value
            else:
                yield from _renderers(value)
    elif isinstance(data, list):
        for value in data:
            yield from _renderers(value)


def _text(field: Any) -> str | None:
    """YouTube's text fields are either {"simpleText": ...} or {"runs": [{"text": ...}, ...]}"""
    if not isinstance(field, dict):
        return None
    if "simpleText" in field:
        text = field["simpleText"]
    else:
        text = "".join(run.get("text", "") for run in field.get("runs") or [])
    return " ".join(str(text).split()) or None


def _to_video(item: dict[str, Any]) -> tuple[Video, str | None]:
    """The card's video, and the description snippet search matched, which only the model sees"""
    video_id: str = item["videoId"]
    badges = [badge.get("metadataBadgeRenderer") or {} for badge in item.get("badges") or []]
    live = any(badge.get("style") == "BADGE_STYLE_TYPE_LIVE_NOW" for badge in badges)
    snippets = item.get("detailedMetadataSnippets") or [{}]
    snippet = _text(snippets[0].get("snippetText")) or _text(item.get("descriptionSnippet"))

    video: Video = {
        "id": video_id,
        "url": WATCH_URL.format(id = video_id),
        "title": _text(item.get("title")) or "Untitled video",
        "channel": _text(item.get("ownerText")) or _text(item.get("longBylineText")),
        "duration": None if live else _text(item.get("lengthText")),
        "views": _text(item.get("shortViewCountText")) or _text(item.get("viewCountText")),
        "published": _text(item.get("publishedTimeText")),
        "live": live,
        "thumbnail": THUMBNAIL_URL.format(id = video_id),
    }
    return video, snippet[:SNIPPET_CHARS] if snippet else None


def _search(query: str, limit: int) -> list[tuple[Video, str | None]]:
    data = _post(query)
    found: list[tuple[Video, str | None]] = []
    seen: set[str] = set()
    for item in _renderers(data):
        if item.get("videoId") and item["videoId"] not in seen:
            seen.add(item["videoId"])
            found.append(_to_video(item))
        if len(found) == limit:
            break

    if not found and data.get("estimatedResults") not in (None, "0"):
        # Results came back in a layout this parser doesn't know, rather than there being none
        raise RuntimeError("YouTube returned results in an unrecognized format")
    return found



def _summary(results: list[tuple[Video, str | None]]) -> str:
    """What the model sees: enough to pick between the videos, small enough that the harness never offloads it"""
    lines = [
        f"Found {len(results)} videos. The user already sees them as cards with thumbnail, title, channel, length "
        f"and views, and each opens the video, so don't list them again or repeat the URLs: reply in a sentence or "
        f"two, e.g. which you'd watch first.",
    ]
    for number, (video, snippet) in enumerate(results, start = 1):
        details = [
            part for part in (video["channel"], "live now" if video["live"] else video["duration"], video["views"],
                              video["published"])
            if part
        ]
        lines.append(f"{number}. {video['title']} ({'; '.join(details)}) {video['url']}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)



@tool
async def search_youtube(query: str, limit: int = 5) -> AsyncIterator[dict[str, Any]]:
    """Search YouTube for videos. Use this whenever the user wants a video, or would be helped by one: tutorials, how-tos, music, talks, reviews, trailers, recipes, highlights, or "find me a video about ...". The user sees each result as a card with thumbnail, title, channel, length and views that opens the video, so keep your reply short and don't repeat the titles or links unless asked.

    Write the query the way you'd type it into YouTube's search box, e.g. "sourdough bread for beginners" or "Lex Fridman Andrej Karpathy". If the results look off-target, retry with different words.

    Args:
        query: What to search YouTube for.
        limit: Maximum number of videos to return, 1 to 10.
    """
    limit = min(max(limit, 1), MAX_VIDEOS)
    query = " ".join(query.split())
    if not query:
        yield {"status": "error", "content": [{"text": "search_youtube needs a query."}]}
        return

    try:
        results = await asyncio.to_thread(_search, query, limit)
    except Exception as e:
        yield {
            "status": "error",
            "content": [{"text": f"search_youtube failed: {type(e).__name__}: {e}. Try web_search for "
                                 f"\"site:youtube.com {query}\" instead."}],
        }
        return

    if not results:
        yield {"status": "success", "content": [{"text": f"No YouTube videos matched {query!r}. Try other words."}]}
        return

    card: VideosCard = {"card": "videos", "version": 1, "query": query, "videos": [video for video, _ in results]}
    # The card goes to the client as a stream event; the last yield is the result the model sees
    yield card
    yield {"status": "success", "content": [{"text": _summary(results)}]}
