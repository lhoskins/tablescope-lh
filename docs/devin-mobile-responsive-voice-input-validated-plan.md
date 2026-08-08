# TableScope Devin-Ready Implementation Plan

## Mobile-Responsive Application and Private Voice Input (Validated and Enhanced)

**Status:** Ready for implementation
**Recommended branch:** `devin/mobile-responsive-voice-input`
**Base branch:** `devin/r-echarts-e2e-validation`. This is confirmed, not merely assumed — every feature merged and deployed this cycle (KG/nav fixes, Databricks/Snowflake and HubSpot/QuickBooks Teiid translators, LDAP/SSO, the eight-item bug/enhancement batch, conversation-consolidation follow-ups) has landed on this branch, and it is the branch Devin has been merging into and reporting as deployed. Before coding, still `git fetch origin devin/r-echarts-e2e-validation` and diff against the SHA recorded here, because additional PRs may land between this plan being written and Devin starting work — the branch identity is settled, freshness is not.
**Deployment method:** Pull request, automated validation, responsive-device review, staging deployment, production deployment behind feature flags.

---

## 0. Validation notes and corrections

This section records what changed from the original draft after checking it against the actual repository (commit `5a24de88` on `devin/r-echarts-e2e-validation`). Nothing below is a rejection of the plan's architecture — the recorded-audio-plus-private-server-transcription design is correct and unchanged. These are corrections and sharpenings so Devin isn't guessing at things the codebase already answers.

1. **No shared "Ask Anything" composer exists today.** Phase 0, item 5 of the original plan treats this as something Devin must go discover. It doesn't need discovering — it's already false. There are at least four independent input implementations across the three target surfaces, all built on the same low-level `AutosizeTextarea` primitive (`web-ui/components/ui/autosize-textarea.tsx`) but with no shared composer wrapper above it:
   - `web-ui/components/tablescope/project/ai-assistant-screen.tsx` (line 15 imports `AutosizeTextarea`, ~line 149) — local textarea + submit button, calls `askProjectAi` from `web-ui/lib/ui/use-project-data.ts`.
   - `web-ui/components/tablescope/home/insight-ask-box.tsx` (`InsightAskBox`) — a separate implementation used only from `web-ui/app/business-insight/analysis/[insightId]/page.tsx` (the per-card "Full analysis" ask box), calling `aiActionsApi.askAndRun()` from `web-ui/lib/api/ai-actions.ts`.
   - `web-ui/components/tablescope/project-insight/project-insight-screen.tsx` — a third implementation (`handleProjectAsk`, ~line 329), rendering through `IntelligenceWorkspace`/`TurnBubble` from the canonical-conversation package.
   - `web-ui/components/ai/AIPanel.tsx` and `web-ui/components/tablescope/home/hero-search.tsx` — further independent `AutosizeTextarea` usages (dashboard-generation and home search, not one of the three target surfaces, but evidence of how scattered this pattern already is).
   This means Phase 4 step 1's "Consolidate the Ask Anything composer if necessary" is not conditional — it is required, and it is a bigger job than one line suggests: three different mutation call sites, three different result-rendering paths, and three different loading/error state shapes need to converge on one component before a microphone button can be added once and behave identically everywhere. See the workstream change in section 5 below.

2. **A voice input already exists in the product today, and it is not private.** `web-ui/components/ai/AIPromptBar.tsx` implements a working microphone button using the browser's Web Speech API (`window.SpeechRecognition` / `window.webkitSpeechRecognition`), which routes audio through the browser vendor's own recognition service (Apple's or Google's, depending on browser) — exactly what section 2.2 of this plan prohibits. It's wired into `web-ui/components/dashboard/DashboardTab.tsx`'s "Generate Dashboard" prompt bar, not into any of the three target Ask Anything surfaces, so it does not conflict with the letter of this plan's scope. But it does conflict with the plan's spirit: shipping a second, differently-private microphone button elsewhere in the same app undermines the "audio never leaves the isolated TableScope environment" claim this plan wants to be able to make. Devin must make an explicit choice and say which one was taken in the PR, not silently leave both in place:
   - **Recommended:** fold the dashboard-generation prompt bar onto the same shared `VoiceInputButton`/`useVoiceRecorder` pipeline built for the three target surfaces, retiring `AIPromptBar`'s `SpeechRecognition` branch entirely, or
   - Explicitly remove `AIPromptBar`'s microphone button (typed input only) if consolidating that fourth surface is out of scope for this PR, with a short note in the PR description explaining why a second voice mechanism was not left in the product.

3. **No custom Tailwind breakpoints exist, and the container-query plugin is not installed.** `web-ui/tailwind.config.ts` has no `screens` override — only Tailwind's defaults apply (`sm` 640px, `md` 768px, `lg` 1024px, `xl` 1280px, `2xl` 1536px). There is currently no Tailwind utility that can distinguish anything below 640px, so the plan's own "compact phone 320–479 / large phone 480–767" split (section 3.1) cannot be expressed with existing utilities — it needs a real addition, not just "use existing tokens if present." Also, `web-ui/package.json` pins `tailwindcss@^3.4.13` with no `@tailwindcss/container-queries` dependency, so the plan's recommendation to "use container queries for reusable cards and panels" (section 3.1) requires adding that plugin (or hand-rolling `@container` CSS) — it is not available out of the box on this Tailwind version. Phase 1 must add both explicitly.

4. **The HMAC request-signing precedent is real, but the exact location differs from what an earlier internal draft assumed.** The client that signs platform-api → ai-server requests is a single file, `platform-api/app/services/ai_intelligence_client.py` — not a package. `_sign_payload()` (line 69) does `hmac.new(secret.encode(), canonical_json.encode(), hashlib.sha256).hexdigest()` over a canonicalized payload; the signature is attached at line 125 before the request goes out. This is exactly the mechanism the new platform-api → ai-server transcription call in section 4.2 should reuse — same signing helper, same shared-secret convention — rather than inventing a second signing scheme. One caution: this file's `_TIMEOUT` is `httpx.Timeout(300.0, connect=10.0)` (line 29), sized for LLM generation calls. Do not default the new transcription call to that same 300-second budget — a ≤120-second audio clip should transcribe in well under a minute; give the transcription endpoint its own, much shorter timeout and treat anything approaching it as a service-unavailable state (section 4.5), not a hung request.

5. **The existing "LLM/model-vault deployment process" cannot serve a Whisper-family model as-is — it is GGUF- and Ollama-specific.** `platform-api/app/services/llm_ollama_adapter.py`'s `install()` copies a verified GGUF file into an install directory, writes an Ollama `Modelfile`, and runs `ollama create`. `faster-whisper` (the model this plan recommends) is a CTranslate2-format model, not GGUF, and Ollama does not serve speech-to-text models at all — it is a chat/embedding LLM runtime only. Section 4.4's "package a local Whisper-compatible model through the existing LLM/model-vault deployment process" needs to be read narrowly: reuse the *artifact verification and signed-transfer* half of that pipeline (getting a vetted binary from the model vault onto the AI server through the same trusted channel used for LLM weights today), but the *serving* half needs a new, separate process — a small `faster-whisper`/CTranslate2 runtime running alongside Ollama on the AI server, not `OllamaAdapter.install()` / `ollama create`. Say this explicitly in the plan so Devin doesn't spend time trying to coerce Whisper through the Ollama adapter before discovering it can't.

6. **The GPU contention section 4.4 treats as a contingency is already a confirmed, existing fact, not a hypothetical.** The AI server currently runs on a single `g6.xlarge` (1× L4, 24GB) with `llama3.1:8b` for generation and `nomic-embed-text` for embeddings both served through the same Ollama process on that one GPU; `max_jobs=1` is already set on the arq worker specifically to serialize AI calls because the GPU can't run them concurrently (`platform-api/app/tasks/workflows.py:1488`, with an explanatory comment to that effect), and `home_intelligence_max_concurrent_ai_calls_per_project=1` (`platform-api/app/config.py:165`) exists for the same reason. Adding a third GPU-resident workload to a card that's already serialized down to one job at a time is not something to evaluate later — it's already known to be a problem. Given recordings are capped at 120 seconds and users are already reviewing a transcript before sending (i.e., this path tolerates a few seconds of extra latency far better than interactive chat generation does), **the plan should recommend CPU-based `faster-whisper` (int8 quantization) as the default**, not GPU. That sidesteps the existing contention entirely without new infrastructure. Only fall back to a dedicated GPU service (as the original section 4.4 proposed) if real measurement on the CPU path shows unacceptable latency — measure before provisioning.

7. **A per-tenant boolean-toggle precedent already exists and should be reused for `VOICE_INPUT_ENABLED`.** `platform-api/app/models/tenant.py` puts feature toggles directly on the `Tenant` model as plain boolean columns — `enforce_2fa`, `allowed_domains_enabled` — each added by its own migration, not through a generic JSONB flags blob. Add `voice_input_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)` to `Tenant` the same way, with a migration mirroring the `allowed_domains_enabled` one, instead of introducing a new flags mechanism.

8. **A rolling-window rate-limit precedent already exists and should be reused for the transcription endpoint.** `platform-api/app/services/mfa_sms_service.py` enforces per-user and per-phone rolling-window send caps against a dedicated events table (`MfaSmsEvent`) and config-driven window/cap settings (`settings.mfa_sms_window_seconds`, `settings.mfa_sms_max_sends_per_window`). Section 4.3/6.2's "rate limits" for `POST /api/ai/speech/transcribe` should follow this exact shape — either a small `VoiceTranscriptionEvent` table or a rolling-window query against the existing generic `AuditEvent` table — rather than pulling in a new rate-limiting library.

9. **iOS Safari's `MediaRecorder` needs explicit format branching, not just format acceptance.** Section 4.3 already lists `audio/mp4`/AAC as an iOS-compatible format to accept server-side, which is correct, but the client also needs to *choose* the right format at record time: iOS Safari's `MediaRecorder` in practice only reliably emits `audio/mp4` and will throw if asked for `audio/webm;codecs=opus`. `useVoiceRecorder` must call `MediaRecorder.isTypeSupported()` and try `audio/webm;codecs=opus` first, fall back to `audio/mp4`, and — if neither is supported — resolve directly to the Unsupported state (section 4.5) instead of letting `MediaRecorder`'s constructor throw an uncaught exception.

10. **Workstream ordering risk.** Because finding 1 (no shared composer) means composer consolidation is a real prerequisite for coherent work on the three AI surfaces, and Phase 3 remediates those exact three surfaces first (its own stated order), doing the consolidation in Phase 4 — after Phase 3 has already touched those pages — risks redoing Phase 3's AI-surface work a second time once the shared composer lands. Section 5 below moves composer consolidation into Phase 2, ahead of Phase 3's page-by-page pass.

None of this changes the plan's scope, its privacy posture, or its non-negotiable requirements in section 2. It sharpens the parts that were previously open questions into concrete instructions, and fixes two assumptions (Ollama-for-Whisper, GPU-by-default) that would otherwise have cost Devin a discovery cycle mid-implementation.

---

## 1. Objective

Make the complete TableScope web application usable on Apple iOS and Android phones without reducing or breaking the desktop experience. Add private voice-to-text input to the shared Ask Anything experience used by:

1. AI Assistant
2. Business Insights
3. Project Insights

The work must establish reusable responsive primitives and one shared voice-input implementation. Do not create page-specific microphone logic or solve responsiveness with isolated CSS overrides. Per validation note 1, "shared" is a construction task, not a discovery task — there is no existing shared composer to extend.

---

## 2. Non-negotiable product requirements

### 2.1 Responsive application

- No page-level horizontal overflow at supported phone widths.
- All application content remains reachable by touch, keyboard, and assistive technology.
- Cards resize to the available width and never clip titles, summaries, actions, charts, tables, filters, status labels, or modal content.
- Desktop layout and behavior remain unchanged at desktop breakpoints unless a change is explicitly required by this plan.
- Preserve tenant, project, role, data-plane, and conversation isolation.
- Preserve the existing insight-card **More Actions** behavior. On mobile, the data-source row and secondary actions remain collapsed until the user expands More Actions.
- Wide data grids use an intentional internal horizontal scroller; the entire page must not horizontally scroll.
- Mobile charts must be readable, touch-safe, and responsive through the shared ECharts/WidgetRenderer path.

### 2.2 Voice input

- Show a microphone control in every shared Ask Anything composer on AI Assistant, Business Insights, and Project Insights.
- A user explicitly starts and stops recording.
- Convert speech to editable text in the existing composer.
- Do **not** automatically submit the question after transcription. The user can review, edit, cancel, or send it.
- Audio must not be retained by default.
- Transcription must use the isolated TableScope AI environment rather than depending on Apple, Google, or another public speech-recognition service. Per validation note 2, this requirement is not hypothetical: it directly supersedes the `SpeechRecognition`-based mechanism already shipping in `AIPromptBar.tsx`, and this PR must say what happened to that mechanism.
- The feature must fail safely when microphone access is denied, unavailable, interrupted, or unsupported.
- Typed input remains available at all times.

---

## 3. Target responsive behavior

### 3.1 Breakpoints

Per validation note 3, no usable breakpoint tokens exist below Tailwind's default 640px `sm`, and the container-query plugin is not installed. Add both explicitly in Phase 1:

```ts
// web-ui/tailwind.config.ts
theme: {
  extend: {
    screens: {
      xs: "480px",   // large-phone boundary; nothing below sm(640) exists today
      // keep Tailwind's sm/md/lg/xl/2xl as-is — desktop breakpoints are unaffected
    },
  },
},
plugins: [
  require("@tailwindcss/container-queries"), // new dependency; not currently installed
  // ...existing plugins
],
```

| Mode | Viewport | Expected layout | Tailwind mechanism |
|---|---:|---|---|
| Compact phone | 320–479 px | One content column; drawer navigation; full-width cards and sheets | default (below `xs`) |
| Large phone | 480–767 px | One content column; selected two-column micro-layouts only where each control remains usable | `xs:` |
| Tablet | 768–1023 px | Two-column layouts when content permits; collapsible side panels | `md:` |
| Desktop | 1024–1439 px | Existing desktop layout | `lg:` |
| Wide desktop | 1440 px and above | Existing wide layout with bounded readable content where appropriate | `xl:`/`2xl:` as already used |

Use container queries (`@container`, via the new plugin) for reusable cards and panels — insight cards, dashboard widgets — when component width, not viewport width, determines the correct presentation. Confirm during Phase 1 whether the installed Tailwind 3.4.x container-query plugin version needs any PostCSS config changes; do not assume it's drop-in without checking the build.

### 3.2 Application shell and navigation

On phone widths:

- Replace the persistent left sidebar with a menu button and accessible slide-out drawer.
- Show the TableScope/project identity in a compact header.
- Close the drawer after navigation and restore focus to the trigger.
- Keep tenant/project switching accessible inside the drawer.
- Convert secondary project navigation into a horizontally scrollable tab row or a compact overflow menu without truncating destinations.
- Move the AI Context right panel into a drawer or collapsible section reachable from the project header.
- Use `100dvh`, not fixed `100vh`, to handle iOS Safari browser chrome.
- Respect `env(safe-area-inset-top/right/bottom/left)` for notched devices.
- Ensure the software keyboard does not cover the AI composer or modal submit controls.

### 3.3 Shared content behavior

| Component | Phone behavior |
|---|---|
| Insight cards | Full width; header wraps; status and pin remain visible; chart/control groups stack |
| More Actions | Collapsed by default; full-width disclosure row; expanded actions wrap or use compact icon toolbar with tooltips/accessible labels |
| Charts | Resize through WidgetRenderer; minimum readable height; responsive labels; horizontal control strip where necessary |
| Tables/grids | Internal horizontal scroll; sticky first column when useful; visible scroll affordance; no body overflow |
| Percent Change Summary | Preserve continuous horizontal period scroll; sticky Insight column; statistics remain at row end; cell background colors preserved. Note: this panel already gained a statistics on/off toggle this cycle (`web-ui/components/tablescope/home/percent-change-summary-panel.tsx`, `SHOW_STATISTICS_STORAGE_KEY`, default off) — the mobile layout must accommodate that toggle's control, not just the columns it shows/hides. |
| Dashboard grid | One column on compact phones; two columns only when widget minimum width is satisfied; disable unusable drag/resize gestures or provide explicit move controls |
| Forms | Labels above fields; controls full width; validation near field; logical mobile keyboard/input modes |
| Dialogs | Full-screen dialog or bottom sheet on phones; ordinary modal on desktop |
| Drawers | Full-width or near-full-width on phones; focus trapped; swipe is optional, close control is mandatory |
| Toasts | Fit within safe area and viewport; do not cover composer controls |
| Filters | Collapsible filter sheet; active-filter count remains visible |
| Long titles | Wrap to multiple lines; never ellipsize the only identifying text without an accessible full value |

### 3.4 Page coverage

Audit and remediate every authenticated route. At minimum include:

- Home
- Business Insights
- AI Assistant
- Project Home/Overview
- Project Insights
- Project Actions and subitems
- Goals/Success Criteria, measures, and risks
- Scopes and scope relationship builder
- Knowledge Graph and Graph Lifecycle (the interactive canvas at `/relationship-map` and the build/lifecycle page at `/knowledge-graph` are two distinct pages — cover both)
- Data Source Builder, Connected Sources, network file browsing, and project assignment
- Data Sources and Tables
- Documents and document-family views
- Dashboards, dashboard editor, and widget configuration
- Metadata Catalog
- Reference Library: Industry, Company, and Project views
- Audit Log
- Settings and all administration panels, including the relocated Allowed Host panel now under Settings → Security
- Users, authentication, 2FA, LDAP, SSO, and tenant administration where enabled
- LLM Framework and platform-only administration surfaces

Complex desktop-only builders such as the scope canvas and the relationship-map KG canvas may use a guarded mobile read-only summary plus an explicit "Edit on a larger screen" state if a safe touch editing experience cannot be delivered in this release. This exception must be documented and approved; do not leave a broken canvas.

---

## 4. Voice-input architecture

### 4.1 Recommended design

Do not make browser `SpeechRecognition` the primary implementation. Browser support and behavior vary, and recognition may use browser/vendor services outside the isolated TableScope environment. Per validation note 2, `AIPromptBar.tsx` already does this today for dashboard generation — treat that as the thing being replaced/retired, not as a working reference to build from.

Use this flow:

1. User taps the microphone inside the shared AI composer.
2. Browser requests microphone permission only after that user gesture.
3. Capture audio with `navigator.mediaDevices.getUserMedia({ audio: true })` and `MediaRecorder`, selecting the recording MIME type via `MediaRecorder.isTypeSupported()` (validation note 9): try `audio/webm;codecs=opus`, then `audio/mp4`, then fall through to the Unsupported state.
4. Display recording duration, live recording state, Stop, and Cancel.
5. Upload the audio through the authenticated platform API.
6. Platform API validates the user, tenant, project context, MIME type, duration, and size.
7. Platform API forwards the audio to a signed private AI-server transcription endpoint, signed with the same `_sign_payload()` HMAC scheme used in `platform-api/app/services/ai_intelligence_client.py` (validation note 4).
8. The isolated AI server transcribes with a locally installed speech-to-text model.
9. Return transcript text only and insert it at the current composer cursor position.
10. Stop media tracks and purge temporary audio in success, cancellation, and error paths.
11. The user reviews and sends the transcript through the existing question pipeline.

### 4.2 Components and services

Create or consolidate the following responsibilities, adapting names to repository conventions:

```text
web-ui
  shared AskAnythingComposer (replaces the ad-hoc AutosizeTextarea usage in
    ai-assistant-screen.tsx, insight-ask-box.tsx, and project-insight-screen.tsx —
    see section 5, Phase 2)
  VoiceInputButton
  useVoiceRecorder
  VoiceRecordingSheet

platform-api
  POST /api/ai/speech/transcribe
  speech transcription proxy/service (sign outbound request with the existing
    _sign_payload() helper from app/services/ai_intelligence_client.py; do not
    add a second signing scheme)
  request validation, audit metadata (reuse the generic AuditEvent table),
    rate limits (reuse the MfaSmsEvent rolling-window pattern from
    app/services/mfa_sms_service.py — see validation note 8)

ai-server
  POST /ai/speech/transcribe
  local STT adapter (a new CTranslate2/faster-whisper runtime process,
    separate from the Ollama-based OllamaAdapter used for chat/embedding
    models — see validation note 5; do not attempt to serve this model
    through `ollama create`)
  model health/readiness endpoint integration
```

The three surfaces must render the same shared composer or the same voice-control hook. A behavior correction made later must apply to all three surfaces. Per validation note 1, this also means retiring three separate result-rendering/mutation call sites (`askProjectAi`, `aiActionsApi.askAndRun`, `handleProjectAsk`) behind one composer's input/submit contract — the mutation *targets* can stay different (each surface still asks its own endpoint), but the input chrome, mic button, and state machine must be identical.

### 4.3 Audio handling

- Accept browser formats actually emitted on supported devices, including `audio/webm;codecs=opus` and iOS-compatible `audio/mp4`/AAC.
- Normalize audio server-side with a pinned, patched FFmpeg build before transcription.
- Maximum recording duration: configurable, default 120 seconds.
- Maximum upload size: configurable and derived from supported duration/bitrate; default no greater than 20 MB.
- Reject empty, malformed, polyglot, or unsupported media.
- Store only in an encrypted temporary/quarantine location when buffering is required.
- Delete temporary bytes immediately after transcription or failure.
- Do not write raw audio to application logs, Redis, conversation history, object storage, or model-training datasets.
- Audit metadata only: tenant, user, project if applicable, surface, duration, status, latency, selected language, and error category. Write these through the existing generic `AuditEvent` table (`app/models/...` — same JSONB-friendly pattern used for `tenants_security_policy.py` and the project/tenant member self-change logging added this cycle), not a new table.
- Never log transcript text in infrastructure logs beyond the existing governed conversation/audit policy.
- Give the transcription HTTP call its own short timeout (tens of seconds, not the 300-second budget `ai_intelligence_client.py` uses for LLM generation — validation note 4); treat a timeout as the "Service unavailable" state in section 4.5.

### 4.4 Speech model and isolation

- Stage and verify the `faster-whisper` model artifact through the existing model-vault verification/signed-transfer channel (the trust boundary, not the Ollama-specific `install()`/`Modelfile`/`ollama create` mechanism — validation note 5, since that mechanism is GGUF-only and Ollama does not serve STT models).
- Serve the model via a new, separate `faster-whisper`/CTranslate2 process on the AI server, running alongside — not through — Ollama.
- Recommended starting configuration: `faster-whisper` **medium, int8-quantized, running on CPU**, not GPU (validation note 6). The existing AI-server GPU is already fully committed to `llama3.1:8b` generation and `nomic-embed-text` embeddings with `max_jobs=1` serialization; a 120-second-capped, review-before-send transcription workload tolerates CPU latency far better than it tolerates contending for the one GPU that's already the bottleneck for interactive chat. Measure real CPU transcription latency during Phase 4 before considering GPU placement or a separate GPU service.
- Do not download a speech model from the AI server at runtime.
- Isolate transcription admission from LLM generation so long speech jobs cannot starve Ask Anything or insight generation — with the CPU-based default above, this is naturally true (separate resource entirely), but still cap concurrent transcription jobs so a burst of uploads can't exhaust AI-server CPU/memory.
- If measured CPU latency proves unacceptable, fall back to a dedicated GPU service or independently reserved GPU capacity rather than sharing the existing L4.
- Add `VOICE_INPUT_ENABLED`, `VOICE_TRANSCRIPTION_MODEL`, `VOICE_MAX_DURATION_SECONDS`, `VOICE_MAX_UPLOAD_BYTES` environment variables, plus per-tenant enablement as a `voice_input_enabled` boolean column on `Tenant`, mirroring the existing `enforce_2fa`/`allowed_domains_enabled` columns and their migrations (validation note 7) rather than a new flags mechanism.

### 4.5 Voice states and wording

| State | UI behavior |
|---|---|
| Available | Microphone icon with tooltip/label "Speak your question" |
| Permission request | Brief explanation that audio is transcribed privately by TableScope |
| Recording | Red active indicator, elapsed time, Stop and Cancel |
| Processing | Spinner and "Transcribing…"; typed text is preserved |
| Transcript ready | Insert editable text; announce completion to screen readers |
| Permission denied | Explain how to enable microphone access; keep typed input focused |
| Unsupported | Hide or disable microphone with accessible explanation; typing remains available. Includes the case from validation note 9 where `MediaRecorder.isTypeSupported()` finds no usable format. |
| No speech | "No speech detected. Try again." |
| Service unavailable | "Voice input is temporarily unavailable. You can continue typing." Includes transcription timeout (section 4.3) and AI-server-unreachable cases. |

Do not reuse the card-download, data-source-upload, or document-upload APIs for audio transcription.

---

## 5. Implementation workstreams

### Phase 0 — Baseline and regression inventory

1. Fetch `devin/r-echarts-e2e-validation` and record its current commit SHA in the PR description (the base branch is settled per the header; only the SHA needs confirming at start-of-work).
2. Inventory route layouts and shared components using `rg`; identify fixed widths/heights, `min-width`, overflow rules, absolute positioning, non-wrapping toolbars, and viewport assumptions.
3. Capture baseline desktop screenshots for the principal pages.
4. Add automated viewport smoke tests before changing layout.
5. Confirm the composer inventory in validation note 1 is still accurate (`ai-assistant-screen.tsx`, `insight-ask-box.tsx`, `project-insight-screen.tsx`, `AIPanel.tsx`, `hero-search.tsx`, `AIPromptBar.tsx`) — these were verified against commit `5a24de88`; re-check for drift if this plan starts later.
6. Record existing desktop behavior that must not regress, especially insight-card More Actions, percent-change controls and its statistics toggle, conversation consolidation, and Project Home navigation.

**Exit criterion:** Route/component matrix exists and every target surface has an owner component and test location.

### Phase 1 — Responsive foundations

1. Add shared breakpoint, spacing, safe-area, minimum-touch-target, and responsive typography tokens, including the `xs: 480px` Tailwind screen addition and the `@tailwindcss/container-queries` plugin (validation note 3).
2. Correct the root layout:
   - `width: 100%`
   - `min-width: 0` on flex/grid children
   - controlled `overflow-x`
   - `100dvh`
   - safe-area padding
3. Implement responsive application shell, mobile header, navigation drawer, and mobile project tabs.
4. Add reusable `ResponsiveStack`, `ResponsiveGrid`, `HorizontalScroller`, and mobile dialog/sheet behavior where the existing design system lacks them.
5. Ensure skip links, landmarks, focus order, and drawer focus restoration.

**Exit criterion:** Shell works at 320 px without page-level horizontal overflow and desktop screenshots remain visually equivalent.

### Phase 2 — Shared cards, charts, tables, forms, overlays, and the Ask Anything composer

1. Refactor shared card shells rather than patching individual cards.
2. Make InsightCard, KPI cards, dashboard widgets, source cards, action rows, goal rows, and document cards container-responsive.
3. Update WidgetRenderer/ECharts resize behavior using `ResizeObserver`; dispose observers and chart instances on unmount.
4. Provide compact chart controls with touch scrolling and selected-state visibility.
5. Implement table/grid internal scroll, sticky identifying columns, accessible captions, and keyboard scroll access.
6. Convert dense modals to full-screen mobile dialogs/bottom sheets.
7. Ensure action icons have visible focus styles, tooltips, `aria-label`s, and at least 44×44 CSS-pixel hit targets.
8. **Build the shared `AskAnythingComposer` and migrate `ai-assistant-screen.tsx`, `insight-ask-box.tsx`, and `project-insight-screen.tsx` onto it now**, ahead of Phase 3's page-by-page pass (moved up from the original plan's Phase 4 step 1 — see validation note 10). Leave the mic button itself disabled/unbuilt in this phase; the composer's job here is just to unify the input chrome, submit handling, and loading/error states so Phase 3 remediates one component's mobile layout three times by reference, not three independent ones, and Phase 4 has exactly one place to add voice.

**Exit criterion:** Shared components pass component tests at compact and desktop widths, and all three AI surfaces render through the same composer component (verified by a shared component test asserting identical DOM/behavior across the three usages, not just visual similarity).

### Phase 3 — Page-by-page remediation

Implement in this order:

1. AI Assistant, Business Insights, Project Insights (now working from the shared composer built in Phase 2)
2. Project Home and Home
3. Data Source Builder and Connected Sources
4. Dashboards and tables
5. Project Actions, Goals, risks, and scopes
6. Documents, Reference Library, Knowledge Graph (both `/knowledge-graph` and `/relationship-map`)
7. Settings, Users, LLM Framework, and administrative pages (including the relocated Allowed Host panel)

For each page:

- Test portrait and landscape.
- Test empty, loading, error, small-data, and high-density states.
- Test real long titles, filenames, datasource names, usernames, and generated narratives.
- Remove duplicated responsive CSS once shared primitives cover the case.
- Add the route to the responsive regression suite before marking it complete.

### Phase 4 — Shared voice input

1. Add the recorder hook (`useVoiceRecorder`) and voice UI states to the `AskAnythingComposer` built in Phase 2 — composer consolidation itself is already done by this point, so this phase is purely additive.
2. Implement `MediaRecorder.isTypeSupported()` format selection (validation note 9): `audio/webm;codecs=opus` first, `audio/mp4` fallback, Unsupported state if neither.
3. Add authenticated platform transcription endpoint (`POST /api/ai/speech/transcribe`) with request limits, feature gates (`voice_input_enabled` tenant column), tenant/project scope validation, rate limiting (reuse the `mfa_sms_service.py` rolling-window pattern), and temp-file cleanup on all paths.
4. Add the signed private AI-server endpoint (`POST /ai/speech/transcribe`) and the new `faster-whisper`-on-CPU STT adapter, signed via the existing `_sign_payload()` HMAC helper.
5. Add model readiness to AI health reporting without exposing infrastructure details to ordinary users.
6. Insert transcript into existing text without overwriting user-entered content.
7. Ensure route changes, component unmounts, Cancel, and browser interruption stop all media tracks.
8. Add audit events (via `AuditEvent`) and operational metrics (section 7).
9. Decide and document what happens to `AIPromptBar.tsx`'s existing `SpeechRecognition` mic button (validation note 2) — fold it onto this pipeline or remove it; do not leave it as a second, differently-private voice mechanism.
10. Enable in development/staging only until mobile device tests and privacy review pass.

### Phase 5 — Accessibility, device testing, and performance

1. Run automated accessibility checks plus manual VoiceOver and TalkBack review.
2. Validate 200% text zoom and large system font settings.
3. Validate reduced motion, high contrast, and dark/light themes if supported.
4. Verify mobile keyboard behavior for all forms and the sticky AI composer.
5. Lazy-load heavy chart/editor modules and avoid rendering collapsed insight content.
6. Measure cumulative layout shift, largest contentful paint, interaction latency, chart render time, and memory during long insight feeds.
7. Confirm the microphone stream indicator ends immediately after Stop, Cancel, success, error, navigation, logout, and idle timeout.
8. Measure real CPU-based transcription latency for the recommended `faster-whisper` medium/int8 configuration (validation note 6) against representative 30s/60s/120s recordings, and record the results in the PR — this is the evidence that determines whether the GPU fallback in section 4.4 is needed.

---

## 6. Automated test requirements

### 6.1 Frontend unit/component tests

- Drawer open/close, navigation, focus trap, Escape, and focus restoration.
- Shared composer displays microphone consistently on all three surfaces, and a single component test suite covers all three usages (validation note 1/Phase 2 exit criterion).
- Recording state machine: idle → permission → recording → processing → transcript/error, including the `isTypeSupported()` fallback branch and the no-supported-format Unsupported branch (validation note 9).
- Existing typed content is preserved and transcript is inserted correctly.
- Stop and Cancel stop all media tracks.
- Unsupported/denied microphone states never disable typing.
- Mobile More Actions remains collapsed and restores the existing data-source/action row when expanded.
- ECharts resizes when card/container width changes.
- Tables scroll internally and do not expand the document width.
- Percent Change Summary's statistics toggle remains reachable and functional at phone widths.

### 6.2 API and AI-server tests

- Authentication, tenant isolation, project membership, and rate limits (test the reused `mfa_sms_service.py`-style rolling window directly, including the boundary/reset behavior).
- Supported and unsupported MIME types.
- Oversized, over-duration, empty, malformed, and malicious payload rejection.
- Signed platform-to-AI request validation and replay protection, using the same `_sign_payload()` scheme already covered by `platform-api/tests/test_ai_intelligence_client.py` as a reference for how that suite tests signing today.
- Successful transcription and deterministic error mapping.
- Temporary-file cleanup on success, timeout, client disconnect, cancellation, and exception.
- Feature flag and tenant-toggle behavior (`voice_input_enabled` column).
- AI server unavailable does not affect typed Ask Anything.
- Admission control keeps transcription from starving interactive LLM requests — verify this holds even though the recommended default (CPU-based STT) makes contention unlikely; don't skip the test just because the default configuration avoids the failure mode.

### 6.3 Browser/device end-to-end matrix

Minimum physical or hosted-device coverage:

| Platform | Required targets |
|---|---|
| iOS Safari | Current major and previous major; iPhone SE-class width and current Pro/Pro Max |
| iOS Chrome | Current version; remember it uses the iOS browser engine |
| Android Chrome | Current and previous major; Pixel-class and Samsung-class widths |
| Android Samsung Internet | Current supported version |
| Tablet | Current iPad Safari and one Android tablet viewport |
| Desktop regression | Chrome, Edge, Safari and Firefox at existing supported sizes |

Use Playwright device profiles for continuous regression, but complete microphone permission/recording tests on real iOS and Android devices before production. Confirm on real iOS Safari that the `audio/mp4` recording path (validation note 9) actually reaches the transcription endpoint and decodes correctly server-side — this is the one path that can't be fully verified in a desktop-browser or emulator run.

### 6.4 Required E2E scenarios

1. Open every navigation destination at 320/375/390/412/430 px widths with no page-level horizontal overflow.
2. Ask a typed question from each AI surface.
3. Speak, stop, review, edit, and submit a question from each AI surface.
4. Deny microphone permission and continue by typing.
5. Start recording, navigate away, and confirm capture stops.
6. Rotate the device during recording and during chart viewing.
7. Open/close the software keyboard without losing Send or Stop controls.
8. Expand and collapse an insight card's More Actions area.
9. Use percent-change interval/range controls, its statistics toggle, and scroll its summary table.
10. Open Explain, chart options, action creation, filters, and download actions.
11. Upload and manage data sources/documents from a phone.
12. Confirm no user can retrieve or transcribe content outside their tenant/project authorization.

---

## 7. Observability and operations

Add metrics without recording audio or sensitive prompt content:

- Voice starts, cancellations, completions, errors, and permission denials
- Audio duration and byte-size histograms
- Transcription queue wait, processing time, and total latency
- STT model and deployment version
- Per-surface success rate
- Mobile frontend errors by viewport/browser
- Layout-overflow test failures
- AI/voice admission saturation (expected to stay near zero under the CPU-default configuration — treat any sustained non-zero reading as a signal the GPU-fallback path in section 4.4 needs evaluating)

Add alerts for sustained transcription failure, queue saturation, model unavailability, cleanup failure, and abnormal temporary-storage growth.

---

## 8. Security and privacy review

- Microphone access only follows a direct user gesture.
- HTTPS is mandatory.
- Set an explicit restrictive microphone Permissions Policy appropriate to the application origin.
- Do not enable microphone access in untrusted embedded frames.
- Apply existing CSRF/session protections and content-security policy.
- Do not pass audio through Redis.
- Do not retain audio by default.
- Encrypt any unavoidable temporary bytes and restrict them to the processing identity.
- Apply tenant and project authorization before forwarding audio to the AI server.
- Document STT in the customer-facing AI/privacy disclosure.
- Confirm idle logout stops active recording and releases the device.
- Confirm the disposition of `AIPromptBar.tsx`'s existing `SpeechRecognition` mic (validation note 2) is covered by this review — a retained non-private mic elsewhere in the app is a privacy-review finding, not a documentation footnote.

---

## 9. Rollout plan

1. Merge responsive foundations with voice disabled.
2. Deploy to staging and run screenshot/device regression.
3. Enable voice for an internal test tenant only.
4. Complete privacy/security review and isolated-network verification.
5. Load-test simultaneous typed questions, transcriptions, and insight rebuilds — including confirming the CPU-based STT default (section 4.4) doesn't starve the platform-api process pool under concurrent load, since it now shares CPU rather than GPU contention.
6. Enable mobile/voice canary for selected tenants.
7. Monitor for at least one business cycle.
8. Expand tenant enablement, retaining an immediate feature-flag rollback.

Rollback must disable voice without removing typed input or rolling back responsive layout changes.

---

## 10. Definition of done

- All targeted routes are usable at 320 px through wide desktop widths.
- There is no unintended page-level horizontal scrollbar.
- Desktop behavior has no material visual or functional regression.
- iOS and Android users can record, stop, transcribe, edit, and submit a question on all three AI surfaces, through one shared composer component (not three parallel implementations).
- Audio transcription remains inside the TableScope-controlled private pipeline, and the pre-existing `AIPromptBar` browser-speech mic has been either migrated onto that pipeline or removed.
- No raw audio is retained after processing.
- Typed input works when voice is disabled, denied, unsupported, or unavailable.
- Mobile navigation, cards, charts, tables, forms, modals, drawers, and toolbars pass accessibility checks.
- More Actions remains present and continues hiding the data-source/action toolbar until expanded.
- Automated unit, API, isolation, E2E, accessibility, responsive screenshot, and desktop regression suites pass.
- Real-device iOS and Android evidence is attached to the pull request, including confirmation that the `audio/mp4` iOS recording path was exercised on a real device.
- Measured CPU transcription latency for the recommended `faster-whisper` configuration is recorded, with a decision on whether GPU placement is needed.
- Deployment notes document flags, STT model, capacity, monitoring, rollback, and branch/commit SHAs.

---

## 11. Devin implementation instructions

1. The production/merge-base branch is `devin/r-echarts-e2e-validation` (confirmed in the header and validation notes above) — fetch it and confirm the SHA in the PR description; do not spend time re-deriving which branch is production.
2. Search for and reuse current shared layout, card, chart, modal, drawer, tooltip, conversation, authorization, and audit components. For the specific mechanisms called out in the validation notes, reuse them exactly rather than re-deriving equivalents:
   - Request signing: `_sign_payload()` in `platform-api/app/services/ai_intelligence_client.py`.
   - Rate limiting: the rolling-window pattern in `platform-api/app/services/mfa_sms_service.py`.
   - Audit logging: the generic `AuditEvent` table.
   - Per-tenant toggles: boolean columns on `Tenant` (`enforce_2fa`, `allowed_domains_enabled` as precedent).
   - Model artifact staging: the model-vault verification/transfer channel used by `platform-api/app/services/llm_ollama_adapter.py` — but not `OllamaAdapter.install()`/`ollama create` itself, which cannot serve a `faster-whisper` model.
3. Do not replace newer production behavior with implementations found on older branches. Cherry-pick only after comparing the old change with the current component structure.
4. Commit in reviewable phases:
   - responsive tokens and shell
   - shared components, including the consolidated `AskAnythingComposer` (Phase 2)
   - AI surfaces (now just a migration onto the composer, not a parallel rebuild)
   - remaining routes
   - transcription backend/AI adapter
   - tests, documentation, and rollout flags
5. Keep schema/API changes backward compatible during rollout.
6. Include a route-by-route completion matrix, viewport screenshots, real-device voice evidence (including the iOS `audio/mp4` path specifically), test results, migration status, flags, measured CPU transcription latency, and rollback procedure in the PR description.
7. Explicitly state in the PR what happened to `AIPromptBar.tsx`'s existing browser-speech mic button (validation note 2) — migrated or removed, and why.
8. Do not deploy production until staging, privacy, isolation, load, and real-device acceptance criteria pass.
