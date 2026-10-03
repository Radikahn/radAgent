"""
SSH to the sandbox, the container on the user's server where the agent writes, runs and tests code (see sandbox/)

The agent logs in as the sandbox's `agent` user with its own Ed25519 key and trusts exactly one host key, the one
pinned in SANDBOX_HOST_KEY; there is no trust on first use. The connection goes straight to SANDBOX_HOST:SANDBOX_PORT,
or, with SANDBOX_CF_ACCESS_CLIENT_ID and SANDBOX_CF_ACCESS_CLIENT_SECRET set, through a Cloudflare Tunnel with
`cloudflared access ssh`, which needs no open port on the server. Either way SSH runs end to end, so whatever carries
the connection sees only ciphertext. Settings come from agent/.env locally and from the agent's secret on AWS
(scripts/put-secrets.sh carries them there)
"""
import asyncio
import logging
import os
import shlex
import shutil
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path

import asyncssh

from radagent.server.settings import reload_from_secret


SETTING_NAMES: tuple[str, ...] = (
    "SANDBOX_HOST", "SANDBOX_PORT", "SANDBOX_USER", "SANDBOX_HOST_KEY", "SANDBOX_SSH_KEY",
    "SANDBOX_CF_ACCESS_CLIENT_ID", "SANDBOX_CF_ACCESS_CLIENT_SECRET",
)
DEFAULT_PORT: int = 2222
DEFAULT_USER: str = "agent"
CONNECT_TIMEOUT_S: int = 20
KEEPALIVE_INTERVAL_S: int = 30
# Settings pushed with scripts/put-secrets.sh reach a running session by re-reading the secret, at most this often
SECRET_RELOAD_INTERVAL_S: int = 60

# Where the agent works when it isn't told otherwise; relative paths are relative to it
WORK_DIR: str = "work"
# Commands are stopped after their timeout, which is capped here; longer work runs as a background job
MAX_TIMEOUT_S: int = 1_800
# Output past this many bytes loses its middle, keeping the start and the end, where errors and summaries are
OUTPUT_HEAD_BYTES: int = 8_000
OUTPUT_TAIL_BYTES: int = 8_000

SETUP_HINT: str = (
    "The sandbox isn't set up. The user has to run it on their server and give the agent its address and keys; "
    "see sandbox/README.md in the radagent repository."
)

# asyncssh logs every channel at INFO
asyncssh.set_log_level(logging.WARNING)

_reloaded_at: float = float("-inf")
# One connection per event loop: the server streams on one loop, while Agent.__call__ runs each turn on a new one
_connections: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[Settings, asyncssh.SSHClientConnection]]" = (
    weakref.WeakKeyDictionary())
_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()



class SandboxError(Exception):
    """Something the model should hear about in a sentence: the sandbox isn't set up, can't be reached, or refused"""



@dataclass(frozen = True)
class Settings:
    host: str
    port: int
    user: str
    host_key: str
    # Kept out of repr, so a settings object that ends up in a log doesn't carry the secrets with it
    client_key: str = field(repr = False)
    cf_client_id: str | None = None
    cf_client_secret: str | None = field(default = None, repr = False)


    @property
    def via(self) -> str:
        """How the connection gets there, for messages"""
        tunnel = " through Cloudflare Access" if self.cf_client_id else f":{self.port}"
        return f"{self.user}@{self.host}{tunnel}"


@dataclass(frozen = True)
class RunResult:
    exit_status: int | None
    output: str
    # Bytes left out of the middle of the output
    omitted: int
    seconds: float
    timed_out: bool



# ---- Settings ----

def _client_key() -> str:
    """The private key's text, from SANDBOX_SSH_KEY or the file SANDBOX_SSH_KEY_PATH names"""
    key = os.getenv("SANDBOX_SSH_KEY", "").strip()
    if key:
        # A key kept on one line in .env has its newlines written as \n
        return key.replace("\\n", "\n") if "\n" not in key else key
    path = os.getenv("SANDBOX_SSH_KEY_PATH", "").strip()
    if not path:
        return ""
    try:
        return Path(path).expanduser().read_text(encoding = "utf-8").strip()
    except OSError as e:
        raise SandboxError(f"Couldn't read SANDBOX_SSH_KEY_PATH ({path}): {e.strerror}.") from None


def _settings() -> Settings:
    host = os.getenv("SANDBOX_HOST", "").strip()
    host_key = os.getenv("SANDBOX_HOST_KEY", "").strip()
    client_key = _client_key()
    missing = [name for name, value in
               (("SANDBOX_HOST", host), ("SANDBOX_HOST_KEY", host_key), ("SANDBOX_SSH_KEY", client_key)) if not value]
    if missing:
        raise SandboxError(f"{SETUP_HINT} ({', '.join(missing)} not set)")
    port = os.getenv("SANDBOX_PORT", "").strip() or str(DEFAULT_PORT)
    if not port.isdigit():
        raise SandboxError(f"SANDBOX_PORT should be a port number, not {port!r}.")
    return Settings(
        host = host,
        port = int(port),
        user = os.getenv("SANDBOX_USER", "").strip() or DEFAULT_USER,
        host_key = host_key,
        client_key = client_key,
        cf_client_id = os.getenv("SANDBOX_CF_ACCESS_CLIENT_ID", "").strip() or None,
        cf_client_secret = os.getenv("SANDBOX_CF_ACCESS_CLIENT_SECRET", "").strip() or None,
    )


def _reload() -> bool:
    """Take the sandbox settings from the agent's secret as it is now; True when they changed"""
    global _reloaded_at
    if time.monotonic() - _reloaded_at < SECRET_RELOAD_INTERVAL_S:
        return False
    _reloaded_at = time.monotonic()
    return reload_from_secret(SETTING_NAMES)


def _host_public_key(line: str) -> asyncssh.SSHKey:
    """
    The pinned host key, from its .pub file's line ("ssh-ed25519 AAAA... comment") or a known_hosts line, which has
    the host in front
    """
    words = line.split()
    for i, word in enumerate(words[:-1]):
        if word.startswith(("ssh-", "ecdsa-", "sk-")):
            try:
                return asyncssh.import_public_key(f"{word} {words[i + 1]}")
            except (asyncssh.KeyImportError, ValueError):
                break
    raise SandboxError("SANDBOX_HOST_KEY isn't a public key; it should be the sandbox's ssh_host_ed25519_key.pub line.")



# ---- Connection ----

async def _connect(settings: Settings) -> asyncssh.SSHClientConnection:
    try:
        client_key = asyncssh.import_private_key(settings.client_key)
    except (asyncssh.KeyImportError, ValueError):
        raise SandboxError("SANDBOX_SSH_KEY isn't a private key that can be read (it has to be unencrypted).") from None

    proxy_command: list[str] | None = None
    if settings.cf_client_id or settings.cf_client_secret:
        if not (settings.cf_client_id and settings.cf_client_secret):
            raise SandboxError("Set both SANDBOX_CF_ACCESS_CLIENT_ID and SANDBOX_CF_ACCESS_CLIENT_SECRET, or neither.")
        cloudflared = shutil.which("cloudflared")
        if not cloudflared:
            raise SandboxError("The sandbox is behind Cloudflare Access, but cloudflared isn't installed here.")
        proxy_command = [
            cloudflared, "access", "ssh", "--hostname", settings.host,
            "--service-token-id", settings.cf_client_id, "--service-token-secret", settings.cf_client_secret,
        ]

    try:
        return await asyncssh.connect(
            settings.host,
            settings.port,
            username = settings.user,
            client_keys = [client_key],
            # Exactly the pinned key, and nothing from ~/.ssh: no known_hosts, no config file, no ssh-agent
            known_hosts = ([_host_public_key(settings.host_key)], [], []),
            config = None,
            agent_path = None,
            proxy_command = proxy_command,
            connect_timeout = CONNECT_TIMEOUT_S,
            keepalive_interval = KEEPALIVE_INTERVAL_S,
        )
    except asyncssh.HostKeyNotVerifiable:
        raise SandboxError(
            f"Refused to connect to {settings.via}: the server's host key isn't the one in SANDBOX_HOST_KEY. Either "
            "the sandbox's host key was regenerated, or something is in the way of the connection. The user should "
            "compare the key on the server (sandbox/README.md) before changing SANDBOX_HOST_KEY."
        ) from None
    except asyncssh.PermissionDenied:
        raise SandboxError(
            f"The sandbox at {settings.via} refused the agent's key. Its public key has to be in the server's "
            "services.radagent-sandbox.authorizedKeys."
        ) from None
    except (OSError, asyncssh.Error, asyncio.TimeoutError) as e:
        detail = str(e) or type(e).__name__
        raise SandboxError(f"Couldn't reach the sandbox at {settings.via}: {detail}.") from None


async def connection() -> asyncssh.SSHClientConnection:
    """
    The connection to the sandbox, opened on first use and kept while it stays open

    Raises:
        SandboxError: The sandbox isn't set up, can't be reached, or refused the login
    """
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        cached = _connections.get(loop)
        for attempt in range(2):
            try:
                settings = _settings()
                if cached and cached[0] == settings and not cached[1].is_closed():
                    return cached[1]
                if cached:
                    cached[1].close()
                    cached = None
                connection = await _connect(settings)
            except SandboxError:
                # Settings may have been pushed or changed since this session started
                if attempt == 0 and await asyncio.to_thread(_reload):
                    continue
                raise
            _connections[loop] = (settings, connection)
            return connection
        raise AssertionError("unreachable")


async def describe() -> str:
    """Where the sandbox is and how the agent gets there, without connecting"""
    settings = _settings()
    key = _host_public_key(settings.host_key)
    return f"{settings.via}, host key {key.get_fingerprint()}"



# ---- Paths ----

def remote_path(path: str | None) -> str:
    """
    A path as SFTP takes it: relative to the agent's home. Relative paths given to the tools are relative to the work
    folder, and ~ is the home
    """
    path = (path or "").strip()
    if not path:
        return WORK_DIR
    if path == "~":
        return "."
    if path.startswith("~/"):
        return path[2:] or "."
    if path.startswith("/"):
        return path
    return f"{WORK_DIR}/{path}"


def shown_path(path: str) -> str:
    """A path from remote_path the way the model gave it, with ~ for the home"""
    if path.startswith("/"):
        return path
    return "~" if path == "." else f"~/{path}"


def shell_path(path: str | None) -> str:
    """A path for the remote shell, quoted, with ~ and relative paths expanded against $HOME"""
    return shell_quote(remote_path(path))


def shell_quote(resolved: str) -> str:
    """A path from remote_path for the remote shell, quoted, relative to $HOME"""
    if resolved.startswith("/"):
        return shlex.quote(resolved)
    return '"$HOME"' if resolved == "." else f'"$HOME"/{shlex.quote(resolved)}'



# ---- Commands ----

async def run(
    command: str,
    cwd: str | None = None,
    timeout_s: int = 120,
    env: dict[str, str] | None = None,
) -> RunResult:
    """
    Run `command` with bash in a login shell in the sandbox, stdout and stderr together, and stop it after `timeout_s`

    The sandbox's `timeout` stops the command and everything it started; the connection gives up a little later in
    case the sandbox itself stops answering

    Raises:
        SandboxError: The sandbox couldn't be reached
    """
    timeout_s = max(1, min(timeout_s, MAX_TIMEOUT_S))
    folder = shell_path(cwd)
    exports = "".join(f"export {name}={shlex.quote(value)}\n" for name, value in (env or {}).items())
    script = f'mkdir -p {folder} && cd {folder} || exit 1\n{exports}{command}'
    remote = f"timeout --kill-after=10s {timeout_s}s bash -lc {shlex.quote(script)}"

    connection_ = await connection()
    started = time.monotonic()
    head = bytearray()
    tail = bytearray()
    total = 0
    try:
        process = await connection_.create_process(remote, stdin = asyncssh.DEVNULL, stderr = asyncssh.STDOUT,
                                                   encoding = None)
    except (OSError, asyncssh.Error) as e:
        raise SandboxError(f"The sandbox couldn't start the command: {e}.") from None

    async def collect() -> None:
        nonlocal total
        while chunk := await process.stdout.read(65_536):
            total += len(chunk)
            room = OUTPUT_HEAD_BYTES - len(head)
            if room > 0:
                head.extend(chunk[:room])
                chunk = chunk[room:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > OUTPUT_TAIL_BYTES:
                    del tail[:len(tail) - OUTPUT_TAIL_BYTES]
        await process.wait_closed()

    try:
        await asyncio.wait_for(collect(), timeout_s + 30)
    except asyncio.TimeoutError:
        process.close()
    except asyncio.CancelledError:
        # The user stopped the answer: stop the command too rather than leave it running
        try:
            process.send_signal("TERM")
        except (OSError, asyncssh.Error):
            pass
        process.close()
        raise
    seconds = time.monotonic() - started

    exit_status = process.exit_status
    # timeout exits 124 when it stopped the command, or 137 when it had to kill it
    timed_out = exit_status is None or (exit_status in (124, 137) and seconds >= timeout_s)
    omitted = total - len(head) - len(tail)
    output = head.decode("utf-8", "replace")
    if tail:
        output += (f"\n[... {omitted:,} bytes left out ...]\n" if omitted else "") + tail.decode("utf-8", "replace")
    return RunResult(exit_status, output, omitted, seconds, timed_out)
