"use client";

import { useEffect } from "react";

/**
 * Stop the browser opening/downloading a file dropped outside a real dropzone.
 *
 * With no document-level handler, dropping a file anywhere on the page is a
 * navigation -- the browser replaces the app with the file. Dropzones that
 * call preventDefault() themselves are unaffected: their handler runs first
 * and this only catches what reaches the document.
 */
export function useBlockStrayFileDrops(): void {
  useEffect(() => {
    const isFileDrag = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");

    // dragover must also be prevented, or the drop event never fires and the
    // browser navigates anyway.
    const onDragOver = (e: DragEvent) => {
      if (isFileDrag(e)) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (isFileDrag(e)) e.preventDefault();
    };

    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, []);
}
