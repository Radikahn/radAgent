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
GREEN = "\033[32m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""


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



class ResearchPrinter:
    """
    Prints a /research run's progress events as one line per step, then streams the report

    The desktop client turns the same events into live agent windows; see radagent/tools/research/events.py
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._sources: list[dict[str, Any]] = []


    def _line(self, agent: str, text: str, color: str = DIM) -> None:
        print(f"{color}  [{self._names.get(agent, agent)}] {text}{RESET}", flush = True)


    def __call__(self, event: dict[str, Any]) -> None:
        agent: str = event.get("agent", "")
        match event.get("kind"):
            case "phase" if event["phase"] == "planning":
                print(f"{DIM}Planning the research…{RESET}", flush = True)
            case "phase" if event["phase"] == "writing":
                print(f"\n{BOLD}{YELLOW}Report:{RESET}\n", flush = True)
            case "phase" if event["phase"] == "done":
                print(f"\n\n{BOLD}Sources{RESET}")
                for source in self._sources:
                    print(f"{DIM}  [{source['id']}] {source['title']} — {source['url']}{RESET}")
            case "plan":
                print(f"{BOLD}{event['title']}{RESET}")
                for plan in event["agents"]:
                    self._names[plan["id"]] = plan["name"]
                    print(f"{DIM}  {plan['name']} ({plan['platform']}): {plan['brief']}{RESET}")
                print()
            case "search":
                self._line(agent, f"searching: {event['query']}")
            case "page":
                self._line(agent, f"read {event['title']} — {event['final_url']}")
            case "page_failed":
                self._line(agent, f"couldn't open {event['url']}: {event['error']}", RED)
            case "note":
                self._line(agent, f"noted: {event['text']}", BLUE)
            case "agent_done":
                if event["error"]:
                    self._line(agent, f"failed: {event['error']}", RED)
                else:
                    self._line(agent, "done", GREEN)
            case "sources":
                self._sources = event["sources"]
            case "report_delta":
                print(event["delta"], end = "", flush = True)
