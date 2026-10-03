"""
Chats are separate conversations with the agent, each with its own context and its own memory

Every chat lives in a folder named after its id, under `.agent/chats/` or, when RADAGENT_S3_BUCKET is set, in an
S3 bucket every device shares (see radagent.storage):
    chat.json    title and timestamps, written when the first message is sent
    memory/      facts the agent distilled from this chat, one markdown file per fact
    session/     the harness's conversation snapshots; reopening a chat restores its context from these
    offloaded/   large tool results the harness moved out of the context
    cards.jsonl  cards the chat showed, so they render again when it's reopened

A chat only recalls its own memory. The /memory command lets a single message look through the others; see
radagent.tools.chats
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, TypeGuard, cast

from strands.storage import LocalFileStorage, S3Storage

from radagent.storage import Files, StorageUnavailable, bucket_files, chat_files


CHATS_DIR: Path = Path(".agent/chats")
# The shared memory from before there were chats; /memory searches it alongside the other chats. With a bucket it
# sits under LEGACY_MEMORY_PREFIX, beside the chats
LEGACY_MEMORY_DIR: Path = Path(".agent/memory")
LEGACY_MEMORY_PREFIX: str = "memory"
# Sidebar titles are the first message, cut at a word boundary near this length
TITLE_CHARS: int = 48

# The client makes ids; keeping them short and alphanumeric means one can never point outside the chats' root
_CHAT_ID = re.compile(r"[a-z0-9]{6,32}")


class ChatInfo(TypedDict):
    id: str
    title: str
    created_at: str     # ISO 8601, UTC
    updated_at: str



def make_title(text: str) -> str:
    """A sidebar title from the chat's first message"""
    line = " ".join(text.split())
    if len(line) <= TITLE_CHARS:
        return line or "New chat"
    cut = line[:TITLE_CHARS].rsplit(" ", 1)[0] or line[:TITLE_CHARS]
    return cut.rstrip(",.;:!?") + "…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec = "seconds")


def _info(data: bytes | None) -> ChatInfo | None:
    try:
        info = json.loads(data) if data else None
    except ValueError:
        return None
    # Only the fields recent() sorts on are checked; the rest is what touch() wrote
    return cast(ChatInfo, info) if isinstance(info, dict) and "updated_at" in info else None



class ChatStore:
    """
    The chats: listing, creating, deleting, and reading back what was said in each

    With S3 every call is a request to the server, which raises radagent.storage.StorageUnavailable when it can't
    be reached
    """

    def __init__(self, files: Files | None = None) -> None:
        """
        Args:
            files: {Files | None} Where the chats live; defaults to the bucket or `.agent/chats`, see radagent.storage
        """
        self.files = files or chat_files(CHATS_DIR)


    @staticmethod
    def valid_id(chat_id: Any) -> TypeGuard[str]:
        return isinstance(chat_id, str) and _CHAT_ID.fullmatch(chat_id) is not None


    def _key(self, chat_id: str, name: str = "") -> str:
        """The key of `name` in the chat's folder, or of the folder itself"""
        if not self.valid_id(chat_id):
            raise ValueError(f"Not a chat id: {chat_id!r}")
        return f"{chat_id}/{name}" if name else chat_id


    def storage(self, chat_id: str, folder: str = "") -> LocalFileStorage | S3Storage:
        """A Strands storage over the chat's folder, or a folder in it, for the harness to save into"""
        return self.files.storage(self._key(chat_id, folder))


    def info(self, chat_id: str) -> ChatInfo | None:
        """The chat's title and timestamps, or None for a chat that hasn't had a message yet"""
        try:
            return _info(self.files.read(self._key(chat_id, "chat.json")))
        except OSError:
            return None


    def recent(self) -> list[ChatInfo]:
        """Every chat, most recently active first"""
        ids = [name for name in self.files.folders() if self.valid_id(name)]
        found = self.files.read_many(self._key(chat_id, "chat.json") for chat_id in ids)
        chats = [info for data in found if (info := _info(data))]
        return sorted(chats, key = lambda chat: chat["updated_at"], reverse = True)


    def touch(self, chat_id: str, first_message: str = "") -> ChatInfo:
        """Mark the chat as just active, creating it (titled after `first_message`) if this is its first message"""
        now = _now()
        info = self.info(chat_id) or ChatInfo(id = chat_id, title = make_title(first_message), created_at = now, updated_at = now)
        info["updated_at"] = now
        self.files.write(self._key(chat_id, "chat.json"), json.dumps(info, ensure_ascii = False, indent = 2).encode("utf-8"))
        return info


    def forget(self, chat_id: str) -> None:
        """Take the chat off the list right away; `delete` removes its folder once nothing is writing to it"""
        self.files.delete(self._key(chat_id, "chat.json"))


    def delete(self, chat_id: str) -> None:
        self.files.delete_folder(self._key(chat_id))


    def saved(self, chat_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        The chat's conversation in Strands message format and its agent's `agent.state`, as the harness last saved
        them; both empty before the first message. One read for both, which counts when the chats are on a server
        """
        # The harness keeps it at session/<id>/scopes/agent/default/snapshots/; searching for the file instead of
        # spelling out that path keeps this working if the layout shifts
        session = self.files.entries(self._key(chat_id, "session"))
        key = next((entry.key for entry in session if entry.key.endswith("/snapshot_latest.json")), None)
        try:
            data = json.loads(self.files.read(key) or b"")["data"] if key else {}
        except (OSError, ValueError, KeyError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        messages, state = data.get("messages"), data.get("state")
        return (messages if isinstance(messages, list) else [], state if isinstance(state, dict) else {})


    def messages(self, chat_id: str) -> list[dict[str, Any]]:
        """The chat's conversation in Strands message format"""
        return self.saved(chat_id)[0]


    def state(self, chat_id: str) -> dict[str, Any]:
        """The chat agent's saved `agent.state`"""
        return self.saved(chat_id)[1]


    def memories(self, chat_id: str) -> list[str]:
        """The facts the agent remembers from this chat"""
        return _read_facts(self.files, self._key(chat_id, "memory"))


    def add_card(self, chat_id: str, tool_use_id: str, card: Any) -> None:
        """
        Keep a card the chat showed; cards stream to the client and aren't part of the saved conversation

        Best effort: a card that can't be saved still showed, it just won't come back when the chat is reopened,
        so failing to reach the storage is logged rather than ending the turn that showed it
        """
        line = json.dumps({"id": tool_use_id, "card": card}, ensure_ascii = False) + "\n"
        try:
            self.files.append(self._key(chat_id, "cards.jsonl"), line.encode("utf-8"))
        except StorageUnavailable as e:
            print(f"[radagent] saving a card failed: {e}", file = sys.stderr)


    def cards(self, chat_id: str) -> dict[str, Any]:
        """The chat's cards by the id of the tool call that showed them"""
        try:
            lines = (self.files.read(self._key(chat_id, "cards.jsonl")) or b"").decode("utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return {}
        cards: dict[str, Any] = {}
        for line in lines:
            try:
                entry = json.loads(line)
                cards[entry["id"]] = entry["card"]
            except (ValueError, KeyError, TypeError):
                continue
        return cards



def _read_facts(files: Files, folder: str) -> list[str]:
    """The facts in a memory folder, oldest first"""
    prefix = f"{folder}/" if folder else ""
    # Only the markdown files directly in the folder, as the memory store writes them
    entries = sorted(
        (entry for entry in files.entries(folder) if entry.key.endswith(".md") and "/" not in entry.key[len(prefix):]),
        key = lambda entry: entry.modified,
    )
    facts = []
    for data in files.read_many(entry.key for entry in entries):
        try:
            if data and (fact := data.decode("utf-8").strip()):
                facts.append(fact)
        except UnicodeDecodeError:
            continue
    return facts


def read_legacy_memories() -> list[str]:
    """The facts in the memory from before chats, oldest first; in the bucket when there is one"""
    return _read_facts(bucket_files(LEGACY_MEMORY_DIR, LEGACY_MEMORY_PREFIX), "")
