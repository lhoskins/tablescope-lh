# Conversational analytics turn classification

This reference is injected into the `/ai/intelligence/conversation-turn`
classifier prompt. It defines the intent taxonomy, the decision rules, and
illustrative examples. It must stay generic: never reference a real tenant's
tables, columns, or business domain here — the model receives the real,
authorized conversation state (result columns, prior SQL, current chart)
separately on every call.

## Intents (choose exactly one)

- new_analysis: a brand-new question that needs new data.
- query_change: changes WHAT data is computed — filters, date ranges, different
  metrics/dimensions, grouping, comparisons. Requires new SQL.
- chart_change: changes ONLY how the EXISTING result is presented — chart type
  or subtype (horizontal/stacked/grouped bars, donut, line, pie, scatter,
  table), which existing columns are plotted as label/values, sorting the
  display, data labels, legend, or title.
- explain: the user asks how the current result was computed or to see the SQL.
- clarification: the message is too vague to act on at all.

## Decision rules

1. chart_change and explain are only valid when has_prior_result is true;
   otherwise prefer new_analysis.
2. Torn between query_change and chart_change? Ask: can the request be
   satisfied by re-drawing the SAME rows and columns? If yes it is
   chart_change; if it needs different rows, columns, filters, or aggregation
   it is query_change.
3. Phrases like "run this query as/using X", "show it as X", "switch to X",
   "make it X", "display as X", "as a X", "in a X", "with a X" where X is a
   chart style are chart_change when there is a prior result — the user wants
   the same data re-presented.
4. Populate "chart" for EVERY chart_change, and ALSO for new_analysis or
   query_change when the user mentions any chart style in the same message.
   The style can appear anywhere in the message, including after data
   constraints. If no chart style is mentioned, return chart as an empty
   object {}. Use null for any chart field the user did not ask to change.
5. When a chart style is mentioned, you MUST set type (and subtype when one
   applies). Plain "bar chart" or "vertical bar": type=bar, subtype=null.
   "horizontal bar", "as horizontal", "make it horizontal": type=bar,
   subtype=horizontal_bar. "donut"/"doughnut": type=pie, subtype=donut.
   "area": type=line, subtype=stacked_area. "bubble": type=scatter,
   subtype=bubble.
6. labelColumn and valueColumns must come from result_columns. For
   new_analysis and query_change, leave them null — the platform derives them
   from the executed result. For chart_change, if the user names a column that
   does not exist, still return chart_change with the requested name — the
   platform reports it to the user.
7. Output data_question for new_analysis and query_change: rewrite THIS user
   message as a focused data question with all chart/presentation wording
   removed. The SQL generator receives ONLY the data_question, so it must
   carry the user's actual subject and constraints, in the user's own terms.
   Never copy wording from the examples below — they are illustrative only and
   describe other, fictional datasets. For chart_change and explain, set
   data_question to null.
8. Do not fabricate chart patches to force a pass. When the intent is truly
   unclear, prefer clarification with a lower confidence.
9. Vague adjectives like "fancier", "nicer", "prettier", or "make it look better"
   without a specific chart type or change are clarification, not chart_change.

## Examples (fictional data — never copy their wording into your output)

Message: "Top suppliers by spend as a horizontal bar chart" ->
{"intent": "new_analysis", "chart": {"type": "bar", "subtype": "horizontal_bar",
"labelColumn": null, "valueColumns": null, "sort": null, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": "Total spend by supplier, highest first",
"confidence": 0.95, "reason": "New data question with an explicit horizontal bar style."}

Message: "show open tickets by priority in a donut chart" ->
{"intent": "new_analysis", "chart": {"type": "pie", "subtype": "donut",
"labelColumn": null, "valueColumns": null, "sort": null, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": "Count of open tickets grouped by priority",
"confidence": 0.95, "reason": "New question requesting a donut chart."}

Message: "monthly revenue for the last year" ->
{"intent": "new_analysis", "chart": {},
"data_question": "Monthly revenue for the last 12 months",
"confidence": 0.9, "reason": "New data question, no chart style mentioned."}

Message: "run this query using horizontal bar format" (prior result) ->
{"intent": "chart_change", "chart": {"type": "bar", "subtype": "horizontal_bar",
"labelColumn": null, "valueColumns": null, "sort": null, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": null, "confidence": 0.95, "reason": "Same data re-presented as horizontal bars."}

Message: "make it a donut" (prior result) ->
{"intent": "chart_change", "chart": {"type": "pie", "subtype": "donut",
"labelColumn": null, "valueColumns": null, "sort": null, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": null, "confidence": 0.95, "reason": "Presentation-only switch to a donut."}

Message: "that looks wrong, I wanted it horizontal" (prior result) ->
{"intent": "chart_change", "chart": {"type": "bar", "subtype": "horizontal_bar",
"labelColumn": null, "valueColumns": null, "sort": null, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": null, "confidence": 0.9, "reason": "Complaint plus an explicit horizontal request; keep the data, change presentation."}

Message: "only include 2024" (prior result) ->
{"intent": "query_change", "chart": {},
"data_question": "Filter the previous result to 2024 only",
"confidence": 0.9, "reason": "Needs a different filter, so new SQL."}

Message: "sort it highest to lowest" (prior result) ->
{"intent": "chart_change", "chart": {"type": null, "subtype": null,
"labelColumn": null, "valueColumns": null,
"sort": {"column": "value", "direction": "desc"}, "dataLabels": null,
"legendVisible": null, "title": null},
"data_question": null, "confidence": 0.9, "reason": "Display sort of the same rows."}

Message: "why is the third bar so high?" (prior result) ->
{"intent": "explain", "chart": {}, "data_question": null,
"confidence": 0.85, "reason": "Asks how the current result came to be."}

Message: "make it fancier" (prior result) ->
{"intent": "clarification", "chart": {}, "data_question": null,
"confidence": 0.8, "reason": "Vague presentation request with no specific chart type."}
