from collections.abc import AsyncIterator
from typing import Any, NotRequired, TypedDict
from urllib.parse import urlsplit

from strands import tool

from radagent.cards import LinksCard, SharedLink


MAX_LINKS: int = 10
MAX_TITLE_CHARS: int = 120
MAX_NOTE_CHARS: int = 240


class LinkInput(TypedDict):
    url: str
    title: str
    note: NotRequired[str]



def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text[:limit - 1].rstrip() + "…" if len(text) > limit else text


def _web_url(url: str) -> str | None:
    """
    The link as an absolute http(s) URL, or None when it isn't one

    A bare host like "x.com/someone" gets https. Links carrying a username or password are refused: in
    "https://bank.com@evil.example" the real host is evil.example, which a title can easily hide
    """
    url = url.strip()
    if "://" not in url:
        url = "https://" + url.removeprefix("//")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not hostname or "." not in hostname and hostname != "localhost":
        return None
    if parts.username is not None or any(char.isspace() for char in url):
        return None
    return url


def _collect(links: list[LinkInput]) -> tuple[list[SharedLink], list[str]]:
    """The links worth showing, deduplicated and capped, and a reason for each one left out"""
    shown: list[SharedLink] = []
    skipped: list[str] = []
    for link in links:
        raw = str(link.get("url") or "")
        url = _web_url(raw)
        if url is None:
            skipped.append(f"{raw!r} is not an http(s) link")
        elif any(other["url"] == url for other in shown):
            continue
        elif len(shown) == MAX_LINKS:
            skipped.append(f"{url} (only {MAX_LINKS} links fit in one card)")
        else:
            title = _clip(str(link.get("title") or ""), MAX_TITLE_CHARS) or urlsplit(url).hostname or url
            note = _clip(str(link.get("note") or ""), MAX_NOTE_CHARS) or None
            shown.append({"url": url, "title": title, "note": note})
    return shown, skipped



@tool
async def share_links(links: list[LinkInput]) -> AsyncIterator[dict[str, Any]]:
    """Show the user links they can click: sources you used, articles, profiles, docs, products, downloads, or any other page they might want to open. Use this whenever your reply points the user to a web page; the user sees each link as a card with its title, site and note, which always opens correctly, while a URL typed into your reply may not. After calling it, refer to the links by title and don't repeat the URLs.

    If you still mention a URL inside your reply's text, write it as a Markdown link with the full address, e.g. [React versions](https://react.dev/versions), never as a bare domain like react.dev/versions.

    Args:
        links: The links in the order to show them, at most 10. Each has `url` (the full http(s) address), `title` (a short name for the page, e.g. "React versions" or "@sooyensu on X", not the URL itself) and optionally `note` (one line on what's there or why it's worth opening).
    """
    shown, skipped = _collect(links)
    problems = f" Skipped: {'; '.join(skipped)}." if skipped else ""

    if not shown:
        yield {"status": "error", "content": [{"text": f"No links to show.{problems}"}]}
        return

    card: LinksCard = {"card": "links", "version": 1, "links": shown}
    # The card goes to the client as a stream event; the last yield is the result the model sees
    yield card
    count = f"{len(shown)} link{'s' if len(shown) != 1 else ''}"
    yield {
        "status": "success",
        "content": [{"text": f"Showed the user {count} as clickable cards; refer to them by title.{problems}"}],
    }
