import os
import sys
from typing import Any

# Skip colors when output isn't a terminal (e.g. piped to a file) or NO_COLOR is set
_USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ

RESET = "\033[0m" if _USE_COLOR else ""
BOLD = "\033[1m" if _USE_COLOR else ""
DIM = "\033[2m" if _USE_COLOR else ""
BLUE = "\033[34m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""


class ReplCallbackHandler:
    """
    Streams agent output to the terminal with labelled, colored sections

    Thinking is printed in blue under `Thinking:`, the reply in yellow under `<name>:`
    """

    def __init__(self, assistant_name: str = "Uma") -> None:
        self.assistant_name = assistant_name
        self.tool_count = 0
        self._section: str | None = None

    def start_turn(self) -> None:
        """Reset state so the next response gets fresh labels"""
        self._section = None

    def end_turn(self) -> None:
        """Close the last section with a newline"""
        if self._section is not None:
            print()
        self._section = None

    def _enter(self, section: str, label: str, color: str) -> None:
        if self._section == section:
            return
        if self._section is not None:
            print("\n")
        print(f"{BOLD}{color}{label}{RESET} ", end = "")
        self._section = section

    def __call__(self, **kwargs: Any) -> None:
        reasoning: str | None = kwargs.get("reasoningText")
        data: str = kwargs.get("data", "")
        tool_use = kwargs.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")

        if reasoning:
            self._enter("thinking", "Thinking:", BLUE)
            print(f"{BLUE}{reasoning}{RESET}", end = "", flush = True)

        if data:
            self._enter("reply", f"{self.assistant_name}:", YELLOW)
            print(f"{YELLOW}{data}{RESET}", end = "", flush = True)

        if tool_use:
            self.tool_count += 1
            if self._section is not None:
                print("\n")
            print(f"{DIM}[tool #{self.tool_count}: {tool_use['name']}]{RESET}")
            self._section = None
