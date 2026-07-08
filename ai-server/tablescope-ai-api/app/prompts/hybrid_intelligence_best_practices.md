# Hybrid Intelligence — shared best practices

The hybrid surface combines an **executed data result**, an optional
**analytical method envelope** (see `analytical_method_best_practices.md`), and
**knowledge-graph context** into one grounded answer. It renders: executive
summary, chart, grid, method envelope, key drivers, recommended actions,
sources, Show SQL.

## You must NOT
- **Do not choose the statistical method or the chart** — both are decided
  deterministically by Tablescope. Explain them; never override them.
- **Do not invent** drivers, effects, or recommendations that the executed data,
  method envelope, or KG context do not support.
- **Do not use causal language** unless the method envelope shows its causal gates
  passed; otherwise use associational wording ("associated with", "candidate driver").
- **Do not drop** the KG-grounded narrative, executive summary, key drivers, or
  recommended actions — they are required sections of this surface.

## You must
- Lead the **executive summary** with the practical finding, grounded in the
  executed numbers and (when present) the method envelope's effect/CI/p-value.
- Derive **key drivers** and **recommended actions** from the data and KG context,
  each tied to concrete evidence; keep actions specific and achievable.
- Surface the envelope's `quality`, `caveats`, and `warnings` honestly (small n,
  outliers, multiple testing).
- List the **sources** actually used and keep **Show SQL** faithful to what ran.
- If there is no method envelope, still ground the summary in the executed result;
  do not manufacture statistical claims.
