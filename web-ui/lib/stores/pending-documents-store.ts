import { create } from "zustand";

/**
 * Documents dropped before a project has been chosen.
 *
 * Data sources can be staged project-less -- `analyzeFile` omits project_id and
 * both FileSourceMeta.project_id and DatabaseDataSource.project_id are nullable
 * -- but a document's upload route is `/projects/{id}/assets/upload` with the
 * id in the path, so there is nowhere to put one until a project exists. From
 * Home that is the normal case, not an edge case: the user has files in hand
 * and picks a project afterwards.
 *
 * So the File is held here and uploaded once a project is settled, whether by
 * "Start Project" or "Add to Existing Project".
 *
 * Deliberately NOT persisted, and not part of the builder store: a File cannot
 * survive JSON serialisation, so a reload would restore a name with no bytes
 * behind it -- worse than losing it honestly. `hydrated` marks that a reload
 * happened so the UI can say the documents need re-adding.
 */
export interface PendingDocument {
  id: string;
  file: File;
  fileName: string;
  sizeBytes: number;
}

interface PendingDocumentsState {
  documents: PendingDocument[];
  add(file: File): PendingDocument | null;
  remove(id: string): void;
  clear(): void;
}

export const usePendingDocumentsStore = create<PendingDocumentsState>(
  (set, get) => ({
    documents: [],

    add: (file) => {
      // Same-name guard as the builder store's structured path, so a double
      // drop doesn't queue the same document twice.
      if (get().documents.some((d) => d.fileName === file.name)) return null;
      const doc: PendingDocument = {
        id: `doc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        fileName: file.name,
        sizeBytes: file.size,
      };
      set((state) => ({ documents: [...state.documents, doc] }));
      return doc;
    },

    remove: (id) =>
      set((state) => ({
        documents: state.documents.filter((d) => d.id !== id),
      })),

    clear: () => set({ documents: [] }),
  }),
);
