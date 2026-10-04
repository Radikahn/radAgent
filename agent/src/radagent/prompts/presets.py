"""
The system prompt as three presets the apps can edit and swap between, kept beside the chats

    prompts/prompts.json    {"active": 0-based slot, "slots": [{"name": str, "text": str}, ...]}

It lives in the bucket when RADAGENT_S3_BUCKET is set (under PROMPTS_PREFIX, next to chats/ and memory/), otherwise
in `.agent/prompts`; see radagent.storage. The first time there's no file, slot 1 starts as the prompt the agent
would otherwise run with (the secret prompt, or prompts/system_prompt.txt) and the other two start empty. From then
on the file is what counts: changing the secret prompt doesn't touch it
"""
import json
import sys
import threading
from pathlib import Path
from typing import TypedDict

from radagent.storage import Files, bucket_files


PROMPTS_DIR: Path = Path(".agent/prompts")
PROMPTS_PREFIX: str = "prompts"
PROMPTS_KEY: str = "prompts.json"
SLOTS: int = 3
# A slot's name is a label for the apps; a prompt this long is already far past what's sensible to send every turn
NAME_CHARS: int = 40
PROMPT_CHARS: int = 100_000
SEED_NAME: str = "Default"


class Slot(TypedDict):
    name: str
    text: str


class Presets(TypedDict):
    active: int
    slots: list[Slot]



class PromptError(ValueError):
    """A change the presets can't take, e.g. using an empty slot; the message is for the user"""



class PromptStore:
    """
    The prompt presets, read once and written through on every change

    With S3 reading and writing are requests to the server, which raise radagent.storage.StorageUnavailable when it
    can't be reached
    """

    def __init__(self, seed: str, files: Files | None = None) -> None:
        """
        Args:
            seed: {str} Slot 1's prompt when there are no presets yet
            files: {Files | None} Where the presets live; defaults to the bucket or `.agent/prompts`
        """
        self.seed = seed
        self.files = files or bucket_files(PROMPTS_DIR, PROMPTS_PREFIX)
        self.lock = threading.Lock()
        self.presets: Presets | None = None


    def get(self) -> Presets:
        """Every slot and which one is in use, seeding them the first time"""
        with self.lock:
            return self._load()


    def active(self) -> str:
        """The prompt the agent runs with"""
        presets = self.get()
        return presets["slots"][presets["active"]]["text"]


    def save(self, slot: int, name: str, text: str) -> Presets:
        """
        Replace one slot's prompt; an empty text empties the slot, which the slot in use can't be

        Raises:
            PromptError
        """
        _check_slot(slot)
        name, text = " ".join(name.split())[:NAME_CHARS], text.strip()
        if len(text) > PROMPT_CHARS:
            raise PromptError(f"A prompt can be at most {PROMPT_CHARS:,} characters")
        with self.lock:
            presets = self._load()
            if not text and slot == presets["active"]:
                raise PromptError("The prompt in use can't be empty; switch to another one first")
            slots = list(presets["slots"])
            slots[slot] = {"name": name, "text": text}
            return self._write({"active": presets["active"], "slots": slots})


    def use(self, slot: int) -> Presets:
        """
        Make one slot's prompt the agent's

        Raises:
            PromptError
        """
        _check_slot(slot)
        with self.lock:
            presets = self._load()
            if not presets["slots"][slot]["text"]:
                raise PromptError(f"Slot {slot + 1} is empty; write a prompt in it first")
            return self._write({"active": slot, "slots": presets["slots"]})


    def _load(self) -> Presets:
        if self.presets is None:
            presets = _parse(self.files.read(PROMPTS_KEY))
            if presets is None:
                empty: Slot = {"name": "", "text": ""}
                presets = self._write({"active": 0, "slots": [{"name": SEED_NAME, "text": self.seed.strip()}] + [empty] * (SLOTS - 1)})
            self.presets = presets
        return self.presets


    def _write(self, presets: Presets) -> Presets:
        self.files.write(PROMPTS_KEY, json.dumps(presets, ensure_ascii = False, indent = 2).encode("utf-8"))
        self.presets = presets
        return presets



def _check_slot(slot: int) -> None:
    if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < SLOTS:
        raise PromptError(f"There are {SLOTS} prompt slots, numbered 1 to {SLOTS}")


def _parse(data: bytes | None) -> Presets | None:
    """The saved presets, or None when there are none or they can't be read (then they're seeded again)"""
    if data is None:
        return None
    try:
        saved = json.loads(data)
        slots = [Slot(name = str(slot.get("name") or ""), text = str(slot.get("text") or "")) for slot in saved["slots"]]
        active = saved["active"]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"[radagent] the saved prompts are unreadable, starting them over: {type(e).__name__}: {e}", file = sys.stderr)
        return None
    slots = (slots + [Slot(name = "", text = "")] * SLOTS)[:SLOTS]
    if not isinstance(active, int) or not 0 <= active < SLOTS or not slots[active]["text"]:
        active = next((i for i, slot in enumerate(slots) if slot["text"]), None)
        if active is None:
            return None
    return {"active": active, "slots": slots}
