"""
Google API access as one user, the agent's owner

The app connects Google (radagent.tools.google.account keeps the refresh token); from it the agent mints hour-long
access tokens as it needs them. The OAuth client is the app's own iOS-type client, which has no secret: PKCE stands
in for one, so refreshing needs only the client ID that came with the login
"""
import json
import threading
import time
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from radagent.tools.google.account import Login


TOKEN_URL: str = "https://oauth2.googleapis.com/token"
REVOKE_URL: str = "https://oauth2.googleapis.com/revoke"
DRIVE_URL: str = "https://www.googleapis.com/drive/v3"
UPLOAD_URL: str = "https://www.googleapis.com/upload/drive/v3"
DOCS_URL: str = "https://docs.googleapis.com/v1"
CALENDAR_URL: str = "https://www.googleapis.com/calendar/v3"
TIMEOUT_S: int = 30
# Access tokens are renewed this long before Google says they expire
TOKEN_MARGIN_S: int = 60
# A missing or refused login is looked up again (another device may have just connected), at most this often
RELOAD_INTERVAL_S: int = 60

DRIVE_SCOPE: str = "https://www.googleapis.com/auth/drive"
DOCS_SCOPE: str = "https://www.googleapis.com/auth/documents"
CALENDAR_SCOPE: str = "https://www.googleapis.com/auth/calendar"
# What the tools need; the app asks for these plus openid and email, to show which account is connected
SCOPES: tuple[str, ...] = (DRIVE_SCOPE, DOCS_SCOPE, CALENDAR_SCOPE)

LOGIN_HINT: str = "The user has to connect Google: Settings (the gear, or ⌘,) > Google > Connect, in the app."

_lock = threading.Lock()
_login: "Login | None" = None
_access_token: str | None = None
_expires_at: float = 0.0
_looked_up_at: float = float("-inf")



class GoogleError(Exception):
    """A request Google refused, with its HTTP status (0 when it never got an answer) and Google's reason code"""

    def __init__(self, status: int, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.status: int = status
        self.message: str = message
        self.reason: str | None = reason


    def __str__(self) -> str:
        if not self.status:
            return self.message
        hint = ""
        if self.reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT") or "scope" in self.message.lower():
            hint = (" The user didn't allow this when connecting Google; have them disconnect and connect again, "
                    "keeping every box ticked.")
        elif self.status == 404:
            hint = " Check the ID; the user may also not have access to it."
        elif self.status == 429 or self.reason in ("rateLimitExceeded", "userRateLimitExceeded"):
            hint = " Try again shortly."
        return f"Google said {self.status}: {self.message.rstrip('.')}.{hint}"



class GoogleNotConnected(GoogleError):
    """Google isn't connected, or no longer accepts the login"""

    def __init__(self, problem: str) -> None:
        super().__init__(0, f"{problem} {LOGIN_HINT}")



# ---- Tokens ----

def _error_body(error: HTTPError) -> Any:
    try:
        return json.loads(error.read() or b"null")
    except ValueError:
        return None


def post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    """
    POST a form to one of Google's OAuth endpoints

    Raises:
        GoogleError: Google refused it or couldn't be reached
    """
    request = Request(url, data = urlencode(form).encode(), method = "POST",
                      headers = {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout = TIMEOUT_S) as response:
            raw = response.read()
            return json.loads(raw) if raw.strip() else {}
    except HTTPError as e:
        body = _error_body(e)
        body = body if isinstance(body, dict) else {}
        raise GoogleError(e.code, f"{body.get('error') or 'request failed'}: {body.get('error_description') or e.reason}",
                          body.get("error")) from None
    except URLError as e:
        raise GoogleError(0, f"Couldn't reach Google: {e.reason}") from None


def token_request(form: dict[str, str]) -> dict[str, Any]:
    """
    POST to Google's token endpoint

    Raises:
        GoogleNotConnected: Google no longer accepts the refresh token
        GoogleError: Google refused the request or couldn't be reached
    """
    try:
        return post_form(TOKEN_URL, form)
    except GoogleError as e:
        if e.reason == "invalid_grant" and form.get("grant_type") == "refresh_token":
            raise GoogleNotConnected(
                "Google no longer accepts the saved login (it was revoked, the password changed, or the Google Cloud "
                "app is still in Testing, where logins last 7 days).") from None
        raise


def remember_login(login: "Login", access_token: str | None = None, expires_in: int = 0) -> None:
    """Use `login` from now on, e.g. right after connecting, with the access token that came with it"""
    global _login, _access_token, _expires_at, _looked_up_at
    with _lock:
        _login = login
        _access_token = access_token
        _expires_at = time.monotonic() + expires_in - TOKEN_MARGIN_S if access_token else 0.0
        _looked_up_at = time.monotonic()


def forget_login() -> None:
    global _login, _access_token, _looked_up_at
    with _lock:
        _login = None
        _access_token = None
        _looked_up_at = time.monotonic()


def login() -> "Login":
    """
    The login in use, looked up when there isn't one yet

    Raises:
        GoogleNotConnected: Google isn't connected
    """
    global _login, _looked_up_at
    from radagent.tools.google.account import load
    if _login is None and time.monotonic() - _looked_up_at >= RELOAD_INTERVAL_S:
        _looked_up_at = time.monotonic()
        _login = load()
    if _login is None:
        raise GoogleNotConnected("Google isn't connected.")
    return _login


def _token(refused: str | None = None) -> str:
    """A current access token; `refused` is one the API just turned down, which forces a new one"""
    global _login, _access_token, _expires_at, _looked_up_at
    with _lock:
        if _access_token and _access_token != refused and time.monotonic() < _expires_at:
            return _access_token
        for attempt in range(2):
            current = login()
            try:
                data = token_request({
                    "grant_type": "refresh_token",
                    "refresh_token": current["refresh_token"],
                    "client_id": current["client_id"],
                })
            except GoogleNotConnected:
                # Another device may have connected again since this login was read
                if attempt == 0 and time.monotonic() - _looked_up_at >= RELOAD_INTERVAL_S:
                    _login = None
                    continue
                raise
            _access_token = data["access_token"]
            _expires_at = time.monotonic() + int(data.get("expires_in", 3600)) - TOKEN_MARGIN_S
            return _access_token
        raise AssertionError("unreachable")



# ---- Requests ----

def _param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _api_error(error: HTTPError) -> GoogleError:
    """Google's error, which is {"error": {"code", "message", "status", "errors": [{"reason"}]}}"""
    body = _error_body(error)
    detail = body.get("error") if isinstance(body, dict) else None
    message: str | None = None
    reason: str | None = None
    if isinstance(detail, dict):
        message = detail.get("message")
        errors = detail.get("errors")
        reason = (errors[0].get("reason") if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                  else None) or detail.get("status")
        for item in detail.get("details") or []:
            if isinstance(item, dict) and item.get("reason"):
                reason = item["reason"]
    elif isinstance(detail, str):
        message = detail
    return GoogleError(error.code, message or str(error.reason) or "request failed", reason)


def call(
    method: str,
    url: str,
    query: dict[str, Any] | None = None,
    body: Any = None,
    data: bytes | None = None,
    content_type: str | None = None,
    raw: bool = False,
) -> Any:
    """
    One API request as the user

    Args:
        method: {str} GET, POST, PUT, PATCH or DELETE
        url: {str} The full endpoint, e.g. DRIVE_URL + "/files"
        query: {dict | None} Query parameters; None values are left out
        body: {Any} Sent as JSON when not None
        data: {bytes | None} Sent as is, with `content_type`, instead of a JSON body
        content_type: {str | None} For `data`
        raw: {bool} Return the reply's bytes instead of decoding JSON (downloads and exports)

    Returns:
        data: {Any} The decoded JSON, None for an empty reply, or bytes with `raw`

    Raises:
        GoogleError: Google refused the request or couldn't be reached
        GoogleNotConnected: Google isn't connected, or no longer accepts the login
    """
    params = {key: _param(value) for key, value in (query or {}).items() if value is not None}
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    if body is not None:
        data, content_type = json.dumps(body).encode(), "application/json"

    token = _token()
    for attempt in range(3):
        headers = {"Authorization": f"Bearer {token}"}
        if not raw:
            headers["Accept"] = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        try:
            request = Request(url, data = data if data is not None else (None if method in ("GET", "DELETE") else b""),
                              method = method, headers = headers)
            with urlopen(request, timeout = TIMEOUT_S) as response:
                payload = response.read()
                if raw:
                    return payload
                return json.loads(payload) if payload.strip() else None
        except HTTPError as e:
            if e.code == 401 and attempt == 0:
                token = _token(refused = token)
                continue
            # Only reads are retried, so a create can't happen twice
            if e.code in (429, 500, 502, 503) and method == "GET" and attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise _api_error(e) from None
        except URLError as e:
            raise GoogleError(0, f"Couldn't reach Google: {e.reason}") from None
    raise GoogleError(503, "Google kept failing after retrying")
