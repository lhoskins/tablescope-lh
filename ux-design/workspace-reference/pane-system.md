# Pane system

Source of truth: `web-ui/components/tablescope/project/workspace/workspace-pane-storage.ts` (state shape and persistence), `use-pane-layout.ts` (the hook implementing every interaction), `workspace-panes.tsx` (the rendering/DOM layer).

This is a generic five-pane layout engine — nothing in it is specific to what a pane contains. `workspace-screen.tsx` supplies five `PaneSpec`s (`id`, `title`, `body`, optional `info`/`chat`/`actions`); everything below is what the engine does with them regardless of content.

## The five pane ids

```ts
type PaneId = "files" | "preview" | "chat" | "notes" | "actions";
```

`"files"` is the Documents pane's internal id (named for what a `WorkspaceCard` points at, not the on-screen label — every id is titled independently, see `paneTitles` in `workspace-screen.tsx`).

## Persisted layout shape

One `PaneLayout` object per project, in `localStorage` under `tablescope:workspace-panes:{projectId}`:

```ts
interface PaneLayout {
  order: PaneId[];                       // left-to-right
  widths: Partial<Record<PaneId, number>>;    // dragged widths in px; absent = use the default ratio
  hidden: PaneId[];                      // switched off in the Pane Views bar -- not rendered at all
  columns: number;                       // the 2/3/4 split preset -- a viewport concern, independent of `hidden`
  collapsed: PaneId[];                   // strip-only, still in the row, reopenable
  maximized: PaneId | null;
  drawers: Partial<Record<PaneId, "info" | "chat">>;
  drawerHeights: Partial<Record<PaneId, number>>;
}
```

**Defaults** (`workspace-pane-storage.ts`): `order` is `files, preview, chat, notes, actions`; `hidden` is `["chat", "actions"]`; `columns` is `3`. A fresh workspace therefore opens on the reading path — Documents, Preview, Notes, three-up — with Chat and Actions one click away in the Pane Views bar rather than crowding a laptop-width screen. `PANE_DEFAULT_RATIO` gives each pane's natural flex weight when nothing has been dragged (`preview: 1.5` is the widest by default, `notes`/`actions: 0.9` the narrowest).

`normalizeOrder` (in `workspace-pane-storage.ts`) backfills any pane id a stored layout predates, so a pane added after a user's layout was saved appears rather than staying permanently hidden.

## Interactions, one by one

- **Resize (drag a divider).** `startColumnResize` mutates `style.flexBasis` directly on the DOM inside one `requestAnimationFrame` per pointer-move frame, and commits to React state exactly once, on release — driving it through state on every move visibly lagged the cursor in an earlier version. Sizing is delta-based (`startWidth + (clientX - startX)`), not absolute, because the handle sits in a negative margin and an absolute reading disagreed with the pane's real width.
- **Collapse / expand.** `toggleCollapsed` leaves a 36px clickable strip in the row (`COLLAPSED_PANE_WIDTH`) labelled with the pane's initial; the pane keeps its place in the order. Collapsing drops any dragged width for that gesture (`widths: {}`) so the ratio-driven layout can retake the freed space.
- **Maximize.** `toggleMaximized` gives one pane `flexGrow: 1` and sets every sibling's style to `display: none` outright (not just collapsed) — there's only one pane on screen, so `isDividerDisabled` returns `true` for everything while maximized.
- **Split (columns).** `setColumns(n)` is a **viewport** concern, deliberately independent of `hidden`: splitting three-up with five panes loaded means three on screen and two a scroll away, never panes switched off. `paneStyle` computes each visible pane's `flexBasis` as `calc((100% - reserved) / columns)` when the visible+expanded count exceeds `columns`, reserving space for any collapsed strips (`36px + gap` each) so they aren't counted into the division.
- **Hide / show (Pane Views bar).** `togglePaneVisible` removes a pane from `order`'s visible subset entirely — distinct from collapse, which keeps a strip. Refuses to hide the last visible pane (an empty workspace has no way back except the bar itself). Re-showing a previously-hidden pane clears any collapse it had, so it can't reappear as a strip requiring a second click.
- **Reorder (drag-and-drop).** `reorder(from, to)` splices `from` out of `order` and re-inserts it at `to`'s index, pushing the rest right. Disabled entirely while any pane is maximized (`reorderDisabled`).
- **Drawers.** Each pane has at most one open drawer at a time, in one of two modes: `"info"` (the selected item's metadata) or `"chat"` (an in-pane conversation scoped to that pane — see `scoping-and-memory.md` for what "scoped" means here). `toggleDrawer(pane, mode)` swaps modes rather than stacking them; clicking the same mode again closes it. `startDrawerResize` drags the divider between a pane's body and its open drawer with the same rAF-batched, delta-based mechanics as column resize, bounded by `MIN_DRAWER_HEIGHT` (120px) below and `pane height - MIN_PANE_BODY_HEIGHT` above so a drawer can never fully swallow the pane's own content.
- **Scroll.** When more panes are visible than `columns` allows, `scrollByPane(direction)` steps the row exactly one split-width sideways (`clientWidth / columns + gap`), backing the `<`/`>` controls next to the split presets. Both ends grey out via a `ResizeObserver` + scroll-position check rather than sitting permanently active.

## Rendering notes worth knowing

- Every pane element carries `data-pane="{id}"` and every open drawer carries `data-pane-drawer="{mode}"` — both are read by other parts of the system rather than being pure styling hooks: `use-selection-capture.ts` walks up to `[data-pane]` to label a selection's source, and `[data-pane-drawer]` distinguishes "selected in the pane" from "selected inside its drawer chat."
- A drag mutates the DOM directly and commits to state once on release (see Resize above) — this is the single most important performance property of the whole system, ported deliberately from an earlier prototype (`YouTube Chat app's modules/resize.js`) after a state-driven version visibly lagged.
- `PaneSpec.actions` (from `workspace-screen.tsx`) renders directly in a pane's header, before its info/chat/maximize/collapse icon buttons — this is where the Pinned Context toggle (see `pinned-context-and-selection.md`) and Documents' **+ Add card** button live.

## Testing

`use-pane-layout.test.tsx` and `workspace-panes.test.tsx` cover this file's every claim above as executable assertions — collapsing, maximizing, splitting, hiding, reordering, and the default pane set — and are the fastest way to confirm a change to this system hasn't broken an existing guarantee. Both suites were updated in this session alongside the default-pane-set change described in `README.md`; run `npx vitest run components/tablescope/project/workspace/` from `web-ui/` to exercise them (also runs `workspace-tab-bar.test.tsx`, `workspace-drag.test.ts`, etc. in the same pass).
