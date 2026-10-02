from dotenv import load_dotenv
from pathlib import Path
from collections.abc import Callable
from typing import Any
from os import getenv

from radagent.config import MODEL

from radagent.prompts.lib.prompt import initalize_agent
from strands.agent import AgentResult
from strands_harness import create_harness
from strands import Agent


# Agent runtime configuratin
load_dotenv()
SYSTEM_PROMPT: str = initalize_agent()



class RadAgent:
    def __init__(
        self,
        model: str | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        callback_handler: Callable[..., Any] | None = None
    ) -> None:
        """
        Initialize a RadAgent with all configuration and system prompts

        Args:
            model: {str} Default model is defined in `config.py`
            system_prompt: {str} Default is the prompt in `prompts/system_prompt.txt`
            callback_handler: {Callable | None} Receives streamed events; Strands prints to stdout when omitted
        """
        if not model: model = MODEL

        # Only pass the handler when given, so Strands keeps its default printer otherwise
        agent_kwargs: dict[str, Any] = {}
        if callback_handler is not None:
            agent_kwargs["callback_handler"] = callback_handler

        # Bedrock has no native web search, so drop it from the default tool set
        self.AGENT: Agent = create_harness(
            model = model,
            instructions = system_prompt,
            builtin_tools = {"web_search": False},
            **agent_kwargs
        )


    def query(self, query: str, image: Any | None = None, **kwargs) -> AgentResult:
        """
        Pass provided query to strands agent

        System prompts and tooling are also passed within this request
        The intended use is when user asks the agent a question through normal converstaion and expects agent character
        response

        Args:
            query: {str}
            image: Any | None
            **kwargs

        Returns:
            response: {AgentResult}
        """

        ##TODO: Handle kwargs
        #TODO: add image support via content_block arg
        response: AgentResult = self.AGENT(prompt = query)

        return response
