from __future__ import annotations

import random

from ._common import _SYNTHETIC
from .dimensions import Dimensions
from .io_utils import Registry


# ── Executive reviews ──────────────────────────────────────────────────────
def _executive_reviews(reg: Registry, dims: Dimensions, rng: random.Random) -> None:
    name = dims.spec.display_name
    sc = dims.scenarios
    for m in range(1, 8):  # 2026-01 .. 2026-07
        period = f"2026-{m:02d}"
        rev = rng.uniform(3.8, 4.6)
        gm = rng.uniform(24, 30)
        body = f"""# {name} — Executive Monthly Review ({period})

{_SYNTHETIC}
**Period:** {period}
**Prepared for:** Executive Leadership Team
**Prepared by:** Office of the CFO

## Executive Summary
{name} delivered revenue of ${rev:.1f}M in {period} at a gross margin of
{gm:.1f}%. Operating performance was stable, with three watch items requiring
leadership attention: rising material costs on program {sc.material_cost_program},
scrap creep at work center {sc.scrap_work_center} ({sc.scrap_site}), and NRE
overrun on projects {', '.join(sc.overrun_projects)}.

## Financial Performance
- Revenue: ${rev:.1f}M (budget ${rev * rng.uniform(0.97, 1.03):.1f}M)
- Gross Margin: {gm:.1f}%
- Operating Margin: {rng.uniform(8, 13):.1f}%
- Budget vs Actual: unfavorable material variance concentrated on {sc.material_cost_program}.

## Forecast Changes
Full-year forecast revised for material inflation and the {sc.slipping_customer}
opportunity slippage in the sales pipeline.

## Manufacturing
Throughput on plan; scrap rate elevated at {sc.scrap_work_center} ({sc.scrap_site}).
Containment underway (see Manufacturing scrap investigation report).

## Engineering
NRE overrun watchlist flags {', '.join(sc.overrun_projects)}; rebaseline requested.

## Sales
Pipeline healthy overall; slippage from {sc.slipping_customer} opportunities.
Backlog coverage remains above target.

## HR
Attrition elevated among {sc.attrition_job_class} at {sc.attrition_site};
retention actions in progress.

## Quality
Supplier defect trend from {sc.defect_supplier_name} driving nonconformances;
CAPA open.

## IT / Security
Access-request turnaround elevated for new hires (onboarding bottleneck).

## Top Risks and Mitigations
1. Material cost inflation ({sc.material_cost_program}) — resource re-sourcing.
2. Scrap creep ({sc.scrap_work_center}) — process containment + PM.
3. NRE overrun ({', '.join(sc.overrun_projects)}) — rebaseline & scope control.

## Decisions Needed
- Approve re-sourcing plan for {sc.material_cost_program}.
- Approve retention package for {sc.attrition_job_class} at {sc.attrition_site}.

## Action Items
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Contain scrap at {sc.scrap_work_center} | VP Operations | {period}-28 | Open |
| Re-source material for {sc.material_cost_program} | Procurement | {period}-28 | Open |
| Rebaseline NRE {', '.join(sc.overrun_projects)} | Engineering | {period}-28 | In Progress |
| {sc.defect_supplier_name} CAPA closure | Quality | {period}-28 | Open |
"""
        reg.write_text(
            f"docs/executive/monthly_reviews/{period}_executive_monthly_review.md",
            body, department="Executive", project="Executive",
            artifact_type="Monthly Review",
            tags=["executive", "monthly-review", period],
            description=f"Executive monthly review {period}.")

    for q in ["Q1", "Q2"]:
        period = f"2026-{q}"
        body = f"""# {name} — Executive Quarterly Review ({period})

{_SYNTHETIC}
**Period:** {period}
**Prepared for:** Board of Directors

## Executive Summary
{name} closed {period} with solid demand and stable margins, offset by three
operational headwinds: material inflation on {sc.material_cost_program}, scrap
creep at {sc.scrap_work_center}, and NRE overrun on {', '.join(sc.overrun_projects)}.

## Financial Results
- Quarterly revenue: ${rng.uniform(11, 15):.1f}M
- Gross margin: {rng.uniform(25, 30):.1f}%
- Book-to-bill: {rng.uniform(0.95, 1.15):.2f}

## Budget vs Actual and Forecast
Unfavorable variance driven by material and NRE; forecast rebaselined.

## Operational Highlights
- Manufacturing: scrap containment at {sc.scrap_site}.
- Quality: {sc.defect_supplier_name} corrective action in progress.
- HR: {sc.attrition_job_class} attrition at {sc.attrition_site}.
- Sales: {sc.slipping_customer} slippage; backlog coverage healthy.

## Top Risks
Material inflation, scrap creep, NRE overrun, critical-role attrition, supplier
defect trend.

## Strategic Initiatives
Operational Excellence and Supplier Consolidation prioritized for the next quarter.

## Decisions and Action Items
| Action | Owner | Due | Status |
| --- | --- | --- | --- |
| Approve re-sourcing for {sc.material_cost_program} | CFO | {period} | Open |
| Fund automation at {sc.scrap_site} | COO | {period} | Open |
| Rebaseline NRE {', '.join(sc.overrun_projects)} | CTO | {period} | In Progress |
"""
        reg.write_text(
            f"docs/executive/quarterly_reviews/{period}_executive_quarterly_review.md",
            body, department="Executive", project="Executive",
            artifact_type="Quarterly Review",
            tags=["executive", "qbr", period.lower()],
            description=f"Executive quarterly review {period}.")


