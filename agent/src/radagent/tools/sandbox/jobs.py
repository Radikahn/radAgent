"""
Background jobs in the sandbox: commands that run longer than a tool call should wait, like a training run or a big
build. Each job is a folder under ~/.radagent/jobs/<id> holding its command, the process group it runs in, its output
and, once it ends, its exit status. Jobs keep running when the agent disconnects, and survive it entirely
"""
import secrets
import shlex
import time
from dataclasses import dataclass

from radagent.tools.sandbox.client import SandboxError, run, shell_path


JOBS_DIR: str = '"$HOME"/.radagent/jobs'
# Seconds a stopped job gets to exit after SIGTERM before it's killed
STOP_GRACE_S: int = 5

# Starts the job in a session of its own, so stopping it reaches everything it started, then waits until the job
# has written its process ID. $1 is the job's folder, $2 the folder it runs in
_START = r'''
d="$1"
mkdir -p "$d" "$2"
setsid nohup bash -c 'echo $$ > "$1/pid"; cd "$2" && bash -l "$1/command" > "$1/output.log" 2>&1; echo $? > "$1/exit"' _ "$d" "$2" < /dev/null > /dev/null 2>&1 &
for _ in $(seq 50); do [ -s "$d/pid" ] && break; sleep 0.1; done
cat "$d/pid"
'''

# One line per job, newest first (IDs start with the time): id, state, exit status, start time (epoch), the command's first line
_LIST = r'''
cd "$1" 2>/dev/null || exit 0
for d in $(ls -1r); do
  [ -f "$d/command" ] || continue
  pid=$(cat "$d/pid" 2>/dev/null)
  if [ -f "$d/exit" ]; then state=finished; code=$(cat "$d/exit")
  elif [ -n "$pid" ] && kill -0 -- "-$pid" 2>/dev/null; then state=running; code=-
  else state=lost; code=-; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$d" "$state" "$code" "$(stat -c %Y "$d/command")" "$(head -n 1 "$d/command" | cut -c1-120)"
done
'''

_STOP = r'''
pid=$(cat "$1/pid" 2>/dev/null) || { echo "no such job"; exit 3; }
[ -f "$1/exit" ] && { echo "already finished"; exit 0; }
kill -TERM -- "-$pid" 2>/dev/null || { echo "not running"; exit 0; }
for _ in $(seq $(( $2 * 10 ))); do kill -0 -- "-$pid" 2>/dev/null || break; sleep 0.1; done
if kill -0 -- "-$pid" 2>/dev/null; then kill -KILL -- "-$pid" 2>/dev/null; echo killed; else echo stopped; fi
[ -f "$1/exit" ] || echo stopped > "$1/exit"
'''



@dataclass(frozen = True)
class Job:
    id: str
    state: str
    exit: str
    started: float
    command: str


    def line(self) -> str:
        if self.state != "finished":
            status = self.state
        else:
            status = f"exit {self.exit}" if self.exit.isdigit() else self.exit
        return f"{self.id}  {status}  started {_ago(self.started)}  {self.command}"


def _ago(epoch: float) -> str:
    seconds = max(0, int(time.time() - epoch))
    for unit, size in (("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"


def _job_dir(job_id: str) -> str:
    if not job_id or not all(c.isalnum() or c == "-" for c in job_id):
        raise SandboxError(f"{job_id!r} isn't a job ID; sandbox_jobs lists them.")
    return f"{JOBS_DIR}/{job_id}"


def _script(body: str, *args: str) -> str:
    """`body` as a script with positional arguments, which the shell expands where they're used"""
    return f"bash -c {shlex.quote(body)} _ {' '.join(args)}"


async def _checked(command: str, what: str) -> str:
    result = await run(command, timeout_s = 60)
    if result.exit_status != 0:
        raise SandboxError(f"Couldn't {what}: {result.output.strip() or f'exit {result.exit_status}'}")
    return result.output


async def start(command: str, cwd: str | None = None) -> str:
    """Start `command` as a job and return its ID"""
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
    folder = _job_dir(job_id)
    # The command goes into a file rather than through another layer of quoting
    write = f"mkdir -p {folder} && printf '%s\\n' {shlex.quote(command)} > {folder}/command"
    await _checked(write, "save the job's command")
    await _checked(_script(_START, folder, shell_path(cwd)), "start the job")
    return job_id


async def jobs() -> list[Job]:
    output = await _checked(_script(_LIST, JOBS_DIR), "list the jobs")
    found: list[Job] = []
    for line in output.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            job_id, state, code, started, command = parts
            found.append(Job(job_id, state, code, float(started) if started.isdigit() else 0.0, command))
    return found


async def output(job_id: str, lines: int) -> str:
    """The job's state and the last `lines` lines of its output"""
    folder = _job_dir(job_id)
    found = {job.id: job for job in await jobs()}
    if job_id not in found:
        raise SandboxError(f"There's no job {job_id}; sandbox_jobs lists them.")
    log = await _checked(f"tail -n {lines} {folder}/output.log 2>/dev/null; true", "read the job's output")
    return f"{found[job_id].line()}\n\n{log.rstrip() or '(no output yet)'}"


async def stop(job_id: str) -> str:
    result = await _checked(_script(_STOP, _job_dir(job_id), str(STOP_GRACE_S)), "stop the job")
    return result.strip()


async def remove(job_id: str) -> None:
    """Delete a job that isn't running, with its output"""
    found = {job.id: job for job in await jobs()}
    if job_id not in found:
        raise SandboxError(f"There's no job {job_id}; sandbox_jobs lists them.")
    if found[job_id].state == "running":
        raise SandboxError(f"Job {job_id} is still running; stop it first.")
    await _checked(f"rm -rf {_job_dir(job_id)}", "remove the job")
