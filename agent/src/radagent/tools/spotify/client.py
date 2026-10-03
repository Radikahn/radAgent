"""
Spotify Web API access as one user, the agent's owner

Spotify's user endpoints need that user's OAuth token. `radagent --spotify-login` runs the authorization code flow once
on the Mac and saves a refresh token as SPOTIFY_REFRESH_TOKEN (scripts/put-secrets.sh carries it to AWS); from it the
agent mints hour-long access tokens as it needs them. Refresh tokens last 6 months from the login, then it's rerun
"""
import base64
import json
import os
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL: str = "https://api.spotify.com/v1"
TOKEN_URL: str = "https://accounts.spotify.com/api/token"
TIMEOUT_S: int = 15
# Spotify asks for Retry-After seconds between requests once rate limited; longer waits are reported instead
MAX_RETRY_WAIT_S: int = 5
# Access tokens are renewed this long before Spotify says they expire
TOKEN_MARGIN_S: int = 60

LOGIN_HINT: str = (
    "The user has to connect Spotify: set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in agent/.env, run "
    "`uv run radagent --spotify-login` in agent/, then scripts/put-secrets.sh for the deployed agent."
)

# Hints for the errors the model can do something about, by Spotify's reason code
_REASON_HINTS: dict[str, str] = {
    "NO_ACTIVE_DEVICE": "No device is playing Spotify. Pass `device` to pick one from spotify_now_playing, or ask "
                        "the user to open Spotify on a phone, computer or speaker first.",
    "PREMIUM_REQUIRED": "Controlling playback needs Spotify Premium.",
    "QUOTA_EXCEEDED": "The app's Spotify quota is used up for now.",
}

_lock = threading.Lock()
_access_token: str | None = None
_expires_at: float = 0.0
# Spotify may hand out a new refresh token when renewing; this process keeps using the newest
_refresh_token: str | None = None



class SpotifyError(Exception):
    """A request Spotify refused, with its HTTP status and, when it gives one, a reason code like NO_ACTIVE_DEVICE"""

    def __init__(self, status: int, message: str, reason: str | None = None, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status: int = status
        self.message: str = message
        self.reason: str | None = reason
        self.retry_after: int | None = retry_after


    def __str__(self) -> str:
        text = f"Spotify said {self.status}: {self.message}" if self.status else self.message
        hint = _REASON_HINTS.get(self.reason or "")
        if self.status == 429:
            hint = (hint + " " if hint else "") + (
                f"Try again in {self.retry_after} s." if self.retry_after else "Try again shortly.")
        elif self.status == 403 and not hint and "restriction" in self.message.lower():
            hint = "The device or the current item doesn't allow that right now (e.g. it's already paused)."
        return f"{text}. {hint}" if hint else text



class SpotifyNotConnected(SpotifyError):
    """The Spotify credentials are missing, or Spotify no longer accepts them"""

    def __init__(self, problem: str) -> None:
        super().__init__(0, f"{problem} {LOGIN_HINT}")



# ---- Tokens ----

def _json_body(error: HTTPError) -> Any:
    try:
        return json.loads(error.read() or b"null")
    except ValueError:
        return None


def token_request(form: dict[str, str], client_id: str, client_secret: str) -> dict[str, Any]:
    """
    POST to Spotify's token endpoint as the app; the login trades its code here too

    Raises:
        SpotifyNotConnected: Spotify refused the app's credentials or the refresh token
        SpotifyError: Spotify couldn't be reached
    """
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = Request(
        TOKEN_URL,
        data = urlencode(form).encode(),
        method = "POST",
        headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout = TIMEOUT_S) as response:
            return json.load(response)
    except HTTPError as e:
        body = _json_body(e)
        body = body if isinstance(body, dict) else {}
        code, description = body.get("error"), body.get("error_description") or e.reason
        if code == "invalid_client":
            raise SpotifyNotConnected("Spotify rejected SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET.") from None
        if code == "invalid_grant" and form.get("grant_type") == "refresh_token":
            raise SpotifyNotConnected(
                f"Spotify no longer accepts the saved login ({description}); they last 6 months.") from None
        raise SpotifyError(e.code, f"{code or 'token request failed'}: {description}") from None
    except URLError as e:
        raise SpotifyError(0, f"Couldn't reach Spotify: {e.reason}") from None


def _token(refused: str | None = None) -> str:
    """A current access token; `refused` is one the API just turned down, which forces a new one"""
    global _access_token, _expires_at, _refresh_token
    with _lock:
        if _access_token and _access_token != refused and time.monotonic() < _expires_at:
            return _access_token

        # Read on use rather than import, so secrets loaded from AWS after startup still count
        client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        refresh_token = _refresh_token or os.getenv("SPOTIFY_REFRESH_TOKEN", "").strip()
        missing = [name for name, value in (("SPOTIFY_CLIENT_ID", client_id),
                                            ("SPOTIFY_CLIENT_SECRET", client_secret),
                                            ("SPOTIFY_REFRESH_TOKEN", refresh_token)) if not value]
        if missing:
            raise SpotifyNotConnected(f"Spotify isn't connected ({', '.join(missing)} not set).")

        data = token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, client_id, client_secret)
        _access_token = data["access_token"]
        _expires_at = time.monotonic() + int(data.get("expires_in", 3600)) - TOKEN_MARGIN_S
        if data.get("refresh_token"):
            _refresh_token = data["refresh_token"]
        return _access_token



# ---- Requests ----

def _param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _api_error(error: HTTPError) -> SpotifyError:
    """Spotify's error, which is {"error": {"status", "message", "reason"?}} or, for quota, the object itself"""
    body = _json_body(error)
    detail = body.get("error", body) if isinstance(body, dict) else None
    message: str | None = None
    reason: str | None = None
    if isinstance(detail, dict):
        message, reason = detail.get("message"), detail.get("reason")
    elif isinstance(detail, str):
        message = detail
    retry_after = error.headers.get("Retry-After") if error.headers else None
    return SpotifyError(
        error.code,
        message or str(error.reason) or "request failed",
        reason,
        int(retry_after) if retry_after and retry_after.isdigit() else None,
    )


def call(method: str, path: str, query: dict[str, Any] | None = None, body: Any = None) -> Any:
    """
    One Web API request as the user

    Args:
        method: {str} GET, POST, PUT or DELETE
        path: {str} Below https://api.spotify.com/v1, e.g. "/me/player/play"
        query: {dict | None} Query parameters; None values are left out, lists are joined with commas
        body: {Any} Sent as JSON when not None

    Returns:
        data: {Any} The decoded JSON, or None for the empty replies of the player and library endpoints

    Raises:
        SpotifyError: Spotify refused the request or couldn't be reached
        SpotifyNotConnected: There are no credentials, or Spotify no longer accepts them
    """
    url = API_URL + path
    params = {key: _param(value) for key, value in (query or {}).items() if value is not None}
    if params:
        url += "?" + urlencode(params)
    # Spotify wants a Content-Length on bodiless PUTs and POSTs (pause, next, ...), which an empty body gives
    data = json.dumps(body).encode() if body is not None else (None if method == "GET" else b"")

    token = _token()
    for attempt in range(3):
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(Request(url, data = data, method = method, headers = headers), timeout = TIMEOUT_S) as response:
                raw = response.read()
                return json.loads(raw) if raw.strip() else None
        except HTTPError as e:
            if e.code == 401 and attempt == 0:
                token = _token(refused = token)
                continue
            # Spotify has the odd transient 5xx; only reads are retried, so an add to a playlist can't happen twice
            if e.code in (500, 502, 503) and method == "GET" and attempt == 0:
                time.sleep(1)
                continue
            error = _api_error(e)
            if e.code == 429 and attempt < 2 and error.retry_after is not None and error.retry_after <= MAX_RETRY_WAIT_S:
                time.sleep(error.retry_after)
                continue
            raise error from None
        except URLError as e:
            raise SpotifyError(0, f"Couldn't reach Spotify: {e.reason}") from None
    raise SpotifyError(429, "Still rate limited after retrying")
