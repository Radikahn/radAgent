import asyncio
import atexit
import contextlib
import html
import io
import ipaddress
import re
import socket
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from strands import tool

from radagent.media import MediaError, file_block
from radagent.media.files import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, MAX_IMAGE_INPUT_BYTES, extension

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, FloatRect, Playwright, Response, Route, ViewportSize


# Page text beyond this is cut so a single page can't flood the agent's context
MAX_CHARS: int = 20_000
MAX_BYTES: int = 5 * 1024 * 1024
STATIC_TIMEOUT_S: int = 15
# Plain-fetch text shorter than this is usually a JavaScript shell, so the browser tier takes over
MIN_STATIC_CHARS: int = 500
NAVIGATION_TIMEOUT_MS: int = 30_000
# Extra wait for client-side rendering; many sites never go fully idle, so this is best effort
RENDER_SETTLE_MS: int = 5_000
USER_AGENT: str = "Mozilla/5.0 (compatible; radagent/0.1)"

# Captures (pages read with a screenshot to show the user) render at half scale, so a 1280px wide layout comes
# back as a 640px image; only the top of the page is kept
CAPTURE_VIEWPORT: "ViewportSize" = {"width": 1280, "height": 800}
CAPTURE_SCALE: float = 0.5
CAPTURE_MAX_HEIGHT: int = 2_400
CAPTURE_QUALITY: int = 55
CAPTURE_SETTLE_MS: int = 2_500
# Pages rendering at once in the shared browser; more wait their turn
MAX_CAPTURES: int = 4

# The page's main content when it marks one, else the whole body
_MAIN_TEXT_JS: str = """() => {
    const main = document.querySelector('article, main, [role="main"]');
    const root = main && main.innerText.trim().length > 500 ? main : document.body;
    return root ? root.innerText : "";
}"""

_JS_SHELL_HINTS: tuple[str, ...] = (
    "enable javascript",
    "javascript is required",
    "javascript is disabled",
    "requires javascript",
)
_TEXT_TYPES: tuple[str, ...] = ("text/html", "application/xhtml+xml", "application/json")
# Files the model views as media rather than text, by content type, mapped to the extension media.file_block reads
_MEDIA_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}
# Servers often send files as a generic type, so the URL's extension decides for these
_GENERIC_TYPES: tuple[str, ...] = ("application/octet-stream", "binary/octet-stream", "application/download")



def _is_public_host(host: str) -> bool:
    """
    True when every address `host` resolves to is publicly routable

    Keeps the agent from being steered into localhost, the home network or, on AWS, the metadata and credential
    endpoints. The plain fetch checks every redirect; the browser checks every request a page makes and every
    redirect its navigation went through
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    return bool(addresses) and all(address.is_global for address in addresses)


def _check_url(url: str) -> str | None:
    """Return why `url` can't be fetched, or None when it is a public http(s) URL"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "only http(s) URLs are allowed"
    if not _is_public_host(parsed.hostname):
        return f"{parsed.hostname} does not resolve to a public address"
    return None



# ---- Tier 1: plain HTTP fetch ----

class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        # Without this a public page could redirect the fetch into the local network
        problem = _check_url(newurl)
        if problem:
            raise ValueError(f"refused redirect to {newurl}: {problem}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    # Keep block boundaries as line breaks so the text stays readable
    page = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6])\b[^>]*>", "\n", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"[ \t\r\f\v]+", " ", page)
    page = re.sub(r" *\n *", "\n", page)
    page = re.sub(r"\n{3,}", "\n\n", page)
    return page.strip()


class _MediaFile(NamedTuple):
    """A fetched file the model views as media: a PDF, Office document or image"""
    name: str
    data: bytes
    final_url: str


def _media_name(final_url: str, content_type: str) -> str | None:
    """A file name whose extension media.file_block reads, or None when the response isn't a media file"""
    name = unquote(urlparse(final_url).path.rstrip("/").rpartition("/")[2]) or "file"
    if kind := _MEDIA_TYPES.get(content_type):
        return name if extension(name) == kind else f"{name}.{kind}"
    if content_type in _GENERIC_TYPES and extension(name) in DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS:
        return name
    return None


def _fetch_static(url: str, media: bool = False) -> tuple[str, str] | _MediaFile:
    """
    Fetch `url` with a plain HTTP request and return its text

    Args:
        url: {str} Public http(s) URL
        media: {bool} Return PDFs, Office documents and images as a _MediaFile instead of refusing them

    Returns:
        result: {tuple[str, str] | _MediaFile} (text, final_url), final_url being where redirects ended up
    """
    request = Request(url, headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"})
    with build_opener(_PublicRedirectHandler).open(request, timeout = STATIC_TIMEOUT_S) as response:
        final_url: str = response.geturl()
        content_type: str = response.headers.get_content_type()
        charset: str = response.headers.get_content_charset() or "utf-8"

        if media and (name := _media_name(final_url, content_type)):
            # Images are shrunk to fit later, so they may arrive larger than what the model is finally sent
            data: bytes = response.read(MAX_IMAGE_INPUT_BYTES + 1)
            if len(data) > MAX_IMAGE_INPUT_BYTES:
                raise MediaError(f"{name} is larger than {MAX_IMAGE_INPUT_BYTES // 1_000_000} MB")
            return _MediaFile(name, data, final_url)
        body: bytes = response.read(MAX_BYTES)

    if not (content_type.startswith("text/") or content_type in _TEXT_TYPES):
        raise ValueError(f"unsupported content type {content_type}")

    try:
        text = body.decode(charset, errors = "replace")
    except LookupError:
        text = body.decode("utf-8", errors = "replace")
    return (_html_to_text(text) if "html" in content_type else text), final_url


def _needs_browser(text: str) -> bool:
    """True when plain-fetch text looks like a page that only renders with JavaScript"""
    if len(text) < MIN_STATIC_CHARS:
        return True
    # Only short pages are judged by their wording; long pages often mention JavaScript in passing
    return len(text) < 2_000 and any(hint in text.lower() for hint in _JS_SHELL_HINTS)



# ---- Tier 2: headless browser ----

@dataclass(frozen = True)
class PageCapture:
    """A page as the browser rendered it: where it ended up, its text, and a picture of its top"""
    url: str
    title: str
    text: str
    screenshot: bytes | None    # JPEG, CAPTURE_VIEWPORT width at CAPTURE_SCALE
    pdf: bool = False           # A PDF read as text, so there's no screenshot


async def _keep_public(context: "BrowserContext") -> None:
    """Refuse every request a page in `context` makes to an address that isn't public"""
    public: dict[str, bool] = {}

    async def check(route: "Route") -> None:
        parsed = urlparse(route.request.url)
        if parsed.scheme not in ("http", "https"):
            # data:, blob: and the like stay inside the page
            await route.continue_()
            return
        host = parsed.hostname or ""
        if host not in public:
            public[host] = await asyncio.to_thread(_is_public_host, host)
        if public[host]:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await context.route("**/*", check)


def _check_navigation(response: "Response | None") -> None:
    """
    Refuse a page whose navigation was redirected through an address that isn't public

    A route sees the request a page makes but not the redirects the network follows for it, so these are checked
    once the navigation is done, before anything from the page is read
    """
    request = response.request if response is not None else None
    while request is not None:
        if problem := _check_url(request.url):
            raise ValueError(f"refused {request.url}: {problem}")
        request = request.redirected_from


def _check_final(url: str) -> None:
    """Refuse a page that ended up, after scripts ran, on an address that isn't public"""
    if url not in ("", "about:blank") and (problem := _check_url(url)):
        raise ValueError(f"refused {url}: {problem}")



class _BackgroundBrowser:
    """
    One headless Chromium on a dedicated event loop thread, shared across agent turns

    Strands runs each agent call on a fresh event loop, and Playwright objects are bound to the loop that
    created them, so the browser lives on its own long-lived loop and tools submit work to it
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        threading.Thread(target = self._loop.run_forever, name = "radagent-browser", daemon = True).start()
        self._playwright: "Playwright | None" = None
        self._browser: "Browser | None" = None
        self._capture_slots = asyncio.Semaphore(MAX_CAPTURES)
        atexit.register(self.close)


    async def _get_browser(self) -> "Browser":
        # Import and launch lazily so the plain-fetch tier works without Playwright installed
        if self._browser is None:
            if self._playwright is None:
                try:
                    from playwright.async_api import async_playwright
                except ImportError:
                    raise RuntimeError(
                        "Playwright is not installed (uv add playwright && uv run playwright install chromium)"
                    ) from None
                self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless = True)
        return self._browser


    async def _render(self, url: str) -> tuple[str, str]:
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        browser = await self._get_browser()

        # A fresh context per call keeps cookies and storage from leaking between pages
        context = await browser.new_context(user_agent = USER_AGENT)
        try:
            await _keep_public(context)
            page = await context.new_page()
            _check_navigation(await page.goto(url, wait_until = "domcontentloaded", timeout = NAVIGATION_TIMEOUT_MS))
            with contextlib.suppress(PlaywrightTimeout):
                await page.wait_for_load_state("networkidle", timeout = RENDER_SETTLE_MS)
            _check_final(page.url)
            return await page.inner_text("body"), page.url
        finally:
            await context.close()


    async def render(self, url: str) -> tuple[str, str]:
        """
        Load `url` in the background browser and return the page's visible text

        Args:
            url: {str} Public http(s) URL

        Returns:
            (text, final_url): {tuple[str, str]} final_url is where navigation ended up
        """
        future = asyncio.run_coroutine_threadsafe(self._render(url), self._loop)
        return await asyncio.wrap_future(future)


    async def _capture(self, url: str) -> PageCapture:
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        async with self._capture_slots:
            browser = await self._get_browser()
            context = await browser.new_context(
                user_agent = USER_AGENT, viewport = CAPTURE_VIEWPORT, device_scale_factor = CAPTURE_SCALE
            )
            try:
                await _keep_public(context)
                page = await context.new_page()
                try:
                    _check_navigation(await page.goto(url, wait_until = "domcontentloaded", timeout = NAVIGATION_TIMEOUT_MS))
                except PlaywrightTimeout:
                    # A slow page often has its content up long before it finishes loading; keep what's there
                    if page.url in ("", "about:blank"):
                        raise
                with contextlib.suppress(PlaywrightTimeout):
                    await page.wait_for_load_state("networkidle", timeout = CAPTURE_SETTLE_MS)
                _check_final(page.url)

                height: int = await page.evaluate("document.documentElement.scrollHeight") or CAPTURE_VIEWPORT["height"]
                clip: "FloatRect" = {"x": 0, "y": 0, "width": CAPTURE_VIEWPORT["width"], "height": min(height, CAPTURE_MAX_HEIGHT)}
                screenshot: bytes | None = None
                with contextlib.suppress(Exception):
                    screenshot = await page.screenshot(type = "jpeg", quality = CAPTURE_QUALITY, full_page = True, clip = clip)
                return PageCapture(
                    url = page.url, title = await page.title(), text = await page.evaluate(_MAIN_TEXT_JS), screenshot = screenshot
                )
            finally:
                await context.close()


    async def capture(self, url: str) -> PageCapture:
        """
        Load `url` in the background browser and return its text along with a screenshot of the top of the page

        Args:
            url: {str} Public http(s) URL

        Returns:
            capture: {PageCapture}
        """
        future = asyncio.run_coroutine_threadsafe(self._capture(url), self._loop)
        return await asyncio.wrap_future(future)


    async def _shutdown(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()


    def close(self) -> None:
        """Shut down Chromium and stop the background loop"""
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout = 10)
        self._loop.call_soon_threadsafe(self._loop.stop)


_browser = _BackgroundBrowser()



def _media_result(media: _MediaFile) -> dict[str, Any]:
    """The file as a tool result the model views directly; MediaGuard keeps it within Bedrock's limits"""
    block = file_block(media.name, media.data)
    kind = "image" if "image" in block else "document"
    # The Source line comes first, as for pages, so the trust gate can attribute it
    header = f"Source: {media.final_url}\n\nThe {kind} {media.name} follows."
    return {"status": "success", "content": [{"text": header}, block]}


def _page_result(text: str, final_url: str) -> str:
    # The Source line names where the text really came from after redirects; the trust gate reads it
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[truncated]"
    return f"Source: {final_url}\n\n{text}"


@tool
async def read_page(url: str) -> str | dict[str, Any]:
    """Read a web page and return its visible text. Tries a fast plain fetch first and falls back to a real browser when the page needs JavaScript or the plain fetch is blocked. Links to PDFs, Word and Excel files, and images come back as the file itself, which you can read or look at directly.

    Args:
        url: The http(s) URL to read.
    """
    url = url.strip()
    problem = await asyncio.to_thread(_check_url, url)
    if problem:
        return f"read_page failed: {problem}"

    static_text, static_url = "", url
    try:
        fetched = await asyncio.to_thread(_fetch_static, url, True)
        if isinstance(fetched, _MediaFile):
            return await asyncio.to_thread(_media_result, fetched)
        static_text, static_url = fetched
        if not _needs_browser(static_text):
            return _page_result(static_text, static_url)
        static_problem = "too little text, likely needs JavaScript"
    except MediaError as e:
        # The file was found but can't be shown, and a browser would do no better
        return f"read_page failed: {e}"
    except Exception as e:
        static_problem = f"{type(e).__name__}: {e}"

    try:
        browser_text, browser_url = await _browser.render(url)
    except Exception as e:
        # A failed browser tier still leaves whatever the plain fetch got
        if static_text.strip():
            return _page_result(static_text, static_url)
        # Return the failure as text so the model can try another source
        return f"read_page failed: plain fetch ({static_problem}); browser ({type(e).__name__}: {e})"

    if browser_text.strip():
        return _page_result(browser_text, browser_url)
    if static_text.strip():
        return _page_result(static_text, static_url)
    return "The page rendered no visible text."



def _pdf_text(data: bytes) -> tuple[str, str]:
    """
    A PDF's title and the text of its first pages, stopping once there's more than a page result can hold

    Returns:
        (title, text): {tuple[str, str]} title is "" when the PDF doesn't name itself
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    title = ""
    with contextlib.suppress(Exception):
        title = " ".join(str(reader.metadata.title or "").split()) if reader.metadata else ""

    pages: list[str] = []
    size = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
        size += len(text)
        if size > MAX_CHARS:
            break
    return title, "\n\n".join(pages)


async def capture_page(url: str) -> PageCapture:
    """
    Read a page through the browser so there is a screenshot to show, falling back to a plain fetch for its text

    The reverse of read_page's order: the picture is the point, so the browser goes first and the plain fetch
    only fills in text the browser couldn't get (blocked, or a page that rendered next to nothing)

    Args:
        url: {str} The http(s) URL to read

    Returns:
        capture: {PageCapture} `screenshot` is None for a PDF, or when only the plain fetch worked

    Raises:
        ValueError: When `url` isn't a public http(s) URL or neither tier got any text
    """
    url = url.strip()
    problem = await asyncio.to_thread(_check_url, url)
    if problem:
        raise ValueError(problem)

    capture: PageCapture | None = None
    browser_problem = ""
    try:
        capture = await _browser.capture(url)
        if not _needs_browser(capture.text):
            return capture
    except Exception as e:
        # Playwright's errors carry a call log after the first line; the first line says what happened
        browser_problem = (str(e).splitlines() or [type(e).__name__])[0]
        if "Download is starting" in browser_problem:
            browser_problem = "the link is a file download, not a page"

    try:
        fetched = await asyncio.to_thread(_fetch_static, url, True)
        if isinstance(fetched, _MediaFile):
            # The browser downloads a PDF rather than showing it, so PDFs land here and are read as text
            if extension(fetched.name) != "pdf":
                raise ValueError(f"the link is a {extension(fetched.name) or 'media'} file, not a page")
            title, text = await asyncio.to_thread(_pdf_text, fetched.data)
            if not text.strip():
                raise ValueError("the PDF has no text to read, likely a scan")
            return PageCapture(url = fetched.final_url, title = title, text = text, screenshot = None, pdf = True)
        static_text, static_url = fetched
    except Exception as e:
        if capture is not None and capture.text.strip():
            return capture
        raise ValueError(f"{browser_problem or 'the page showed no text'}; a plain fetch failed too ({e})") from None

    if capture is not None and len(capture.text) >= len(static_text):
        return capture
    return PageCapture(
        url = capture.url if capture else static_url,
        title = capture.title if capture else "",
        text = static_text,
        screenshot = capture.screenshot if capture else None,
    )
