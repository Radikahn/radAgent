/** A file sent with a message, as the thread shows it; the bytes themselves go straight to the agent */
export type Attachment = {
  name: string;
  /** How the model gets it: an image it looks at, a PDF or Office document, or plain text (notes, code, CSV) */
  kind: "image" | "document" | "text";
  /** Shown in place of the name: an object URL for a new image, a data URL for one from a reopened chat */
  preview?: string;
};

/** A file picked in the composer and not sent yet */
export type PendingFile = Attachment & { id: string; file: File };

// The agent checks every limit exactly and shrinks images to fit (agent/src/radagent/media/files.py); these only
// turn away files that could never be sent, before reading them into memory
export const MAX_FILE_BYTES = 25_000_000;
export const MAX_FILES = 20;

// Same routing as the agent's media.file_block: by extension, with anything else read as text
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"]);
const DOCUMENT_EXTENSIONS = new Set(["pdf", "doc", "docx", "xls", "xlsx"]);

export function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function kindOf(name: string): Attachment["kind"] {
  const ext = extension(name);
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  if (DOCUMENT_EXTENSIONS.has(ext)) return "document";
  return "text";
}

/** A picked file ready to attach, or why it can't be */
export function toPending(file: File): PendingFile | string {
  if (file.size > MAX_FILE_BYTES) return `${file.name} is over ${MAX_FILE_BYTES / 1_000_000} MB`;
  const kind = kindOf(file.name);
  const preview = kind === "image" ? URL.createObjectURL(file) : undefined;
  return { id: crypto.randomUUID(), file, name: file.name, kind, preview };
}

/** Frees the preview of a file that was removed rather than sent */
export function release(file: PendingFile) {
  if (file.preview) URL.revokeObjectURL(file.preview);
}

/** The file's bytes as base64, which is how the prompt command carries them to the agent */
export function encode(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = reader.result as string;
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}
