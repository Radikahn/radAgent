import asyncio
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeModelCallEvent, HookProvider, HookRegistry
from strands.types.tools import ToolResultContent

from radagent.media.files import (
    MAX_DOCUMENTS_PER_MESSAGE,
    MAX_IMAGES_PER_MESSAGE,
    MediaError,
    document_block,
    image_block,
)



class MediaGuard(HookProvider):
    """
    Keeps the images and documents that tools return within what Bedrock accepts

    Bedrock fails a whole request over one oversized block, and because the block stays in the conversation every
    later turn fails too. So oversized images are shrunk, and a document that can't be sent is swapped for a note
    telling the model why. The results of one step's tool calls share a message, which Bedrock caps at 20 images
    and 5 documents; anything past the cap is swapped for a note asking the model to read it in another step.
    Covers the harness's `read` as well as our own tools
    """

    def __init__(self) -> None:
        # Images and documents returned so far in the current step, per agent (subagents share these hooks)
        self._counts: dict[int, dict[str, int]] = {}


    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._next_step)
        registry.add_callback(AfterToolCallEvent, self._check_result)


    def _next_step(self, event: BeforeModelCallEvent) -> None:
        # Tool calls made after this model call put their results in a new message
        self._counts[id(event.agent)] = {"image": 0, "document": 0}


    async def _check_result(self, event: AfterToolCallEvent) -> None:
        content = event.result.get("content", [])
        if not any("image" in block or "document" in block for block in content):
            return

        counts = self._counts.setdefault(id(event.agent), {"image": 0, "document": 0})
        checked = [await self._check_block(block, counts) for block in content]
        event.result = {**event.result, "content": checked}


    async def _check_block(self, block: ToolResultContent, counts: dict[str, int]) -> ToolResultContent:
        kind = "image" if "image" in block else "document" if "document" in block else None
        if kind is None:
            return block

        cap = MAX_IMAGES_PER_MESSAGE if kind == "image" else MAX_DOCUMENTS_PER_MESSAGE
        if counts[kind] >= cap:
            return {"text": f"[{kind} not shown: one step can return at most {cap}. Read it again in a separate step.]"}
        # Claim the slot before converting, since parallel tool calls finish their results concurrently
        counts[kind] += 1

        media = block[kind]
        data = media.get("source", {}).get("bytes")
        # Media referenced by location (e.g. S3) isn't ours to check
        if not isinstance(data, bytes):
            return block
        try:
            if kind == "image":
                # Shrinking a large photo takes a moment, so it runs off the event loop
                return await asyncio.to_thread(image_block, data)
            checked = document_block(data, media.get("format", "pdf"), media.get("name", "document"))
            # Keep anything else the tool set, such as citations
            return {"document": {**media, "name": checked["document"]["name"]}}
        except MediaError as e:
            counts[kind] -= 1
            return {"text": f"[{kind} not shown: {e}. Tell the user if they need it.]"}
