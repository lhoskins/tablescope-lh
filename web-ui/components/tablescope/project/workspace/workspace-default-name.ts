import type { Workspace } from "@/lib/api/workspaces";

/**
 * The next free `Untitled-NN` name for a new workspace.
 *
 * Numbering by list length (the previous approach) collides after a delete --
 * remove #2 of 3, create one, and you have two "Workspace 3"s -- so take the
 * highest N actually in use and step past it. Names that aren't `Untitled-NN`
 * (anything the user renamed) are ignored, which is what keeps a project full
 * of hand-named workspaces from starting over at 01.
 */
export function nextUntitledName(existing: Pick<Workspace, "name">[]): string {
  let highest = 0;
  for (const w of existing) {
    const match = /^Untitled-(\d+)$/.exec(w.name.trim());
    if (match) highest = Math.max(highest, Number(match[1]));
  }
  return `Untitled-${String(highest + 1).padStart(2, "0")}`;
}
