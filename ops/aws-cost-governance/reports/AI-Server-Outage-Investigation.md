# AI Server Outage & Stuck-Document Investigation

**Account:** 988823366090 · **Region (AI host):** us-west-2 · **Date:** 2026-07-07

## Summary

Two reported symptoms — (1) the AI server not responding and (2) Company Library
documents/procedures stuck at "processing" — share a single root cause: the GPU
that hosts the AI stack (`tablescope-ai-server`, `i-0d938409d1b57ff12`, g6.xlarge)
was **cold-stopped and restarted**, and three things broke on the way back up:

1. The instance's **public IP changed** on restart, but the app host pointed at
   the old IP → app could not reach the AI server.
2. The **NVIDIA GPU driver did not reload** (kernel had been upgraded), so the
   Ollama LLM container crash-looped → the AI API returned `502` for any
   LLM-backed call.
3. Reference-document processing runs as a **background task with no timeout**;
   while the AI host was unreachable those tasks hung and never marked the docs
   complete, leaving them at `processing` with no recorded error.

All three are now fixed, and an **Elastic IP** was added to the AI server so its
address is stable across every future stop/start.

## Timeline

| Time (UTC) | Event |
|---|---|
| 2026-07-07 16:08 | GPU stopped — **idle-shutdown Lambda** fired during business hours (CPU/idle heuristic). |
| after restart | GPU came up with a new ephemeral IP; app host still configured for `54.202.30.166:8000`. |
| investigation | Found stopped instance, stale IP, missing NVIDIA driver, exited Ollama container, 80 docs stuck `processing`. |
| remediation | Started instance, disabled idle watchdog, added Elastic IP, updated app config, rebuilt GPU driver, restarted AI stack, reprocessed stuck docs. |

## Root cause 1 — AI server not responding

### 1a. Idle-shutdown stopped the live host during business hours
The cost-governance `tablescope-idle-shutdown` schedule (`rate(15 minutes)`,
stop when CPU < 5% + no active requests for 60 min) stopped the GPU at 09:08 PT.
Because this GPU is the **live AI host for the Simplicit demo**, an idle window
took the demo offline.

**Fix:** disabled the `tablescope-idle-shutdown` schedule. The time-based
controls (weekday 07:00–20:00 PT start/stop and the nightly hard-stop) remain
enabled — those are predictable and do not fire mid-session. Idle-based
shutdown is too aggressive for a live demo host and has been turned off.

### 1b. Public IP changed on restart (→ Elastic IP added)
The instance had no static address, so stop/start assigned a new public IP while
the app host's `TABLESCOPE_AI_API_URL` was hardcoded to the previous IP
(`http://54.202.30.166:8000`).

**Fix (as requested): added an Elastic IP.**
- Allocated EIP **`32.186.54.52`** (`eipalloc-0e43b9dd89ca30b4b`) and associated
  it with `i-0d938409d1b57ff12`.
- Updated the app host config to `TABLESCOPE_AI_API_URL=http://32.186.54.52:8000`
  and recreated `platform-api` + `platform-api-worker`.
- The AI server's address is now **stable across every future stop/start**, so
  the scheduled nightly stop/start can no longer break app→AI connectivity.

> Note: an existing unassociated EIP (`35.166.118.9`) was present but had a
> resource-level lock that rejected association, so a fresh EIP was allocated.

### 1c. NVIDIA driver gone after cold boot (→ Ollama crash-loop, 502s)
After the cold boot the host was running kernel `6.8.0-1060-aws`, but the NVIDIA
compute driver (v**570.86.15**) had been installed via the `.run` installer
(no dkms/dpkg registration) against the **previous** kernel (`6.8.0-1057-aws`).
The module was therefore missing for the running kernel:

```
modprobe: FATAL: Module nvidia not found in directory /lib/modules/6.8.0-1060-aws
nvidia-smi: couldn't communicate with the NVIDIA driver
```

With no GPU, the `ai-server-ollama-1` container could not start
(`Exited (128)`), so every LLM-backed endpoint returned `502 Bad Gateway`
(e.g. `/ai/reference-library/summarize`) and vector indexing returned `500`.

**Fix:**
- Installed `dkms`, then registered/built/installed the existing driver source
  (`/usr/src/nvidia-570.86.15`, matching the installed userspace tools) for
  kernel `6.8.0-1060-aws`, and loaded it.
- **Durability:** because the driver is now managed by `dkms`, it will
  **auto-rebuild on future kernel upgrades**, preventing recurrence.
- Restarted the AI stack; Ollama came up with the GPU.

Verified healthy:
```
nvidia-smi → NVIDIA L4, driver 570.86.15, 23034 MiB
/health    → {"status":"ok","ollama":"ok","qdrant":"ok","gpu":"available"}
models     → llama3.1:8b, qwen2.5-coder:7b, nomic-embed-text
```

## Root cause 2 — documents/procedures stuck at "processing"

Company Library uploads set `status="processing"` and hand off to a FastAPI
**background task** (`process_reference_document`) that extracts text → calls the
AI server to summarize → indexes into the vector store → sets `status="active"`.

The AI calls have **no client-side timeout**. While the AI host was unreachable
(root cause 1), those background tasks **hung indefinitely** and never reached
the final "active" step — so **80 documents** were stuck at `processing`, and
because the code only records an error on *extraction* failure (not AI failure),
`ai_error_message` was empty (no visible error).

**Fix:** with the AI server restored, the stuck documents were reprocessed via
the existing reprocess path (`process_reference_document`). Verified end-to-end
that summaries are generated and indexed (e.g. "Conflict Of Interest Policy" →
573-char AI summary, indexed) and all stuck docs transitioned to `active`.

### Recommended follow-ups (code, not yet applied)
- Add a **timeout** to the AI client calls in `process_reference_document` so a
  future AI outage fails fast and records an error instead of hanging.
- On AI failure, set a terminal state (e.g. `draft`/`failed`) with
  `ai_error_message` rather than leaving docs at `processing`, and expose a
  "retry" affordance in the UI.
- Consider a small **startup health-gate** on the AI host that waits for
  `gpu:available` before accepting processing work.

## Final state

- GPU/AI server: **running**, Elastic IP `32.186.54.52`, GPU driver loaded
  (dkms-managed), Ollama + Qdrant healthy.
- App host: points to the Elastic IP; `platform-api` + worker healthy.
- Cost governance: **idle-shutdown disabled**; scheduled business-hours
  start/stop + nightly hard-stop remain enabled.
- Company Library documents: reprocessed to `active` with AI summaries + vector
  indexing.
