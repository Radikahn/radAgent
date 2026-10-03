import re
from collections.abc import Mapping
from pathlib import Path
from radagent.prompts.lib import SYSTEM_PROMPT_PATH
from strands.types.tools import ToolSpec

# A description's first sentence ends at the first ., ! or ? followed by a capitalized word, so "e.g. `x`" doesn't end it
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

def _load_system_prompt(path: Path) -> str:
    with open(path, "r", encoding='utf-8') as file:
        prompt: str = file.read()
        file.close()
        return prompt


def initalize_agent(override_prompt_path: Path = SYSTEM_PROMPT_PATH) -> str:
    """
    Load all prompts (system, tools, etc..) in to memory
    """
    SYSTEM_PROMPT = _load_system_prompt(path =  override_prompt_path)

    return SYSTEM_PROMPT


def append_tools(prompt: str, tools: Mapping[str, ToolSpec]) -> str:
    """
    Append the agent's tools to the end of a system prompt, one "- name: summary" line each

    The prompts end on a heading for this list, so it lands right under it. The model gets each tool's full spec
    separately; the summary is just the first sentence of its description

    Args:
        prompt: {str} The system prompt
        tools: {Mapping[str, ToolSpec]} Every tool the agent has by name, e.g. `agent.tool_registry.get_all_tools_config()`

    Returns:
        prompt: {str} The prompt with the tool list as its last lines
    """
    lines = []
    for name, spec in tools.items():
        summary = _SENTENCE_END.split(" ".join(spec.get("description", "").split()), maxsplit = 1)[0]
        lines.append(f"- {name}: {summary}" if summary else f"- {name}")

    return prompt.rstrip() + "\n" + "\n".join(lines)
