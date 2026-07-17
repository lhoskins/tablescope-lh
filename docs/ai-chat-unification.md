# AI Chat Unification — One Pipeline for the AI Assistant

## The root cause of "still not working"

Tablescope had **two separate AI chat implementations**:

| Surface | Route | Backend | Had the chart classifier? |
|---|---|---|---|
| Global **AI Assistant** page (top-nav "AI", the one tested on the iPad) | `/ai` | old `/api/ai/conversations/{id}/messages` in `ai_proxy.py` | **No** |
| Project conversation screen | `/projects/{id}/ai` | `/api/conversational-analytics/...` | Yes |

Every chart-reformatting fix (regex removal, LLM classifier, donut support,
`data_question`, all of Devin's iterations) was built and verified against the
**project** pipeline. The global AI Assistant page never called any of it:

1. It passed the raw message straight to SQL generation — no intent
   classification, so "Make it donut" was treated as a data question.
2. Its chart was chosen purely from the result's shape
   (`_suggest_visualization(columns, rows)`) — "as a horizontal bar chart" was
   ignored, and a vertical bar rendered.
3. When SQL generation failed, it fell back to the raw prose model and stored
   the model's unfiltered output — which is why chat bubbles showed
   "To create a donut chart, I'll need to modify the existing query…" followed
   by a literal ` ```sql ` block.

That is why every verification transcript looked green while the product
stayed broken: the fixes and the tests ran against one pipeline, the user ran
against the other.

## What changed (before / after)

### 1. The global AI Assistant now runs on the conversational-analytics engine

**Before** — `web-ui/app/ai/page.tsx` called the old endpoints:

```ts
import {
  useConversations, useConversation, createConversation,
  sendConversationMessage, ...
} from "@/lib/ui/use-shell-data";           // -> /api/ai/conversations/...
```

**After** — the same page (same look: sidebar, bubbles, project picker) calls
the conversational-analytics API, so the LLM intent classifier, structured
chart patches, donut/horizontal subtypes, and grounded column validation all
apply on every turn:

```ts
import {
  createConversation, listConversations, getConversation, submitTurn,
  renameConversation, deleteConversation,
} from "@/lib/api/conversational-analytics"; // -> /api/conversational-analytics/...
```

Turns render through the shared chart contract — `chart_config.subtype`
(`horizontal_bar`, `donut`, …) rides into the dashboard `WidgetRenderer` as
`chartStyle`, so a requested format is actually drawn. Chart follow-up chips
("change it to a donut chart", "change it to a horizontal bar chart", …) are
now on this screen too.

A conversation is created against a selected project and stays scoped to it
(the picker locks while a thread is open), matching how answers are grounded.

### 2. The old pipeline is retired

Removed from `platform-api/app/routes/ai_proxy.py` (~370 lines):

- `GET/POST /api/ai/conversations`, `GET/PUT/DELETE /conversations/{id}`,
  `POST /conversations/{id}/messages`, `POST /conversations/{id}/branch`
- Their helpers (`_conversation_dict`, `_message_dict`,
  `_get_owned_conversation`, branching logic)
- `platform-api/tests/test_ai_conversations.py` (tested only those routes)
- The client functions/types in `web-ui/lib/ui/use-shell-data.ts`

Kept: the `/api/ai/ask` prose endpoint (used by insight surfaces for
document/knowledge-graph questions) and `_chat_answer_text` (used by the /ask
data-first path). The `ai_conversations` DB tables are left in place — nothing
writes to them anymore; a drop migration can follow later. Conversation
branching had no equivalent in the new engine and was dropped (history was not
required).

### 3. Raw model output can no longer leak into chat

Every prose answer now passes through `_strip_model_markup`, which removes
fenced ``` blocks (including unterminated ones) before the text is returned to
any surface. The SQL for data answers is carried separately in structured
fields, never inline in prose. Applied to `_forward_prose_answer` (the
ask-and-run fallback) and to `/api/ai/ask` responses.

### 4. The classifier prompt is de-overfitted

The conversation-turn classifier prompt had accumulated ~15 few-shot examples
hardcoding one tenant's demo data — "IT backup jobs", "Count of IT backup jobs
grouped by Result" appeared in the decision rules and in 8 examples. On any
other project, an 8B model is prone to parroting those strings as the
`data_question`.

**After:**

- All rules and examples moved to
  `ai-server/.../app/prompts/conversational_analytics_best_practices.md`
  (rewritten, generic, fictional example domains) and the file is now actually
  **injected** into the prompt via `load_prompt_reference` — the same pattern
  as the dashboard/project-insight best-practice guides. One editable source
  of truth, no tenant data in it.
- The prompt explicitly states the examples are fictional and must never be
  copied into output; `data_question` must rewrite *this* user message.
- Nine balanced examples cover: new analysis with/without a chart style,
  donut/horizontal requests, chart-only follow-ups, complaint + reformat,
  query change, sort, and explain.

### 5. Deterministic grounding guard for `data_question`

Even with a clean prompt, a small model can echo an example. The platform now
accepts the model's rewritten `data_question` only if it shares at least one
non-filler content word with what the user actually typed
(`_grounded_data_question` in `conversational_analytics.py`); otherwise the
raw user message is used and a warning is logged. Filler words ("count",
"grouped", "by", …) don't count as overlap, so a parroted rewrite about the
wrong subject is always discarded.

### 6. Deterministic answer text for data turns

Successful data turns answer with a scalar ("`JobCount: 42`") or a row-count
summary ("Here are the results (4 rows).") built in code — never raw model
prose.

## Verification

- `platform-api`: full suite — **664 passed** (includes 2 new tests:
  parroted-`data_question` rejection, code-fence stripping; the 10 removed
  old-pipeline tests went with their routes).
- `ai-server`: **39 passed**.
- `web-ui`: `npm run typecheck` clean; `npm run lint` clean apart from one
  pre-existing unrelated warning.
- `ruff` clean on all touched Python files.

## Deployment

Both hosts must be rebuilt from this commit:

- App host (13.57.117.13): `platform-api`, `platform-api-worker`, `web-ui`
- AI host (32.186.54.52): `tablescope-ai-api`, `ai-worker`

## Suggested smoke test (on the global AI page, `/ai`)

1. "Run IT backup jobs as a horizontal bar chart" → horizontal bars.
2. "Make it donut" → same data, actual ring, no SQL prose.
3. "Only show failed jobs" → new SQL, data changes.
4. "Show the SQL" → the query, plainly.
5. "Make it fancier" → a clarification prompt, not a query re-run.
