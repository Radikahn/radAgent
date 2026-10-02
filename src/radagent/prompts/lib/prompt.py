from pathlib import Path
from radagent.prompts.lib import SYSTEM_PROMPT_PATH

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
