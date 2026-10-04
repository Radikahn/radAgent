import asyncio
import os
import posixpath
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import asyncssh
from strands import tool

from radagent.tools.sandbox import jobs
from radagent.tools.sandbox.client import (
    MAX_TIMEOUT_S, SandboxError, connection, describe, remote_path, run, shell_quote, shown_path,
)
from radagent.tools.web.trust_gate import protected_path


# sandbox_read shows at most this much of a file, and a page of this many lines unless asked for more
MAX_READ_BYTES: int = 1_000_000
DEFAULT_READ_LINES: int = 400
MAX_READ_LINES: int = 2_000
# Files bigger than this aren't read or edited as text; download them instead
MAX_EDIT_BYTES: int = 5_000_000
# Uploads and downloads past this are refused, so one transfer can't fill either disk
MAX_TRANSFER_BYTES: int = 2 * 1024 ** 3
# Where sandbox_download puts files when it isn't told where, relative to the agent's working directory
DOWNLOADS_DIR: str = "sandbox-downloads"

JobAction = Literal["list", "output", "stop", "remove"]



async def _result(name: str, work: Callable[[], Awaitable[str]]) -> dict[str, Any]:
    """Run a tool's work and turn what it says, or the reason it couldn't, into the tool result"""
    try:
        text = await work()
    except SandboxError as e:
        return {"status": "error", "content": [{"text": f"{name} failed: {e}"}]}
    except asyncssh.SFTPError as e:
        return {"status": "error", "content": [{"text": f"{name} failed: {e.reason}"}]}
    except Exception as e:
        return {"status": "error", "content": [{"text": f"{name} failed: {type(e).__name__}: {e}"}]}
    return {"status": "success", "content": [{"text": text}]}


def _size(bytes_: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if bytes_ < 1024 or unit == "GB":
            return f"{bytes_:,} {unit}" if unit == "bytes" else f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    raise AssertionError("unreachable")


async def _read_text(sftp: asyncssh.SFTPClient, path: str, limit: int) -> tuple[str, int]:
    """A remote file's text, up to `limit` bytes, and its full size"""
    attrs = await sftp.stat(path)
    if attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
        raise SandboxError(f"{shown_path(path)} is a folder; list it with sandbox_run (ls).")
    async with sftp.open(path, "rb") as file:
        data = await file.read(limit)
    if b"\0" in data[:8_192]:
        raise SandboxError(f"{shown_path(path)} is a binary file; use sandbox_download to fetch it.")
    return data.decode("utf-8", "replace"), attrs.size or len(data)


async def _write_text(sftp: asyncssh.SFTPClient, path: str, text: str, append: bool = False) -> int:
    parent = posixpath.dirname(path)
    if parent:
        await sftp.makedirs(parent, exist_ok = True)
    data = text.encode("utf-8")
    async with sftp.open(path, "ab" if append else "wb") as file:
        await file.write(data)
    return len(data)



@tool
async def sandbox_status() -> dict[str, Any]:
    """Check the sandbox, the Linux machine on the user's server where you can write, run and test code: whether it's reachable, what it runs on (CPUs, memory, disk, Python, Node) and which background jobs are running. Use it when the user asks about the sandbox or a sandbox tool fails to connect.

    The sandbox is an Ubuntu container you reach as the user `agent`, without root or sudo. Your files live in ~/work and stay there between chats. Install packages per project in your home: uv or python3 -m venv for Python, npm for Node. It can reach the internet but not the user's home network.
    """
    async def work() -> str:
        where = await describe()
        result = await run(
            'echo "$(uname -srm), $(nproc) CPUs, $(free -h | awk \'/^Mem/ {print $2 " memory, " $7 " free"}\')"; '
            'df -h "$HOME" | awk \'NR==2 {print $4 " free of " $2 " on disk"}\'; '
            'echo "$(python3 --version 2>&1), uv $(uv --version 2>/dev/null | cut -d" " -f2), '
            'node $(node --version 2>/dev/null), $(git --version 2>/dev/null)"; '
            'echo "up $(uptime -p | sed "s/^up //")"',
            timeout_s = 30,
        )
        running = [job for job in await jobs.jobs() if job.state == "running"]
        lines = [f"Connected to {where}.", result.output.strip()]
        lines.append(f"{len(running)} background job{'s' if len(running) != 1 else ''} running"
                     + (":\n" + "\n".join(job.line() for job in running) if running else "."))
        return "\n".join(lines)

    return await _result("sandbox_status", work)


@tool
async def sandbox_run(
    command: str,
    cwd: str | None = None,
    timeout_s: int = 120,
    background: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a shell command in the sandbox, the Linux machine on the user's server, and get its exit status and output (stdout and stderr together). Use it to run and test code you wrote there, install a project's dependencies, run builds, test suites and scripts, and anything that needs real compute.

    Commands run with bash in a login shell as the user `agent`, without root or sudo, starting in ~/work (made if missing); files persist between commands and chats. The sandbox can reach the internet but not the user's home network. Each call is a new shell, so `cd` and `export` don't carry over: pass `cwd` and `env`, or chain commands with &&. Long output keeps its start and end.

    A command is stopped after `timeout_s`. For anything longer (training, long builds, servers, crawls), set background=True: it returns at once with a job ID, and sandbox_jobs shows its output and stops it.

    Args:
        command: The bash command or script to run, e.g. "uv run pytest -q" or "python3 train.py --epochs 3".
        cwd: Folder to run in: relative paths are inside ~/work, and ~ is the home folder. Defaults to ~/work.
        timeout_s: Seconds before the command is stopped, up to 1800. Ignored with background=True.
        background: Start the command as a background job instead of waiting for it.
        env: Environment variables to set for the command.
    """
    if not command.strip():
        return {"status": "error", "content": [{"text": "sandbox_run needs a command."}]}

    async def work() -> str:
        if background:
            # The job outlives this call, so its variables go into its command
            exports = "".join(f"export {name}={shlex.quote(value)}\n" for name, value in (env or {}).items())
            job_id = await jobs.start(exports + command, cwd)
            return (f"Started background job {job_id}. Check on it with sandbox_jobs(action=\"output\", "
                    f"job_id=\"{job_id}\"); it keeps running until it finishes or you stop it.")
        result = await run(command, cwd, timeout_s, env)
        where = shown_path(remote_path(cwd))
        if result.timed_out:
            status = (f"Stopped after {min(timeout_s, MAX_TIMEOUT_S)} s (the timeout). For long work run it with "
                      f"background=True")
        else:
            status = f"exit {result.exit_status}"
        return f"{status} · {result.seconds:.1f} s · in {where}\n{result.output.rstrip() or '(no output)'}"

    return await _result("sandbox_run", work)


@tool
async def sandbox_jobs(
    action: JobAction = "list",
    job_id: str | None = None,
    lines: int = 100,
) -> dict[str, Any]:
    """See and manage the sandbox's background jobs, the long commands started with sandbox_run(background=True): list them with their state, read a job's latest output, stop one, or remove a finished one with its output.

    Args:
        action: list (every job, newest first), output (a job's state and the end of its output), stop (end a running job and everything it started), or remove (delete a job that isn't running).
        job_id: The job, for output, stop and remove.
        lines: For output: how many lines from the end of its output, 1 to 2000.
    """
    async def work() -> str:
        if action == "list":
            found = await jobs.jobs()
            return "\n".join(job.line() for job in found) if found else "No background jobs."
        if not job_id:
            raise SandboxError(f"{action} needs a job_id; list the jobs to find it.")
        if action == "output":
            return await jobs.output(job_id, min(max(lines, 1), MAX_READ_LINES))
        if action == "stop":
            return f"Job {job_id}: {await jobs.stop(job_id)}."
        await jobs.remove(job_id)
        return f"Removed job {job_id}."

    return await _result("sandbox_jobs", work)


@tool
async def sandbox_write(
    path: str,
    content: str,
    append: bool = False,
    executable: bool = False,
) -> dict[str, Any]:
    """Write a text file in the sandbox, replacing it if it exists and making its folders. Use it to put code, configs and data you've written onto the sandbox before running them with sandbox_run.

    Args:
        path: The file: relative paths are inside ~/work, e.g. "myproject/main.py"; ~ is the home folder.
        content: The file's whole text.
        append: Add to the end of the file instead of replacing it.
        executable: Make the file executable (chmod +x), e.g. for a script.
    """
    async def work() -> str:
        target = remote_path(path)
        async with (await connection()).start_sftp_client() as sftp:
            written = await _write_text(sftp, target, content, append)
            if executable:
                mode = (await sftp.stat(target)).permissions or 0o644
                await sftp.chmod(target, mode | 0o111)
        verb = "Appended" if append else "Wrote"
        return f"{verb} {_size(written)} to {shown_path(target)}."

    return await _result("sandbox_write", work)


@tool
async def sandbox_read(path: str, offset: int = 1, limit: int = DEFAULT_READ_LINES) -> dict[str, Any]:
    """Read a text file in the sandbox, with line numbers. Use it to look at code, logs and results there; for binary files such as images, use sandbox_download and then look at the local copy.

    Args:
        path: The file: relative paths are inside ~/work; ~ is the home folder.
        offset: The first line to show, counting from 1.
        limit: How many lines to show, up to 2000.
    """
    async def work() -> str:
        target = remote_path(path)
        async with (await connection()).start_sftp_client() as sftp:
            text, size = await _read_text(sftp, target, MAX_READ_BYTES)
        lines = text.splitlines()
        start = max(offset, 1)
        shown = lines[start - 1:start - 1 + min(max(limit, 1), MAX_READ_LINES)]
        header = f"{shown_path(target)} · {_size(size)} · {len(lines):,} lines"
        if size > MAX_READ_BYTES:
            header += f" in the first {_size(MAX_READ_BYTES)} (the rest isn't shown; use sandbox_run with tail or grep)"
        if not shown:
            return f"{header}\n(no lines from {start})"
        end = start + len(shown) - 1
        if start > 1 or end < len(lines):
            header += f", showing {start}-{end}"
        numbered = "\n".join(f"{start + i:>6}\t{line}" for i, line in enumerate(shown))
        return f"{header}\n{numbered}"

    return await _result("sandbox_read", work)


@tool
async def sandbox_edit(path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict[str, Any]:
    """Change part of a text file in the sandbox by replacing exact text, without rewriting the whole file. The old_text has to match the file exactly, whitespace included, and only once unless replace_all is set; read the file first with sandbox_read (leave out its line numbers).

    Args:
        path: The file: relative paths are inside ~/work; ~ is the home folder.
        old_text: The exact text to replace.
        new_text: What to put in its place.
        replace_all: Replace every match instead of requiring exactly one.
    """
    async def work() -> str:
        if not old_text:
            raise SandboxError("old_text can't be empty; use sandbox_write to write a whole file.")
        target = remote_path(path)
        async with (await connection()).start_sftp_client() as sftp:
            text, size = await _read_text(sftp, target, MAX_EDIT_BYTES + 1)
            if size > MAX_EDIT_BYTES:
                raise SandboxError(f"{shown_path(target)} is {_size(size)}, too big to edit as text.")
            count = text.count(old_text)
            if count == 0:
                raise SandboxError(f"old_text isn't in {shown_path(target)}; read the file to copy it exactly.")
            if count > 1 and not replace_all:
                raise SandboxError(f"old_text is in {shown_path(target)} {count} times; give more surrounding text "
                                   "to pick one, or set replace_all.")
            await _write_text(sftp, target, text.replace(old_text, new_text))
        return f"Replaced {count} match{'es' if count > 1 else ''} in {shown_path(target)}."

    return await _result("sandbox_edit", work)


def _local_files(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    """
    The files to upload from `root` with their paths relative to it, and the ones left out because they hold
    credentials (.env, .ssh and the like), which never leave this machine
    """
    if root.is_file():
        return [(root, root.name)], []
    files: list[tuple[Path, str]] = []
    skipped: list[str] = []
    for folder, dirs, names in os.walk(root):
        for name in list(dirs):
            if protected_path(os.path.join(folder, name)):
                dirs.remove(name)
                skipped.append(os.path.relpath(os.path.join(folder, name), root) + "/")
        for name in names:
            path = Path(folder, name)
            relative = path.relative_to(root).as_posix()
            if protected_path(str(path)):
                skipped.append(relative)
            elif path.is_file():
                files.append((path, relative))
    return files, skipped


@tool
async def sandbox_upload(local_path: str, sandbox_path: str | None = None) -> dict[str, Any]:
    """Copy a file or folder from this machine (where you run, with your own shell and file tools) to the sandbox. Use it for files the user gave you or that you made here, such as data, a project or an attachment you saved.

    Files that hold credentials (.env, .ssh, .aws and the like) are never uploaded; a folder is copied without them.

    Args:
        local_path: The file or folder here; relative paths are relative to your working directory.
        sandbox_path: Where it goes in the sandbox: relative paths are inside ~/work, ~ is the home folder. Defaults to its name in ~/work.
    """
    async def work() -> str:
        source = Path(local_path).expanduser()
        if not source.exists():
            raise SandboxError(f"{local_path} doesn't exist here.")
        files, skipped = await asyncio.to_thread(_local_files, source)
        total = sum(path.stat().st_size for path, _ in files)
        if total > MAX_TRANSFER_BYTES:
            raise SandboxError(f"{local_path} is {_size(total)}, more than the {_size(MAX_TRANSFER_BYTES)} limit.")

        target = remote_path(sandbox_path or source.resolve().name)
        async with (await connection()).start_sftp_client() as sftp:
            if source.is_file():
                if await sftp.isdir(target):
                    target = posixpath.join(target, source.name)
                await sftp.makedirs(posixpath.dirname(target) or ".", exist_ok = True)
                await sftp.put(str(source), target)
            else:
                await sftp.makedirs(target, exist_ok = True)
                for path, relative in files:
                    destination = posixpath.join(target, relative)
                    await sftp.makedirs(posixpath.dirname(destination), exist_ok = True)
                    await sftp.put(str(path), destination)

        what = "1 file" if source.is_file() else f"{len(files):,} files"
        text = f"Uploaded {what} ({_size(total)}) to {shown_path(target)}."
        if skipped:
            text += f" Left out, since they hold credentials: {', '.join(skipped[:20])}."
        return text

    return await _result("sandbox_upload", work)


@tool
async def sandbox_download(sandbox_path: str, local_path: str | None = None) -> dict[str, Any]:
    """Copy a file or folder from the sandbox to this machine (where you run). Use it to bring back results: download a chart, image or PDF the code made and then look at it with your file reading tool, or fetch output to share with the user.

    Args:
        sandbox_path: The file or folder in the sandbox: relative paths are inside ~/work, ~ is the home folder.
        local_path: Where to put it here. Defaults to sandbox-downloads/<its name> in your working directory.
    """
    async def work() -> str:
        source = remote_path(sandbox_path)
        async with (await connection()).start_sftp_client() as sftp:
            if not await sftp.exists(source):
                raise SandboxError(f"{shown_path(source)} doesn't exist in the sandbox.")
            folder = await sftp.isdir(source)
            if folder:
                result = await run(f"du -sb -- {shell_quote(source)} | cut -f1", timeout_s = 60)
                total = int(result.output.strip() or 0) if result.output.strip().isdigit() else 0
            else:
                total = (await sftp.stat(source)).size or 0
            if total > MAX_TRANSFER_BYTES:
                raise SandboxError(f"{shown_path(source)} is {_size(total)}, more than the "
                                   f"{_size(MAX_TRANSFER_BYTES)} limit.")

            target = Path(local_path).expanduser() if local_path else Path(DOWNLOADS_DIR, posixpath.basename(source))
            if target.is_dir() and not folder:
                target = target / posixpath.basename(source)
            await asyncio.to_thread(target.parent.mkdir, parents = True, exist_ok = True)
            await sftp.get(source, str(target), recurse = folder)

        return f"Downloaded {shown_path(source)} ({_size(total)}) to {target.resolve()}."

    return await _result("sandbox_download", work)
