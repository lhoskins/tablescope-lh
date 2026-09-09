# Workspace — Reference for Implementers

This folder documents the **Workspace** feature as it actually exists in the codebase today (branch `UX-design-04`), not as originally planned. It supersedes `docs/workspace-feature-spec.md` for anything the two disagree on — that spec described the feature before it was built, and this folder describes it after. Read `docs/ux-workspace-redesign-gap-analysis.md` separately for the rest of the project shell (sidebar, nav grid, Data Sources header); this folder is scoped to the Workspace page only.

Five files, each a different layer of the same feature:

- **This file** — what a Workspace is, the mental model, and the user-facing workflows end to end.
- [`data-model-and-api.md`](./data-model-and-api.md) — the `workspaces`/`workspace_cards` backend tables, the REST endpoints, ownership and sharing rules.
- [`pane-system.md`](./pane-system.md) — the five panes, and the generic resize/collapse/maximize/split/reorder/drawer mechanics that host them.
- [`scoping-and-memory.md`](./scoping-and-memory.md) — how a question typed into any chat surface gets grounded: the canonical conversation thread, active resources vs. focus, pinned context, and the project-reach fallback.
- [`pinned-context-and-selection.md`](./pinned-context-and-selection.md) — selecting text anywhere in the workspace, pinning it to Chat or Notes, and how Actions turns a description into a checklist.
- [`navigation.md`](./navigation.md) — where the Workspace page sits in the app: the top nav grid, the left sidebar, and the Data Source Builder entry points.

## What a Workspace is

A **workspace** is a named, user-created canvas that pins together an arbitrary number of tables, dashboards, documents, and data sources — the four resource types the rest of the app already models. A project can hold several workspaces at once, shown as browser-style tabs across the top of the page (`Cost review`, `Vendor spend`, `Workspace 3`, …). Each is:

- **Private by default**, visible only to its creator.
- **Publishable** by its owner to the rest of the project (`shared_project` visibility), and just as reversibly un-publishable back to private.
- **Owned**, in the sense that only the owner can rename it, add or remove cards, publish/un-publish it, or delete it — publishing makes a workspace *visible* to teammates, it does not open it to *editing* by them. See `data-model-and-api.md` for exactly how that's enforced.

This is deliberately not a knowledge graph or a relationship model — a workspace is a scope list (which items am I looking at right now), nothing more. The Knowledge Graph is a separate, existing, project-wide feature.

## The five panes

Every workspace, whatever cards it holds, is worked in through the same five panes. `pane-system.md` covers the mechanics (resize, collapse, split, drawers); this is what each one is *for*:

| Pane | Purpose |
|---|---|
| **Documents** | The workspace's pinned cards themselves — the canvas. Drag a table, document, dashboard or data source in from the sidebar, or use **+ Add card**; each renders as a Card/Row/Full-width tile you can retoggle. This is also the page's drop target. |
| **Preview** | Whichever card is selected in Documents, shown in full using the same view the rest of the app already has for that resource type — a table here is the same result grid as the Tables screen, not a reimplementation. |
| **Chat** | The one surface that resumes the workspace's whole conversation history. Grounded on every card currently pinned to the workspace, with the card in Preview named as the user's current focus. Carries the Pinned Context panel — see below. |
| **Notes** | Passages you've pinned for later — the same Pinned Context list as Chat, but scoped to `"notes"` rather than `"chat"`, so you can keep a running set of excerpts separate from what's actively quoted into the conversation. |
| **Actions** | A scratchpad of draft to-dos, either typed directly or suggested by the assistant from a one-line description of what you're trying to do (grounded the same way Chat is). Nothing here reaches the project's real action board until promoted — it's deliberately disposable. |

A fresh workspace opens showing **Documents, Preview, Notes** at three columns — Chat and Actions are one click away in the Pane Views bar (`▤ PANES` in the tab strip) rather than crowding a laptop-width screen by default. Every pane, drawer, chat, and drop target described above also exists inside the **Documents** and **Preview** panes' own info/chat drawers — see `pane-system.md` for how a drawer differs from the main Chat pane.

## The scoping hierarchy: Panes → Workspace → Project

This is the part most worth understanding before touching the code, because it's easy to build a version that either leaks everything into every prompt or walls off panes from each other so aggressively that a reasonable question can't be answered. The actual design threads that needle with four distinct mechanisms, each doing one job:

1. **Full visibility, narrowed default focus.** Every chat surface can see every card pinned to the workspace — there's no per-pane blindfold. What differs is which of those is named as the *focus* (see `scoping-and-memory.md`'s active-resource/focus split): the card open in Preview. A question like "what should I fix first?" defaults to being about the item in front of you, not treated as ambiguous across five peers.
2. **One shared memory, many surfaces.** The Chat pane and every pane's chat drawer all write to and read from the *same* canonical conversation thread — one per `(project, "project_workspace")` pair, resolved server-side. A drawer doesn't have its own separate memory; it shows only what was asked in it, but the shared thread already has everything. This is why the drawer's ↗ button works: it lifts that exchange into the Chat pane, where it was already sitting.
3. **Pinned context, layered on top.** Selecting a passage anywhere and sending it to Chat or Notes is the user explicitly saying "this specific text matters across the conversation" — distinct from *which cards are open*. It's quoted verbatim into every subsequent prompt on that surface, on top of whatever cards are grounding the turn.
4. **Project reach, for when the question isn't about what's open.** If none of the pinned/focused cards' terms overlap with the question, a cheap term-overlap search surfaces at most two other resources from the *rest of the project* — described as background, never as the primary subject. This is intentionally invisible: no toggle, no button. It lives entirely in prompt construction, so it can never change how the turn is routed (see `scoping-and-memory.md` for why that ordering is load-bearing).

`scoping-and-memory.md` has the exact backend call sequence and prompt text for all four.

## Typical workflows

**Starting a workspace.** From the Workspace page, `+ New Workspace` creates a private, empty workspace named `Workspace N` and switches to it. Drag resources in from the sidebar's asset tree, or use Documents' **+ Add card**. Nothing is visible to teammates until you publish it.

**Investigating something.** Open the item you're looking at in Preview (it becomes the chat's *focus*, not just one more open card), ask questions in Chat, and pin the passages that matter — the ones you'd otherwise have to re-explain in a follow-up — to Notes or back into Chat as you go. If you realize a table outside the workspace is actually relevant, either drag it in (making it a real pinned card) or just ask about it directly — project reach will likely surface it on its own if your wording overlaps.

**Turning findings into next steps.** In Actions, either type what you already know needs doing, or describe the situation in a couple of sentences and ask the assistant to suggest actions — it replies as a list, which gets parsed into individually checkable, deletable drafts tagged `AI`. This stays a personal scratchpad; promoting a draft into the project's real action board is a separate, not-yet-described step.

**Sharing it.** Publish turns the workspace visible (read-only) to the rest of the project. Every other project member sees your card set, your workspace's name, and can open it — but only you can still edit it, rename it, or take it back to private.

## Implementation status note

Everything described in this folder is implemented and merged into `UX-design-04` as of this session (2026-09-08) — this is documentation of working code, not a proposal. Where the old `docs/workspace-feature-spec.md`'s "Open questions" (§6) are now resolved by the actual build, `data-model-and-api.md` says so explicitly with a pointer to the code that settles it.
