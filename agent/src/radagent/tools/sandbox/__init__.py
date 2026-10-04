from typing import Any

from radagent.tools.sandbox.tools import (
    sandbox_download,
    sandbox_edit,
    sandbox_jobs,
    sandbox_read,
    sandbox_run,
    sandbox_status,
    sandbox_upload,
    sandbox_write,
)

# The sandbox suite: running code on the user's server first, then its files, then moving files to and from it
SANDBOX_TOOLS: list[Any] = [
    sandbox_status,
    sandbox_run,
    sandbox_jobs,
    sandbox_write,
    sandbox_read,
    sandbox_edit,
    sandbox_upload,
    sandbox_download,
]

__all__ = ["SANDBOX_TOOLS"]
