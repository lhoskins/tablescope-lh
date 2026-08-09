# Insight card matching

This reference is injected into the `/ai/intelligence/select-insight-card`
prompt. It governs one decision only: given a question the platform could not
answer with a fresh query, and a short list of already-computed Insight Cards
from the same project, which single card (if any) most directly answers the
question. It must stay generic: never reference a real tenant's tables,
columns, or business domain — the candidate cards themselves carry the real,
authorized content on every call.

## What this is not

This is not insight generation and not SQL generation. Do not propose a
query, do not invent findings, and do not synthesize an answer from multiple
cards. Pick at most one existing card exactly as given, or decline.

## Decision rules

1. A card's own title is the strongest signal that it is about the question's
   topic. A card titled directly after the subject of the question ("Material
   Cost Over Time Indicates Potential Risks" for "why is material cost
   increasing") is a far stronger match than a card that only mentions the
   same words in passing within a longer summary about a different subject
   ("Vendor Spend Trends Indicate Potential Cost Optimization Opportunities"
   merely touching on cost).
2. Prefer specificity over incidental overlap. A card sharing one word with
   the question is not evidence of a match by itself — judge whether the card
   is actually about what was asked, not just whether it contains matching
   vocabulary.
3. Decline (return no card) when no candidate is genuinely about the
   question's subject. A vague, tangential, or partial match is worse than
   admitting nothing existing answers it — the platform falls back to a
   different path when you decline, so declining is always safe.
4. Never pick a card because it is the only one provided. "Best of a bad set"
   is still a decline if none of them are actually on-topic.
5. Give a one-sentence reason either way, grounded in the specific card
   title/summary text you compared against the question — never a generic
   restatement like "this card is relevant."

## Examples (fictional data — never copy their wording into your output)

Question: "why is material cost increasing?"
Candidates:
- id=c1 title="Material Cost Over Time Indicates Potential Risks" summary="Material cost has risen month over month; the trend correlates with a known supplier issue."
- id=c2 title="Vendor Spend Trends Indicate Potential Cost Optimization Opportunities" summary="Category-level vendor spend trends, including material and indirect cost categories, tracked over the last four quarters."
->
{"insightId": "c1", "confidence": 0.9, "reason": "c1's own title names material cost directly and its summary describes the same rising trend; c2 is about vendor spend broadly and only mentions material cost in passing."}

Question: "what is driving the drop in on-time delivery?"
Candidates:
- id=c1 title="Warehouse Utilization Nearing Capacity" summary="Storage utilization across three warehouses is above 85%."
- id=c2 title="Q2 Headcount Summary" summary="Current headcount by department for Q2."
->
{"insightId": null, "confidence": 0.0, "reason": "Neither candidate is about on-time delivery or its drivers; declining rather than forcing an unrelated match."}

Question: "show me backup jobs by system"
Candidates:
- id=c1 title="Backup Jobs by System: Potential Backup Job Overload" summary="Backup job counts grouped by system, flagging systems above the expected job count."
->
{"insightId": "c1", "confidence": 0.85, "reason": "c1 is titled and scoped exactly to backup jobs by system, the same grouping the question asks for."}
