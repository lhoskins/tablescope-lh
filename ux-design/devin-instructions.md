# Working on the UX prototype — instructions for Devin

**File:** `prototype-ux.html` (repo root — do not move it, other docs link to it)
**Branch context:** authored against `UX-design-02`; push your changes to whatever branch you're working on for this task as usual.

## What this file is

A static, no-backend click-through prototype. It has its own screen switcher
(`showScreen(n, btn)`, defined near the bottom `<script>` block) — leave that
function and the `.screen` / `.screen.active` pattern alone unless the task is
specifically to change navigation structure.

## The audit layer — do not remove

There is a second `<script>` block right before `</body>`, clearly delimited
with an HTML comment starting `AUDIT LAYER — added by Claude`. It is a
read-only scanner: on load it finds every button/link/clickable element and
checks two things — does it have an `onclick`, and does it have a
`data-intent` attribute. Nothing about it changes app behavior. Leave it in
place across edits; it's how Ephraim reviews what you've wired vs. what's
still undecided.

## When you add or change a clickable element

If it should trigger real behavior in this prototype (switch screens, open a
modal, etc.), wire it the way the existing code does (`onclick="showScreen(...)"`
or equivalent) — don't introduce a different navigation convention.

If it's a button/element whose destination or behavior is part of the design
but isn't meaningfully simulatable here (e.g. it should eventually hit a real
API, or open a screen that doesn't exist yet as a prototype), leave it
unwired but add a `data-intent` attribute describing what it's supposed to
do in plain language, e.g.:

```html
<button class="nav-card" data-intent="Opens the Project Detail screen (not built in this prototype)">
```

That note is what shows up in the audit panel and gets exported — it's the
bridge between "this is just a mockup" and an actual spec.

## Workflow

1. Ephraim tells you which screen(s)/button(s) to change, usually from a
   screenshot with markup or notes.
2. Edit `prototype-ux.html` directly, following the two rules above.
3. Commit and push as usual. He pulls your branch locally, where a live-reload
   server is watching this file — your change shows up in his browser
   automatically once he pulls, no build step.

---

## Update — real UI is now the working surface (supersedes the section above for implementation)

`prototype-ux.html` was the early flow-sketch stage. For actual implementation,
edit the real app directly:

- **Pages:** `web-ui/app/**` (Next.js App Router — one folder per route)
- **Shared components:** `web-ui/components/**`
- **Data hooks:** `web-ui/lib/ui/use-project-data/**` and `web-ui/lib/ui/use-shell-data.ts`

### The local preview mock layer — read before touching data-fetching code

Ephraim previews your changes locally without a running backend, using
`web-ui/lib/dev-mock/mock-api.ts`. It's activated only by his local,
gitignored `.env.local` (`NEXT_PUBLIC_MOCK_API=1`) — it does not run in CI,
staging, or production, and you should never make it default-on or commit an
`.env.local`.

**If your change adds or uses a new `/api/...` call** that isn't already in
`mock-api.ts`'s `routes` array, add a matching mock route there in the same
PR — a `respond()` returning plausible fake data, following the existing
entries' pattern. This is what lets him actually see the screen you built,
not just the code. If a call is too complex to fake reasonably, leave it
unmocked and say so in the PR description — he knows those spots will show
empty/error states until real data exists.

### Branch

Base new work on `UX-design-02` (repo: `vitruvity33/tablescope`). Push to
your own branch (`devin/<short-description>`); he pulls it locally with
`ux-design/pull-latest.sh <your-branch>` to review, then opens a PR back
into **`UX-design-02-updates`** (not `UX-design-02` directly) once he's
happy with it. `UX-design-02-updates` is a buffer branch for reviewing a
batch of UI changes before they land on `UX-design-02` — target your PR
there every time unless told otherwise.
