"""
Checks the sandbox end to end with the agent's own tools: connects with the SANDBOX_* settings from agent/.env (or the
environment), then writes, edits, reads and runs a file, runs a background job, and moves files both ways. Everything
it makes is under ~/work/.smoke-test in the sandbox and a temporary folder here, and is removed at the end

    uv run --project agent python scripts/smoke_sandbox.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "agent" / ".env")
# A relative SANDBOX_SSH_KEY_PATH in agent/.env is relative to agent/, where the agent runs
os.chdir(Path(__file__).resolve().parent.parent / "agent")

from radagent.tools.sandbox.tools import (  # noqa: E402 (needs the settings loaded first)
    sandbox_download, sandbox_edit, sandbox_jobs, sandbox_read, sandbox_run, sandbox_status, sandbox_upload,
    sandbox_write,
)


DIR = ".smoke-test"
failures: list[str] = []


def text(result: dict) -> str:
    return "\n".join(block["text"] for block in result["content"])


def check(name: str, result: dict, expect: str | None = None) -> str:
    output = text(result)
    ok = result["status"] == "success" and (expect is None or expect in output)
    print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        failures.append(name)
        print("     " + output.replace("\n", "\n     "))
    return output


async def main() -> None:
    status = check("status", await sandbox_status(), "Connected to")
    print("     " + status.replace("\n", "\n     "))
    if failures:
        sys.exit(1)

    check("write", await sandbox_write(f"{DIR}/hello.py", "import sys\nprint('hello from', sys.platform)\n"))
    check("edit", await sandbox_edit(f"{DIR}/hello.py", "hello from", "hi from"))
    check("read", await sandbox_read(f"{DIR}/hello.py"), "hi from")
    check("run", await sandbox_run("python3 hello.py", cwd = DIR), "hi from linux")
    check("run exit status", await sandbox_run("exit 3"), "exit 3")
    check("run env", await sandbox_run('echo "$GREETING"', env = {"GREETING": "it's me"}), "it's me")
    check("run timeout", await sandbox_run("sleep 30", timeout_s = 2), "Stopped after 2 s")
    check("run long output", await sandbox_run("seq 1 100000"), "bytes left out")

    started = check("job start", await sandbox_run("for i in 1 2 3; do echo tick $i; sleep 1; done", cwd = DIR,
                                                   background = True), "Started background job")
    job_id = started.split("job ")[1].split(".")[0]
    check("job list", await sandbox_jobs(), job_id)
    await asyncio.sleep(4.5)
    check("job output", await sandbox_jobs("output", job_id), "tick 3")
    long_job = check("long job start", await sandbox_run("sleep 600", background = True), "Started")
    long_id = long_job.split("job ")[1].split(".")[0]
    check("job stop", await sandbox_jobs("stop", long_id), "stopped")
    for job in (job_id, long_id):
        check("job remove", await sandbox_jobs("remove", job), "Removed")

    with tempfile.TemporaryDirectory() as local:
        folder = Path(local, "project")
        (folder / "src").mkdir(parents = True)
        (folder / "src" / "data.txt").write_text("some data\n")
        (folder / ".env").write_text("SECRET=1\n")
        check("upload folder", await sandbox_upload(str(folder), f"{DIR}/project"), "Left out")
        check("credentials stay here", await sandbox_run(f"ls -A {DIR}/project; cat {DIR}/project/src/data.txt"),
              "some data")
        listing = text(await sandbox_run(f"ls -A {DIR}/project"))
        if ".env" in listing:
            failures.append("upload left .env out")
            print("FAIL upload left .env out")
        check("download file", await sandbox_download(f"{DIR}/hello.py", str(Path(local, "back.py"))))
        if "hi from" not in Path(local, "back.py").read_text():
            failures.append("download content")
        check("download folder", await sandbox_download(f"{DIR}/project", str(Path(local, "copy"))))
        copied = sorted(str(p.relative_to(local)) for p in Path(local, "copy").rglob("*"))
        print(f"     downloaded: {copied}")

    check("clean up", await sandbox_run(f"rm -rf {DIR}"))
    print("\nAll good." if not failures else f"\n{len(failures)} failed: {', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
