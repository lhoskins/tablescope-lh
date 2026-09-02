# Devin: merge + deploy — chat answer decimal precision + markdown rendering

**Repository:** `lhoskins/tablescope-lh`
**Branch to merge:** `fix-chat-number-precision-and-markdown`
**Base:** `UX-design-03`

**1 commit · `ai-server/` + `web-ui/` · no migration, no platform-api change · all tests green**

---

## 1. What this fixes

Two UI-quality issues flagged from screenshots of the chat/insight-card
surfaces:

**1a. Inconsistent decimal precision.** "Give me the average resolution
hours by category" answered:

> Average resolution hours by category are Network 44.43 hours, Hardware
> 36.20 hours... **Network has the highest average resolution time at
> 44.42777777777778 hours**, while Application is the lowest at
> 28.550000000000004 hours.

Same value, two different precisions in the same sentence — the first
mention rounded fine, the superlative re-statement didn't.

**1b. Literal `**` instead of bold.** Chat answers and insight-card
summaries showed text like `**WC-004** leads with **$506,713.68** total
scrap cost` verbatim, asterisks and all, instead of rendering as bold.

## Root causes

**1a** — `ai-server/tablescope-ai-api/app/routers/ai_ask.py`'s `/ai/ask`
endpoint synthesizes the chat answer from an already-executed query's rows.
`_format_data_result`/`_format_investigation_steps` embed those rows into
the prompt via `f"{k}={v}"` — raw `str(v)` on whatever Teiid returned,
including a full-precision Python float for a computed aggregate. The model
apparently rounds when composing prose freely but copies a cited value
verbatim when restating it, so the two mentions of "the same number" in one
answer can carry different precision.

**1b** — the `**bold**` markdown was already there in the model's output;
nothing ever rendered it. `Prose`/`BulletList` in
`web-ui/components/ai/ResponsePresenter.tsx` and `InsightCard`'s
summary/diagnostics/actions in
`web-ui/components/tablescope/conversation/matched-insight-block.tsx` were
all plain `<p>{text}</p>` / `<li>{line}</li>` — no markdown parsing
anywhere on these surfaces (confirmed: no markdown library used in any chat
or insight-card rendering path in the repo).

## 2. What changed

### ai-server (`app/routers/ai_ask.py`)

- New `_format_row_value(value)`: rounds a `float` row value to 2 decimal
  places before it's ever embedded in the prompt (non-floats pass through
  unchanged). Used in both `_format_data_result` and
  `_format_investigation_steps`'s row-dump lines.
- Prompt text for the grounded-answer path now explicitly says "Cite
  specific numbers, rounded to at most two decimal places" (was just "Cite
  specific numbers").
- New `_round_long_decimals(text)`: a deterministic regex backstop
  (`\b\d+\.\d{3,}\b`, rounded to 2dp) applied to the returned `answer`
  after the existing `to=self`-artifact strip — catches a number the model
  computes/derives on its own (not copied from a row) at full precision,
  which pre-rounding the rows alone wouldn't cover.

### web-ui

- New `components/ai/inline-markdown.tsx`: `renderInlineMarkdown(text)` /
  `<InlineMarkdown text={...} />`. Intentionally minimal — bold (`**...**`)
  only, no full markdown/HTML parsing, renders directly to React nodes
  (`<strong>`), never `dangerouslySetInnerHTML` — there's no injection
  surface to review here.
- Wired into `ResponsePresenter.tsx`'s `Prose` (chat summary/answer text)
  and `BulletList` (key points/findings/drivers/recommended actions), and
  `matched-insight-block.tsx`'s `InsightCard` summary, `DiagnosticStep`'s
  finding/highlight, and `ProposedActionItem`'s headline — every place
  free-form LLM-authored text was rendered as plain text on these two
  surfaces.

## 3. Tests added

- `ai-server/tablescope-ai-api/tests/test_ai_ask_number_formatting.py` (4
  tests): `_format_row_value` rounds floats / leaves other types alone;
  `_round_long_decimals` rounds 3+-decimal-digit numbers and leaves
  already-short ones untouched, using the exact reported live values
  (`44.42777777777778` → `44.43`, `28.550000000000004` → `28.55`).
- `web-ui/components/ai/inline-markdown.test.tsx` (4 tests): renders
  `**bold**` as `<strong>`, leaves plain text unchanged, leaves an unpaired
  `**` as literal text rather than dropping it, handles an empty string.
- `web-ui/components/ai/ResponsePresenter.test.tsx` (2 tests, new file):
  `Prose`-rendered summary text renders bold correctly and plain text
  unchanged.
- `web-ui/components/tablescope/conversation/matched-insight-block.test.tsx`
  (+1 test): the exact reported live text (`**WC-004** leads with
  **$506,713.68**...`) renders with no literal `**` and a real `<strong>`.

## 4. Verification

| Suite | Result |
|---|---|
| ai-server `pytest` (full) | 160 / 160 passed (156 existing + 4 new) |
| ai-server `ruff check` (touched files) | clean |
| web-ui `vitest` (`components/ai`, `components/tablescope/conversation`) | 24 / 24 passed (17 existing + 7 new) |
| web-ui `tsc --noEmit` (whole project) | clean, 0 errors |
| web-ui `eslint` (touched files) | clean |

```bash
cd ai-server/tablescope-ai-api
pytest -q
ruff check app/routers/ai_ask.py tests/test_ai_ask_number_formatting.py

cd ../../web-ui
npx vitest run components/ai components/tablescope/conversation
npx tsc --noEmit
npx eslint components/ai/inline-markdown.tsx components/ai/ResponsePresenter.tsx components/tablescope/conversation/matched-insight-block.tsx
```

## 5. Deploy

Two independent services, no shared contract change, no migration.

```bash
docker compose build ai-api
docker compose up -d ai-api

cd web-ui
# your normal build/deploy step (Vercel/Next build, etc.)
```

### Rollback
```bash
git revert 787170cf
```

## 6. Verify live

- Re-ask "What is the average resolution hours by category?" (or any
  question producing a superlative sentence over an aggregate) and confirm
  every mention of the same figure shows the same, 2-decimal precision.
- Confirm an insight-card summary or chat answer containing model-authored
  emphasis (e.g. a top-work-center/top-performer breakdown) renders real
  **bold** text, not literal asterisks.
- Spot-check a plain, markdown-free answer still renders identically to
  before (both changes are no-ops on content that doesn't need them — see
  the "leaves ... unchanged" tests in both new test files).

## 7. Report back

Confirmation both reported screenshots' issues no longer reproduce; and
whether any *other* chat/insight surface not touched here (this pass
covered `ResponsePresenter`'s `Prose`/`BulletList` and
`matched-insight-block`'s `InsightCard` specifically, matching where the
screenshots were taken from) shows the same literal-`**` symptom — if so,
that's the same `renderInlineMarkdown` swap applied to one more `<p>`/`<li>`,
not a new investigation.
