import { extension, type Attachment } from "./files";
import "./attachments.css";

type Props = {
  files: (Attachment & { id?: string })[];
  /** Gives each file a remove button; the composer passes it, the thread doesn't */
  onRemove?: (index: number) => void;
  className?: string;
};

/** Attached files: images as thumbnails, everything else as a chip with its type and name */
export function Attachments({ files, onRemove, className }: Props) {
  return (
    <ul className={`attachments ${className ?? ""}`}>
      {files.map((file, index) => (
        <li key={file.id ?? index} className={`attachment materialize ${file.preview ? "thumbnail" : ""}`} title={file.name}>
          {file.preview ? (
            <img src={file.preview} alt={file.name} />
          ) : (
            <>
              <span className="attachment-type">{extension(file.name).slice(0, 4).toUpperCase() || "FILE"}</span>
              <span className="attachment-name">{file.name}</span>
            </>
          )}
          {onRemove && (
            <button
              type="button"
              className="attachment-remove"
              aria-label={`Remove ${file.name}`}
              onClick={() => onRemove(index)}
              // Keep focus in the input so typing carries on
              onMouseDown={(event) => event.preventDefault()}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
              </svg>
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
