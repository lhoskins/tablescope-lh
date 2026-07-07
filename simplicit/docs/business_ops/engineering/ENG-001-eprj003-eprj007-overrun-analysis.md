# ENG-001 — Engineering Project Overrun Analysis: EPRJ-003 and EPRJ-007
## Simplicit Demo Company | Engineering / Finance

**Document ID:** ENG-001
**Report Date:** June 30, 2026
**Prepared By:** Melissa Jones, Engineering Analyst / Sandra Rodriguez, Finance Manager
**Reviewed By:** Kevin Davis, Engineering Director / Richard Lewis, CFO
**Distribution:** CEO, COO, CFO, Board Audit Committee
**Classification:** Confidential — Executive Distribution

---

## 1. Purpose and Scope

This report documents the root causes, financial impact, and recovery plans for cost overruns on two active engineering projects:

- **EPRJ-003:** Line 2 Process Optimization ($220K budget; $228K spent as of June 30 = 103.8% consumed)
- **EPRJ-007:** Titanium Alloy Study ($180K budget; $211.6K spent as of June 30 = 117.6% consumed; project still active)

Both projects were initiated with good-faith scope definitions and have experienced scope and cost growth primarily due to interconnected operational circumstances in H1 2026. This report presents a shared root cause analysis and, where appropriate, distinguishes project-specific factors.

---

## 2. Project Summaries

### EPRJ-003 — Line 2 Process Optimization

| Field | Detail |
|---|---|
| Project ID | EPRJ-003 |
| Description | Optimize throughput and reduce scrap rate on Manufacturing Line 2 |
| Type | Process Improvement |
| Lead Engineer | Darnell Washington |
| Start Date | June 1, 2025 |
| Original Planned End | June 30, 2026 |
| Revised Planned End | August 31, 2026 |
| Original Budget | $220,000 |
| Total Spend (June 30) | $228,400 |
| Budget Consumed | 103.8% |
| Projected Final Spend | $238,000 |
| Final Overrun (est.) | $18,000 (+8.2%) |

### EPRJ-007 — Titanium Alloy Study

| Field | Detail |
|---|---|
| Project ID | EPRJ-007 |
| Description | Evaluate alternative titanium alloy compositions for cost reduction and supply chain diversification |
| Type | R&D |
| Lead Engineer | Tobias Brennan |
| Start Date | February 1, 2026 |
| Original Planned End | August 31, 2026 |
| Revised Planned End | October 31, 2026 |
| Original Budget | $180,000 |
| Total Spend (June 30) | $211,600 |
| Budget Consumed | 117.6% |
| Projected Final Spend | $228,000 |
| Final Overrun (est.) | $48,000 (+26.7%) |

---

## 3. Root Cause Analysis

### RCA-1: Scope Creep Driven by Interconnected Events (Common to Both Projects)

The primary root cause shared by EPRJ-003 and EPRJ-007 is that two projects that were independently scoped became operationally linked when the Line 2 scrap rate spike emerged in Q1 2026.

**EPRJ-003 original scope:** Process parameters optimization, fixture redesign, and cycle time analysis for Line 2. This was a well-defined process improvement project.

**EPRJ-007 original scope:** Bench evaluation of 3 alternative titanium alloy compositions against Ti-6Al-4V baseline — a contained R&D study.

**What changed:** The Line 2 scrap investigation (MFG-001) revealed that incoming material specification variance from Cascade Alloys (titanium hardness out of Simplicit's operational sweet spot) was a primary root cause of the scrap increase. This finding:

1. **Expanded EPRJ-003 scope:** Darnell Washington (EPRJ-003 lead) was pulled into the scrap root cause investigation, the supplier corrective action process, and the revision of Line 2 standard work instructions (SWI Rev 3). This was outside the original project scope but was the most appropriate use of Washington's process expertise. An estimated $22K of EPRJ-003 spend relates to this investigation-related work.

2. **Expanded EPRJ-007 scope:** The material sourcing crisis accelerated the urgency of the alloy study, and management added 3 additional alloy variants to the test matrix in March 2026 to evaluate supply chain alternatives. Tobias Brennan's original test matrix was 3 alloys; it expanded to 6. External lab testing costs at OSU Materials Science Engineering increased from $28K (estimated) to $54K (actual) due to the expanded test matrix and rush scheduling premium.

**Assessment:** Both scope expansions were operationally justified and likely saved significantly more in Line 2 scrap and supplier costs than the project overruns themselves. However, they were executed without formal scope change documentation or budget amendment approval — a process failure.

---

### RCA-2: Inadequate Project Governance and Change Control

Simplicit's engineering project governance process (reference POL-013, Change Management Policy) requires a written scope change request and Finance co-approval for scope changes exceeding 10% of original project budget. Neither EPRJ-003 nor EPRJ-007 followed this process.

**EPRJ-003:** Darnell Washington verbally communicated scope changes to Kevin Davis (Engineering Director) in weekly status conversations. No written change request was filed. Davis did not escalate to Finance.

**EPRJ-007:** Tobias Brennan documented the expanded test matrix in his lab notebook and a project file, but did not file a formal change request. When the OSU lab invoice arrived in May ($54K vs. $28K estimate), it was the first time Finance (Sandra Rodriguez) was aware of the scope expansion.

**Contributing factor:** Engineering project status reports were submitted monthly to the Engineering Director but were not reviewed by Finance until the budget was already exceeded. The existing governance process assumed the Engineering Director was the final escalation gate, with no Finance checkpoint at the 75% or 90% budget consumption thresholds.

---

### RCA-3: Resource Conflicts

Both Darnell Washington (EPRJ-003) and Tobias Brennan (EPRJ-007) experienced resource conflicts in Q1–Q2 2026:

- **Washington** is also the Lead Engineer on EPRJ-001 (Next-Gen Aerospace Bracket, $380K project). He was managing two significant projects simultaneously while also being pulled into the Line 2 scrap investigation. This divided attention contributed to less frequent project cost monitoring on EPRJ-003.

- **Brennan** is a relatively recent addition to the team (EPRJ-007 is his first project lead role). He has strong technical capability but limited experience managing external supplier relationships (OSU lab) and estimating external lab costs. The OSU cost overrun was partly a consequence of inexperience in managing academic lab contracts, where scope and pricing are more fluid than with commercial vendors.

---

## 4. Financial Impact

### Direct Project Overrun

| Project | Budget | Projected Final | Overrun | % Over |
|---|---|---|---|---|
| EPRJ-003 | $220,000 | $238,000 | $18,000 | 8.2% |
| EPRJ-007 | $180,000 | $228,000 | $48,000 | 26.7% |
| **Combined** | **$400,000** | **$466,000** | **$66,000** | **16.5%** |

### Context: Value Generated by Scope Expansion

While the overruns are real, the expanded scope generated value exceeding the overrun amounts:

| Value Created | Estimated Value |
|---|---|
| EPRJ-003 scope expansion: SWI Rev 3 enabling L2 scrap rate reduction (partial contribution to $550K annualized savings) | $90–140K (engineering credit) |
| EPRJ-007 expanded alloy study: enables supply chain diversification (RSK-001 mitigation); alternative alloy may reduce material cost 8–12% | $200–350K potential annual savings |
| **Net value created vs. overrun** | **Significantly positive** |

This context does not excuse the governance failure, but it is relevant to the board's assessment of project team accountability.

---

## 5. Recovery Plan

### EPRJ-003

- **Status:** Substantially complete. Line 2 SWI Rev 3 issued. SPC system (CAP-004) installation in progress.
- **Remaining work:** Monitor Line 2 effectiveness through August; document lessons learned.
- **Projected completion:** August 31, 2026 (8 weeks late from original June 30 end date).
- **Remaining spend:** Approximately $9.6K (within remaining contingency after acknowledging overrun).
- **Recovery action:** No additional budget authorization required; project will close within the revised $238K estimate.

### EPRJ-007

- **Status:** 60% complete. Expanded alloy test matrix: 4 of 6 alloys tested. Two remaining alloys (candidate alternatives from Ironside Materials and Sierra Springs) in OSU lab queue.
- **Projected completion:** October 31, 2026.
- **Remaining spend (estimate):** $16,400 (within revised $228K total estimate).
- **Recovery action:** Tobias Brennan to submit weekly cost tracking to Melissa Jones for Finance review. OSU lab contract amendment to be executed with fixed-price scope for remaining tests (Brennan to negotiate with OSU by July 15).

---

## 6. Corrective Actions — Project Governance

To prevent recurrence, the following governance improvements are being implemented effective Q3 2026:

| # | Action | Owner | Effective |
|---|---|---|---|
| G-01 | Finance co-signature required on all Engineering project scope documents ≥$50K | Kevin Davis + Richard Lewis | July 1, 2026 |
| G-02 | Automatic Finance review triggered at 75% and 90% budget consumption (ERP system flag) | Ashley Rodriguez (ERP implementation team) | ERP Phase 2 completion |
| G-03 | Formal written scope change request required for any change adding >5% to project budget; requires Engineering Director + CFO co-approval | Kevin Davis | July 1, 2026 |
| G-04 | Monthly written Engineering project cost status to CFO (separate from narrative status reports) | Kevin Davis | Effective July 2026 |
| G-05 | External vendor (lab, consultant) contracts to be reviewed by Procurement before execution for projects ≥$20K | Sarah Nelson | July 1, 2026 |
| G-06 | Project lead training on cost estimation and change control for new project leads (Tobias Brennan's role profile specifically) | HR / Kevin Davis | Q3 2026 training cycle |

---

## 7. Accountability Summary

| Party | Assessment |
|---|---|
| Darnell Washington (EPRJ-003) | Scope expansion was operationally justified; governance failure (no written change request) is a process compliance issue to address in coaching, not a performance rating issue. Strong technical judgment demonstrated. |
| Tobias Brennan (EPRJ-007) | Scope expansion partially justified; external lab cost estimation was inadequate. As a first project lead, supervision was insufficient. Kevin Davis acknowledges this. Mentoring and training plan to be developed. |
| Kevin Davis (Engineering Director) | Director-level accountability for the absence of governance escalation. Davis has accepted this accountability and has proactively proposed the governance corrections in Section 6. |
| Finance (Sandra Rodriguez) | Finance had no visibility until invoice arrived. New process (G-02, G-04) corrects this. No individual accountability assigned. |

---

*Prepared by: Melissa Jones (Engineering Analysis) / Sandra Rodriguez (Finance)*
*Approved: Kevin Davis (Engineering Director), Richard Lewis (CFO)*
*June 30, 2026*
