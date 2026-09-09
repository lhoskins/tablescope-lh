# Pinned context and selection

Source of truth: `use-selection-capture.ts`, `selection-toolbar.tsx`, `workspace-snippet-list.tsx`, `workspace-snippet-storage.ts`, `workspace-actions-pane.tsx`.

## Selecting text anywhere in the workspace

`useSelectionCapture` watches for a text selection anywhere inside the pane row (`document.addEventListener("pointerup"/"keyup", ...)`, not `selectionchange`, which fires continuously mid-drag and would make a toolbar chase the cursor). When a selection settles:

1. It walks up from the selection's range to the nearest `[data-pane]` ancestor to identify which pane it came from, and further checks for a `[data-pane-drawer]` ancestor to distinguish "selected in the pane's own body" from "selected inside that pane's chat drawer" — the label differs accordingly ("Preview" vs. "Preview chat").
2. Selections outside the pane row entirely (the tab strip, the sidebar, anything that isn't workspace content) are ignored.
3. `SelectionToolbar` renders at the selection's coordinates offering **Copy**, **→ Chat**, and **→ Notes**. It's rendered at the screen level (`workspace-screen.tsx`), not inside a pane, specifically so it isn't clipped by a pane's own overflow when the selection sits near an edge.
4. Escape, or any scroll/resize (which invalidates the stored coordinates), clears the toolbar.

## Pinning: `WorkspaceSnippet` and its two targets

A pin becomes a `WorkspaceSnippet { id, projectId, workspaceId, label, text, image?, createdAt }`, appended to one of two independent lists — `"chat"` or `"notes"` (`SnippetTarget`) — each persisted separately in `localStorage` under `tablescope-workspace-{target}-snippets-{projectId}-{workspaceId}`. Sending to Chat also reveals the Chat pane if it's hidden or collapsed; sending to Notes does the same for Notes. Text is normalized (`normalizeSnippetText`: collapsed whitespace, trimmed, capped at `SNIPPET_MAX_CHARS = 2000`) before storage — this cap matches the backend's own per-snippet ceiling (`ContextSnippet.text`), so nothing pinned client-side can silently exceed what the backend will actually use.

`WorkspaceSnippetList` (used identically by both Chat and Notes — one component, not two parallel implementations) renders the pinned list: passages longer than `SNIPPET_CLAMP_CHARS = 220` clamp to three lines with a **More**/**Less** toggle per snippet; a pasted image renders as a thumbnail rather than being quoted (see `scoping-and-memory.md` — images never reach a prompt). **Clear** empties the whole list for that target.

### Resize handle

The list's height is user-adjustable via a drag handle at its bottom edge — same visual treatment and drag mechanics as the pane info/chat drawer divider described in `pane-system.md` (`role="separator"`, `cursor-row-resize`, a hairline that highlights on hover, rAF-batched drag). Starts at `DEFAULT_PINNED_HEIGHT = 176px`, bounded below by `MIN_PINNED_HEIGHT = 96px` and above by however much room the surrounding column has minus `MIN_REMAINDER = 64px` (so it can never fully push the message transcript/composer, or the rest of the pane, out of view). The chosen height persists per surface — `chat` or `notes` — in `localStorage` under `tablescope-pinned-height-{surface}`, independent of any one project or workspace: it's a layout preference, not workspace data.

### Show/hide toggle

Each pane's header carries a pin-icon button (`IconPinned`/`IconPinnedOff`) that hides the Pinned Context panel entirely without discarding what's pinned or changing what's still sent to the assistant — a pure display preference, local `useState` in `workspace-screen.tsx` (`chatPinnedHidden`/`notesPinnedHidden`), not persisted across a reload.

## Actions: turning a description into a checklist

`WorkspaceActionsPane` is a separate, smaller use of the same `useWorkspaceChat` hook (`resume: false` — it doesn't need history, just one-off grounded replies). Two ways an action gets added:

- **Typed directly**: the input at the bottom, `Enter` or the `+` button appends it as a plain `DraftAction`.
- **Suggested**: typing a one- or two-sentence description of the situation into the textarea and clicking **Suggest actions** sends a question shaped as `"{situation}\n\nBased on the items open in this workspace, what are the most useful next actions? Reply as a short list, one action per line."` — grounded on the workspace's cards exactly the way Chat is (`scoping-and-memory.md`). The reply is parsed by `parseSuggestedActions`: only lines that look like list items (`-`, `*`, `•`, or `1.`/`1)`) survive, their leading marker and any Markdown emphasis/code-span characters are stripped, and results are capped to 10 lines of at most 300 characters each. Suggested actions are tagged `AI` in the UI so it's clear which entries came from the assistant versus were typed.

Each `DraftAction` is checkable and independently deletable, persisted per project+workspace via `workspace-actions-storage.ts` (same `localStorage`-per-workspace pattern as snippets). This list is explicitly a **scratchpad** — nothing in it reaches the project's real action board automatically; promoting a draft into that board is a distinct, not-yet-built step.
