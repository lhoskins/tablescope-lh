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

1. **Do NOT rely on the card title.** Titles are marketing-style labels and
can be misleading. The strongest signal is the card's actual **chart data
shape**: the `chart_signature`, the `series` names, and the `trend` direction
computed from the data points.
2. A card answers the question only when its chart series and trend directly
match the question's subject and direction. "Why is material cost increasing?"
requires a card whose series is named `MaterialCosts` (or an unambiguous
synonym like `AveragePrice`/`DirectMaterial`) and whose trend is `rising`. A
card whose series is `ScrapRate` is not a match, even if the title contains the
word "material" or "scrap".
3. Prefer specificity over incidental overlap. A card sharing one word with
the question is not evidence of a match by itself — judge whether the card's
chart is actually about what was asked.
4. Decline (return no card) when no candidate's chart series and trend genuinely
match the question's subject and direction. A vague, tangential, or partial
match is worse than admitting nothing existing answers it.
5. Never pick a card because it is the only one provided. "Best of a bad set"
is still a decline if none of them are actually on-topic.
6. Give a one-sentence reason either way, grounded in the specific
`series`/`trend` you compared against the question — never a generic
restatement like "this card is relevant."

## Examples (fictional data — never copy their wording into your output)

Question: "why is material cost increasing?"
Candidates:
- id=c1 title="Rising Material Costs Outpacing Declining Scrap Rates" chart_signature="combo chart; x=Period; y=MaterialCosts; y2=ScrapRate" series="MaterialCosts, ScrapRate" trend="MaterialCosts rising, ScrapRate falling" summary="Material costs are increasing while scrap rates are decreasing, indicating a potential risk to profitability."
- id=c2 title="Scrap Rate Trend Indicates Quality Control Issues" chart_signature="line chart; x=Period; y=ScrapRate" series="ScrapRate" trend="ScrapRate rising" summary="Scrap rate in June 2026 is 105.10%, indicating significant quality control issues."
->
{"insightId": "c1", "confidence": 0.92, "reason": "c1's series MaterialCosts has a rising trend, which directly matches the question's subject and direction; c2 is only about ScrapRate."}

Question: "what is driving the drop in on-time delivery?"
Candidates:
- id=c1 title="Warehouse Utilization Nearing Capacity" chart_signature="line chart; x=Period; y=Utilization" series="Utilization" trend="Utilization rising" summary="Storage utilization across three warehouses is above 85%."
- id=c2 title="Q2 Headcount Summary" chart_signature="bar chart; x=Department; y=Headcount" series="Headcount" trend="Headcount stable" summary="Current headcount by department for Q2."
->
{"insightId": null, "confidence": 0.0, "reason": "Neither candidate's series is about on-time delivery or its drivers; declining rather than forcing an unrelated match."}

Question: "show me backup jobs by system"
Candidates:
- id=c1 title="Backup Jobs by System: Potential Backup Job Overload" chart_signature="bar chart; x=System; y=JobCount" series="JobCount" trend="JobCount stable" summary="Backup job counts grouped by system, flagging systems above the expected job count."
->
{"insightId": "c1", "confidence": 0.88, "reason": "c1's series JobCount by System matches the question's requested grouping and subject."}
