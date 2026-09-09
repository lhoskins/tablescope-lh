# Data model and API

Source of truth: `platform-api/app/models/workspace.py`, `platform-api/app/routes/workspaces.py`, `web-ui/lib/api/workspaces.ts`.

## Tables

Two tables, following the existing `project_asset` pattern (`visibility` + `owner_user_id`) rather than inventing new sharing semantics.

```
workspaces
  id                  PK
  tenant_id           FK -> tenants.id
  project_id          FK -> projects.id
  owner_user_id       FK -> users.id, nullable (SET NULL on user deletion)
  name                text
  visibility          "private" | "shared_project"   (default "private")
  published_at        timestamp, nullable  -- set on publish, cleared on unpublish
  created_at / updated_at   (TimestampMixin)

workspace_cards
  id                  PK
  workspace_id        FK -> workspaces.id (CASCADE)
  resource_type       "table" | "dashboard" | "document" | "data_source"
  resource_id         string -- kept as a string to match the frontend's
                         WorkspaceTab.id shape; grounding converts it to a
                         numeric id per resource type before resolving it
  view_mode           "card" | "row" | "full"   (default "card")
  position            integer -- ordering within the canvas
  added_at            timestamp
```

Two tables rather than a JSON blob on `workspaces`: ordering, adding, and removing individual cards is then a normal row operation rather than a read-modify-write race on a blob column, mirroring how `project_asset` rows are first-class rather than embedded JSON.

Migration: `platform-api/alembic/versions/0086_workspaces.py`.

## REST endpoints

Router: `platform-api/app/routes/workspaces.py`, prefixed `/api/projects/{project_id}/workspaces`. Access-check shape matches `project_assets.py`: `shared_project` readable by any project member, `private` readable only by `owner_user_id`.

| Method & path | Behavior |
|---|---|
| `POST /projects/{id}/workspaces` | Create. Body `{name, cards?: [{resource_type, resource_id}]}`. `visibility` always starts `"private"`; `owner_user_id` = caller. |
| `GET /projects/{id}/workspaces` | List workspaces visible to the caller: their own private ones plus every `shared_project` one for the project. This is the query behind the workspace tab strip. |
| `GET /projects/{id}/workspaces/{workspace_id}` | Detail, with each card's metadata resolved (name/title, matching how a `WorkspaceTab` label already resolves). |
| `PATCH /projects/{id}/workspaces/{workspace_id}` | Rename, and/or a **full replacement** of the card list — the frontend always sends the complete desired `cards` array (adds, removals, reorders, and `view_mode` changes all expressed as one new list), not incremental diffs. Owner-only. |
| `POST /projects/{id}/workspaces/{workspace_id}/publish` | Sets `visibility = "shared_project"`, `published_at = now()`. Owner-only. |
| `POST /projects/{id}/workspaces/{workspace_id}/unpublish` | Sets `visibility = "private"`, `published_at = null`. Owner-only. |
| `DELETE /projects/{id}/workspaces/{workspace_id}` | Owner-only. |

Frontend client: `web-ui/lib/api/workspaces.ts` (`listWorkspaces`, `getWorkspace`, `createWorkspace`, `updateWorkspace`, `publishWorkspace`, `unpublishWorkspace`, `deleteWorkspace`), typed as `Workspace` / `WorkspaceCard`.

## Open questions from the original spec — now resolved

`docs/workspace-feature-spec.md` §6 left three things unsettled before building. All three are now settled by the actual implementation:

1. **Does the named-workspace tab bar replace the old MRU `WorkspaceTabsBar`, or do they coexist?**
   Resolved: on the Workspace page, `WorkspaceScreen` renders `<ProjectShell showResourceTabs={false} showAssistant={false} ...>` — the old single-resource MRU strip and the docked AI Assistant rail are both switched off for this page. `WorkspaceTabBar` (the named-workspace strip) is the only tab strip shown here; `WorkspaceTabsBar` (`workspace-tabs-bar.tsx`, `workspace-tabs-storage.ts`) is still what every *other* project page uses. They coexist as separate things on separate pages, not stacked on the same one.

2. **Card-edit permissions on a `shared_project` (published) workspace: owner-only, or any project member?**
   Resolved: owner-only, full stop, whether or not the workspace is published. `WorkspaceScreen` passes `editable={isOwner}` to the Documents pane and gates **+ Add card** on `active && isOwner`; `WorkspaceTabBar`'s per-tab rename/publish/unpublish/delete menu is gated on `canManage = currentUserId != null && workspace.owner_user_id === currentUserId`. Publishing shares *visibility*, not *edit access* — a teammate can open and read a published workspace but cannot rename it, change its cards, or take any management action on it.

3. **AI panel default state on the Workspace page: collapsed like elsewhere, or open by default?**
   Resolved by superseding the question: the docked AI Assistant rail doesn't apply to this page at all (`showAssistant={false}`). It's replaced entirely by the in-pane **Chat** pane, which is one of the five default panes and needs no separate open/collapsed state of its own.

## Grounding contract (how a card becomes something the assistant can talk about)

Not part of the `workspaces` CRUD API itself, but the reason this data model exists at all: every card's `{resource_type, resource_id}` is what a chat turn sends as grounding. See `scoping-and-memory.md` for the full path from a card to a prompt — the short version is that `resource_id` only resolves server-side when it's numeric, so a card whose id doesn't parse as a number is silently excluded from grounding (still visible and editable in the canvas, just not sent to the assistant).
