import { createWorkspace, listWorkspaces, type Workspace } from "@/lib/api/workspaces";
import { nextUntitledName } from "./workspace-default-name";

/**
 * List a project's workspaces, opening the project's first one if it has none.
 *
 * A project with zero workspaces is the state every just-created project is in,
 * and an empty tab strip is a dead end -- the user has to find the "+" before
 * the page does anything at all. So bootstrap one.
 *
 * Creating requires EDITOR (`routes/workspaces.py` `require_role`), so a VIEWER
 * opening an empty project falls through to the empty strip rather than being
 * shown a 403 they can do nothing about. A genuine list failure still throws,
 * because that one the caller does need to surface.
 */
export async function loadOrBootstrapWorkspaces(
  projectId: string,
): Promise<Workspace[]> {
  const list = await listWorkspaces(projectId);
  if (list.length > 0) return list;
  try {
    return [await createWorkspace(projectId, { name: nextUntitledName([]) })];
  } catch {
    return [];
  }
}
