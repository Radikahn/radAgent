import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from strands.types.content import ContentBlock
from strands.types.session import decode_bytes_values


# Bedrock's per-message limits for Claude; a request that breaks one fails outright
MAX_IMAGE_BYTES: int = 3_750_000
MAX_IMAGE_PX: int = 8_000
MAX_DOCUMENT_BYTES: int = 4_500_000
MAX_IMAGES_PER_MESSAGE: int = 20
MAX_DOCUMENTS_PER_MESSAGE: int = 5
# Images are shrunk to this edge. Claude scales anything past ~1568 px down itself, and images are capped at
# 2000 px once a request holds more than 20 (every turn resends the whole conversation), so this costs nothing
# and keeps long conversations valid
MAX_IMAGE_EDGE_PX: int = 2_000
# Text files are cut here (about 25k tokens) so one log file can't fill the context
MAX_TEXT_CHARS: int = 100_000
# Images larger than this aren't worth decoding just to shrink them
MAX_IMAGE_INPUT_BYTES: int = 25_000_000

# Every attachment sits inside <file name="..."> ... </file> in the user's message, which tells the model the real
# file name and lets a saved conversation be shown again with its attachments as attachments
FILE_OPEN: re.Pattern[str] = re.compile(r'\A<file name="([^"\n]*)">')
FILE_CLOSE: str = "</file>"
# Bedrock needs text beside a document, so files sent without a message get this in its place
NO_TEXT: str = "(The user sent these files without a message.)"

# Pillow's name for each format Bedrock takes; anything else Pillow can open (BMP, TIFF, ...) is converted
_BEDROCK_IMAGE_FORMATS: dict[str, str] = {"PNG": "png", "JPEG": "jpeg", "MPO": "jpeg", "GIF": "gif", "WEBP": "webp"}
IMAGE_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"})
# Binary documents go to the model as document blocks. Text-like files (txt, md, csv, html, code) go as text
# instead: that skips the 5-document cap and covers formats Bedrock has no document type for
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({"pdf", "doc", "docx", "xls", "xlsx"})



class MediaError(ValueError):
    """A file the model can't be shown; the message says why and is meant for the user or the model"""



@dataclass(frozen = True)
class Attachment:
    """A file the user attached to a message"""
    name: str
    data: bytes


    @classmethod
    def from_path(cls, path: str | Path) -> "Attachment":
        path = Path(path).expanduser()
        try:
            return cls(name = path.name, data = path.read_bytes())
        except OSError as e:
            raise MediaError(f"Could not read {path}: {e.strerror or e}") from None



def _mb(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def extension(name: str) -> str:
    return name.rpartition(".")[2].lower() if "." in name else ""


def file_tag(name: str) -> str:
    """The opening tag that names an attachment; FILE_OPEN reads the name back"""
    name = re.sub(r'["\n]', "'", name)
    return f'<file name="{name}">'


def document_name(name: str) -> str:
    """
    A file name Bedrock accepts for a document: letters, digits, single spaces, hyphens, parentheses and brackets

    The extension stays as a word ("report pdf") since it tells the model what kind of file it is
    """
    name = re.sub(r"[^a-zA-Z0-9\s\-()\[\]]", " ", name)
    return re.sub(r"\s+", " ", name).strip() or "document"



def image_block(data: bytes, name: str = "image") -> ContentBlock:
    """
    An image content block within Bedrock's limits, shrunk and re-encoded only when it has to be

    Args:
        data: {bytes} Image in any format Pillow reads
        name: {str} Used in error messages

    Returns:
        block: {ContentBlock}
    """
    if len(data) > MAX_IMAGE_INPUT_BYTES:
        raise MediaError(f"{name} is {_mb(len(data))}; images up to {_mb(MAX_IMAGE_INPUT_BYTES)} can be shown")
    try:
        image = Image.open(io.BytesIO(data))
        image_format = _BEDROCK_IMAGE_FORMATS.get(image.format or "")
        if image_format and len(data) <= MAX_IMAGE_BYTES and max(image.size) <= MAX_IMAGE_EDGE_PX:
            return {"image": {"format": image_format, "source": {"bytes": data}}}
        return _shrink(image)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise MediaError(f"{name} isn't an image the model can read ({type(e).__name__})") from None


def _shrink(image: Image.Image) -> ContentBlock:
    # Thumbnail first: it decodes large JPEGs at reduced size, which is far faster than loading them whole
    image.thumbnail((MAX_IMAGE_EDGE_PX, MAX_IMAGE_EDGE_PX))
    # Phone photos store their rotation as metadata, which re-encoding drops unless it's applied to the pixels
    image = ImageOps.exif_transpose(image)
    keep_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info

    # Noisy images can still be too big at the edge cap, so step the size down until one fits
    while True:
        buffer = io.BytesIO()
        if keep_alpha:
            image.convert("RGBA").save(buffer, "PNG", optimize = True)
        else:
            image.convert("RGB").save(buffer, "JPEG", quality = 85)
        if buffer.tell() <= MAX_IMAGE_BYTES or min(image.size) < 64:
            break
        image = image.resize((image.width * 3 // 4, image.height * 3 // 4), Image.Resampling.LANCZOS)

    return {"image": {"format": "png" if keep_alpha else "jpeg", "source": {"bytes": buffer.getvalue()}}}


def document_block(data: bytes, document_format: str, name: str) -> ContentBlock:
    """
    A document content block, refused when Bedrock would reject its size

    Args:
        data: {bytes}
        document_format: {str} One of Bedrock's document formats, e.g. "pdf" or "docx"
        name: {str} File name; it is cleaned up to what Bedrock allows

    Returns:
        block: {ContentBlock}
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise MediaError(f"{name} is {_mb(len(data))}; documents up to {_mb(MAX_DOCUMENT_BYTES)} can be shown")
    return {"document": {"format": document_format, "name": document_name(name), "source": {"bytes": data}}}


def text_block(data: bytes, name: str) -> ContentBlock:
    """The file as a text block wrapped in its name, cut at MAX_TEXT_CHARS with a note saying so"""
    # A NUL byte early on means a binary file that happens to be valid UTF-8
    if b"\x00" in data[:8_192]:
        raise MediaError(f"{name} isn't a format the model can read")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise MediaError(f"{name} isn't a format the model can read") from None

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n[truncated: showing the first {MAX_TEXT_CHARS:,} of {len(text):,} characters]"
    return {"text": f"{file_tag(name)}\n{text}\n{FILE_CLOSE}"}


def file_block(name: str, data: bytes) -> ContentBlock:
    """
    The content block that shows the model one file, picked by its extension

    Images become image blocks, PDF and Office files document blocks, and anything else that is text a text block

    Raises:
        MediaError: The file is in a format the model can't read, or too large to send
    """
    kind = extension(name)
    if kind in IMAGE_EXTENSIONS:
        return image_block(data, name)
    if kind in DOCUMENT_EXTENSIONS:
        return document_block(data, kind, name)
    return text_block(data, name)


def prompt_content(text: str, attachments: list[Attachment]) -> str | list[ContentBlock]:
    """
    What to send the agent for a message: the text alone, or the attachments followed by the text

    Raises:
        MediaError: Listing every attachment that can't be sent, so the user can fix them all at once
    """
    if not attachments:
        return text

    blocks: list[ContentBlock] = []
    problems: list[str] = []
    for attachment in attachments:
        try:
            block = file_block(attachment.name, attachment.data)
        except MediaError as e:
            problems.append(str(e))
            continue
        # Text files carry their own tags; images and documents get theirs as text blocks around them
        if "text" in block:
            blocks.append(block)
        else:
            blocks += [{"text": file_tag(attachment.name)}, block, {"text": FILE_CLOSE}]

    images = sum("image" in block for block in blocks)
    documents = [block["document"] for block in blocks if "document" in block]
    if images > MAX_IMAGES_PER_MESSAGE:
        problems.append(f"{images} images attached; up to {MAX_IMAGES_PER_MESSAGE} fit in one message")
    if len(documents) > MAX_DOCUMENTS_PER_MESSAGE:
        problems.append(
            f"{len(documents)} PDF or Office files attached; up to {MAX_DOCUMENTS_PER_MESSAGE} fit in one message"
        )
    if problems:
        raise MediaError("; ".join(problems))

    # Documents sharing a name in one message get mixed up by the model, so repeats are numbered
    seen: dict[str, int] = {}
    for document in documents:
        seen[document["name"]] = count = seen.get(document["name"], 0) + 1
        if count > 1:
            document["name"] = f"{document['name']} ({count})"

    # Files go before the question, which is where Claude reads them best; Bedrock also needs a text block
    # beside any document
    return [*blocks, {"text": text.strip() or NO_TEXT}]


def thumbnail(data: bytes, edge: int = 240) -> str | None:
    """A small JPEG data URL of an image, for showing it again in a reopened conversation"""
    try:
        image = Image.open(io.BytesIO(data))
        image.thumbnail((edge, edge))
        buffer = io.BytesIO()
        ImageOps.exif_transpose(image).convert("RGB").save(buffer, "JPEG", quality = 70)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def split_attachments(content: list[ContentBlock]) -> tuple[list[dict[str, str]], list[ContentBlock]]:
    """
    Separate the files attached to a saved user message from the rest of it

    Returns:
        (attachments, rest): {tuple[list[dict], list[ContentBlock]]} Each attachment is {"name", "kind"} with kind
            "image", "document" or "text", plus a "preview" data URL for images
    """
    attachments: list[dict[str, str]] = []
    rest: list[ContentBlock] = []
    index = 0
    while index < len(content):
        block = content[index]
        text = block.get("text", "")
        match = FILE_OPEN.match(text)
        if not match:
            if not (attachments and text == NO_TEXT):
                rest.append(block)
        elif match.end() < len(text):
            # A text file: tags and contents in one block
            attachments.append({"name": match.group(1), "kind": "text"})
        else:
            # An image or document between an opening and a closing tag block
            media = content[index + 1] if index + 1 < len(content) else {}
            attachment = {"name": match.group(1), "kind": "image" if "image" in media else "document"}
            # Saved sessions keep bytes base64-encoded, so a chat read back from disk needs them decoded first
            data = decode_bytes_values(media.get("image", {}).get("source", {}).get("bytes"))
            if isinstance(data, bytes) and (preview := thumbnail(data)):
                attachment["preview"] = preview
            attachments.append(attachment)
            index += 2
        index += 1
    return attachments, rest
