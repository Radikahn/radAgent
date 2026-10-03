import { useEffect, useRef, useState, type ClipboardEvent } from "react";
import { MAX_FILES, release, toPending, type PendingFile } from "./files";

/** Files waiting to go with the next message: picked, pasted, or dropped anywhere on the window */
export function useAttachments() {
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [problem, setProblem] = useState<string>();
  const [dragging, setDragging] = useState(false);

  function add(picked: File[]) {
    const problems: string[] = [];
    const ready: PendingFile[] = [];
    for (const file of picked) {
      const pending = toPending(file);
      if (typeof pending === "string") problems.push(pending);
      else ready.push(pending);
    }
    const room = Math.max(MAX_FILES - files.length, 0);
    if (ready.length > room) {
      ready.splice(room).forEach(release);
      problems.push(`Up to ${MAX_FILES} files fit in one message`);
    }
    setFiles([...files, ...ready]);
    setProblem(problems.join("; ") || undefined);
  }

  function remove(index: number) {
    release(files[index]);
    setFiles(files.filter((_, at) => at !== index));
    setProblem(undefined);
  }

  /** Hands the files over for sending; their previews live on in the thread, so they aren't released */
  function take(): PendingFile[] {
    setFiles([]);
    setProblem(undefined);
    return files;
  }

  function onPaste(event: ClipboardEvent) {
    const pasted = Array.from(event.clipboardData.files);
    if (!pasted.length) return;
    event.preventDefault();
    add(pasted);
  }

  // The window listeners outlive renders, so they reach the latest `add` through a ref
  const addLatest = useRef(add);
  addLatest.current = add;

  useEffect(() => {
    let settle: number | undefined;
    const carriesFiles = (event: DragEvent) => event.dataTransfer?.types.includes("Files") ?? false;

    const onDragOver = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      // Accepting dragover is what makes the window a drop target
      event.preventDefault();
      setDragging(true);
      // dragover repeats while a file is over the window, so once it goes quiet the drag has left or ended
      window.clearTimeout(settle);
      settle = window.setTimeout(() => setDragging(false), 150);
    };
    const onDrop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      // Otherwise the webview navigates away to show the file
      event.preventDefault();
      window.clearTimeout(settle);
      setDragging(false);
      addLatest.current(Array.from(event.dataTransfer?.files ?? []));
    };

    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
      window.clearTimeout(settle);
    };
  }, []);

  return { files, problem, dragging, add, remove, take, onPaste };
}
