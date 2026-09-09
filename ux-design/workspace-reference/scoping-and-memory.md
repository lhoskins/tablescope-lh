# Scoping and memory

How a question typed into the Chat pane, a pane's chat drawer, or Actions' "Suggest actions" ends up as a grounded, routed, answered turn — and how that stays consistent no matter which of those surfaces it came from.

Source of truth: `platform-api/app/services/canonical_conversations.py`, `platform-api/app/services/conversational_analytics/__init__.py` (`execute_turn`), `platform-api/app/services/workspace_context.py`, `web-ui/components/tablescope/project/workspace/use-workspace-chat.ts`.

## One thread per project, not per surface

Every workspace chat surface — the Chat pane, and each pane's own chat drawer — resolves to the **same backend conversation**. This is a server-side fact, not a frontend convention: `canonical_scope_key("project_workspace", project_id)` always returns `project_workspace:{project_id}`, and `_get_or_create_canonical_conversation` finds-or-creates exactly one `AnalyticsConversation` row per `(tenant, user, canonical_key)`. There is no per-workspace or per-pane conversation — switching workspace tabs does not switch threads.

What differs between surfaces is only what they **show** and what they **ground on**, driven by `useWorkspaceChat`'s `resume` flag:

- **Chat pane** (`resume: true`): loads the whole thread on mount via `listConversations` → `getConversation`, so it always shows the full history.
- **A pane's chat drawer** (`resume: false`): starts empty and shows only the turns asked in that drawer session — but every one of those turns is still written to the same shared thread. The drawer's ↗ (`onSendChatToPane`) button lifts that exchange's text into a Chat pane snippet; it isn't recovering something otherwise lost, since the Chat pane already has it the moment you open it.

## Grounding: active resources and focus

Every turn from `useWorkspaceChat` sends two things derived from the workspace's cards, via `submitCanonicalTurn`:

- `active_resources`: **every** card currently in the workspace, as `{resource_type, resource_id}` pairs — filtered to cards whose `resource_id` parses as a number, since only those resolve server-side (`workspace-screen.tsx`'s `groundable` filter).
- `focused_resource`: the one card selected in Preview, if any.

Server-side, `append_canonical_turn` resolves each pair through `resolve_active_resource_contexts` (`workspace_context.py`), which authorizes and describes each resource without ever executing a query — a `table` resource becomes a short prose summary of its name/description/SQL, a `document` becomes its title and AI summary, and so on for `dashboard`/`data_source`. An id that doesn't belong to the calling project resolves to `None` and is silently dropped, never leaking another project's metadata. The resolved focus is looked up as the one member of the resolved set matching `focused_resource`'s type/id — so focus is a *pointer into* the active set, not a separate parallel channel.

`_format_active_resource_prompt` turns this into the prompt block:

```
--- Active workspace items ---
The user currently has these items open in this project workspace:
- a saved table/query named 'X'; described as: ...
- a project document titled 'Y' (pdf), summarized as: ...
Of those, the user is currently looking at Y.
--- End active workspace items ---
```

Two things worth knowing about this block specifically:

1. It's **descriptive, never imperative**. An earlier version added an instruction ("Answer about that item unless the question says otherwise") — and because this block is prepended to the text the intent classifier reads, that instruction changed the detected intent and silently routed turns away from the SQL path. Every prompt block this file describes follows the same rule for the same reason.
2. The assistant is **not restricted** to the active set — this narrows the *default* interpretation of an ambiguous question, it does not wall off anything else. "What's our total spend across the whole project?" is still answerable even with three tables pinned to the workspace.

## Pinned context: quoted, not summarized

Distinct from "which items are open" is "which specific passages did the user judge worth keeping." Selecting text anywhere in the workspace and sending it to Chat (see `pinned-context-and-selection.md`) adds it to that surface's snippet list; every subsequent turn on that surface sends the current list as `context_snippets: [{label, text}]`, formatted by `_format_context_snippets`:

```
--- Pinned excerpts ---
The user kept these passages as context for this conversation:
- Preview · Incident Report: "..."
- Documents chat: "..."
--- End pinned excerpts ---
```

Capped by `_SNIPPET_TOTAL_CHARS = 6000` across the whole block (snippets beyond the cap are simply omitted from that turn, not truncated mid-quote) and, per snippet, by `SNIPPET_MAX_CHARS = 2000` on the frontend at pin time. Only text snippets are sent — a pasted screenshot stays a visual note for the user and is never quoted into a prompt.

## Project reach: the invisible fallback

If a question's terms don't overlap with anything already pinned or focused, `_find_unpinned_project_matches` runs a cheap term-overlap search (reusing `_extract_insight_terms`, the same scoring approach `insight_card_match.py` already uses elsewhere) over the rest of the project's tables, dashboards, documents, and data sources — via `list_project_resource_candidates` (`workspace_context.py`), which excludes anything already pinned to the workspace. At most **two** candidates surface (`_UNPINNED_MATCH_LIMIT`), and only when they share **at least two terms** with the question (`_UNPINNED_MIN_OVERLAP`) — one shared word (e.g. "revenue") is not enough to surface every table in the project on every turn.

```
--- Also in this project, not pinned to this workspace ---
- a data source named 'Q3 Revenue'...
These are not open in the workspace. Treat any pinned or focused item above
as the primary subject of the question; use one of these only if the
question specifically needs it.
--- End ---
```

This is deliberately **not a visible feature** — no toggle, no button, no UI surface at all. It lives entirely inside prompt construction in `execute_turn`, which is what makes the "never affects routing" guarantee possible (next section). If the user wants a resource to be a first-class part of the workspace rather than an occasional background mention, the actual action is dragging it into Documents as a real pinned card.

One honest limitation: this is keyword overlap, not semantic search. "Q3 Revenue" won't match "third quarter income" even though a person would see the connection immediately. That's the tradeoff for something buildable with no new infrastructure (no embeddings, no search index) — and it applies identically whether you're looking at the mock-backed local preview or the live API, since the scoring function itself doesn't know or care which backend is serving it.

## Ordering, and why it's load-bearing

`execute_turn`'s prompt-assembly order matters and is worth preserving exactly if this code is touched:

1. `classify_turn(question, ...)` — intent routing runs on the **raw** user message. Nothing below this line has run yet.
2. Attachment context is prepended to `question`/`sql_question` (prompt-only; the persisted `turn.user_message` is never mutated).
3. `_format_active_resource_prompt` is prepended next.
4. `_find_unpinned_project_matches` is scored against `turn.user_message` — the **original**, unprefixed message, not the `question` variable being built up — specifically so the term-overlap scoring can't match on the active-resource block's own scaffolding words ("workspace", "currently", "open") instead of what the user actually typed. Its result is then prepended to `question`/`sql_question`.
5. `_format_context_snippets` is prepended last.

Every one of these blocks is added **after** `classify_turn` has already run. That's the whole reason project reach and pinned context can stay invisible and non-intrusive: they can only ever change what the model reads when forming an answer, never which code path (SQL generation, chart change, explain, clarification) the turn takes. If a future change needs one of these blocks to influence routing, it has to move above the `classify_turn` call deliberately, with the same care taken to keep it descriptive rather than imperative.

## Conversation memory (separate from all of the above)

`_build_llm_history` (`conversational_analytics/__init__.py`) is a different mechanism from everything above: it's what lets a follow-up like "explain more" resolve against the actual prior exchange rather than being treated as the first question in an empty conversation. A fixed window — the last 8 successful turns (`_HISTORY_MAX_TURNS`), each message capped at 600 characters (`_HISTORY_MSG_CHARS`), the whole window capped at 8,000 characters total (`_HISTORY_TOTAL_CHARS`, oldest dropped first) — is queried directly (not read off the lazily-loaded `conversation.turns` relationship, which would raise `MissingGreenlet` on an async session) and passed to answer synthesis only. It is **not** sent to intent classification or SQL generation — those already get `prior_turn` and its SQL directly, and sending full history to every one of a turn's 3–8 LLM calls would multiply cost for no benefit. Known limitation, by design: this is a window, not indexed memory — a thread longer than the budget forgets its oldest turns. That's the seam a future revamp (indexing or rolling summary) would attach to.
