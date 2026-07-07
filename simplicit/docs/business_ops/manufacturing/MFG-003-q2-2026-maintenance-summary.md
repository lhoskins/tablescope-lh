# MFG-003 — Q2 2026 Maintenance Performance Summary
## Simplicit Demo Company | Manufacturing / Maintenance

**Report Period:** April 1 – June 30, 2026
**Prepared By:** George Hill, Manufacturing Coordinator (Maintenance Lead)
**Reviewed By:** George Walker, Manufacturing Manager (Plant A) / Christopher Anderson, Manufacturing Manager (Plant B)
**Approved By:** Kimberly Gonzalez, Manufacturing Director
**Date Issued:** July 6, 2026

---

## 1. Executive Summary

Q2 2026 maintenance performance was below expectations. Unplanned maintenance hours increased 34% year-over-year, driven primarily by equipment events on Line 2 associated with the scrap rate issue (harder material + deferred tooling maintenance). Total maintenance cost came in $42K over the Q2 maintenance budget. However, Lines 3 and 4 performed within planned maintenance parameters. MTBF (Mean Time Between Failures) on Line 2 equipment declined significantly and is the focus of the Q3 reliability improvement plan.

---

## 2. Planned vs. Unplanned Maintenance Hours

### Q2 2026 Summary

| Category | Q2 2026 Hours | Q2 2025 Hours | Change | Q2 Budget |
|---|---|---|---|---|
| Planned Preventive Maintenance (PM) | 718 | 724 | (0.8)% | 720 |
| Planned Corrective / Scheduled Repair | 142 | 138 | +2.9% | 140 |
| **Unplanned / Emergency** | **387** | **289** | **+33.9%** | 250 |
| **Total** | **1,247** | **1,151** | **+8.3%** | 1,110 |

**Unplanned maintenance exceeded budget by 137 hours (54.8%).** The overrun is concentrated on Line 2 (see Section 4).

### Monthly Trend — Unplanned Hours

| Month | Unplanned Hours | Notes |
|---|---|---|
| January 2026 | 84 | Normal range |
| February 2026 | 91 | Slightly elevated |
| March 2026 | 118 | L2 CNC 2-A bearing wear; scrap investigation begins |
| April 2026 | 132 | L2 events during investigation containment period |
| May 2026 | 142 | L2 CNC 2-C spindle issue first detected |
| June 2026 | 113 | CNC 2-C bearing replaced; partial recovery |

---

## 3. Maintenance Cost Analysis

| Cost Category | Q2 Budget ($K) | Q2 Actual ($K) | Variance ($K) |
|---|---|---|---|
| Labor (internal technicians) | 188 | 212 | **(24)** |
| External contractors | 45 | 71 | **(26)** |
| Parts and materials | 92 | 98 | (6) |
| Consumables / tooling | 65 | 71 | (6) |
| **Total** | **390** | **452** | **(62)** |

**Labor overrun ($24K):** Driven by overtime for unplanned repairs on Line 2, including the June 12 CNC 2-C bearing failure (48-hour repair requiring 3 technicians, 2 shifts, plus contractor support). Two internal maintenance technicians worked consecutive 12-hour shifts during the repair event.

**External contractor overrun ($26K):** CNC 2-C repair required a Haas Automation field service technician ($18K callout), which was not in the planned maintenance budget. Additionally, a hydraulic system specialist was engaged for a Line 3 cylinder repair in May ($8K).

---

## 4. Equipment Reliability — Line-by-Line

### 4a. MTBF (Mean Time Between Failures) — Hours

| Line | Q2 2026 MTBF | Q1 2026 MTBF | Q2 2025 MTBF | Target |
|---|---|---|---|---|
| L1 — Plant A | 312 hrs | 328 hrs | 341 hrs | 300 hrs |
| L2 — Plant A | **148 hrs** | 218 hrs | 297 hrs | 300 hrs |
| L3 — Plant A | 388 hrs | 372 hrs | 354 hrs | 300 hrs |
| L4 — Plant B | 422 hrs | 408 hrs | 387 hrs | 300 hrs |

**Line 2 MTBF has declined from 297 hours (Q2 2025) to 148 hours (Q2 2026) — a 50% deterioration.** This is the primary reliability concern. The decline correlates with the harder-than-nominal titanium material (higher cutting forces accelerating component wear) and a period of deferred tooling maintenance during peak operator shortage in Q1 2026.

### 4b. MTTR (Mean Time to Repair) — Hours

| Line | Q2 2026 MTTR | Q2 2025 MTTR | Target |
|---|---|---|---|
| L1 | 4.1 hrs | 3.8 hrs | ≤4.0 hrs |
| L2 | **9.2 hrs** | 4.4 hrs | ≤4.0 hrs |
| L3 | 3.4 hrs | 3.7 hrs | ≤4.0 hrs |
| L4 | 3.1 hrs | 3.2 hrs | ≤4.0 hrs |

**Line 2 MTTR of 9.2 hours** reflects the complexity of the CNC bearing failures — these are not quick-fix events and require CNC specialist support. The June CNC 2-C event alone contributed 48 hours of repair time. Excluding that single event, Line 2 MTTR was 5.8 hours — still above target but more reflective of the baseline.

---

## 5. Top Failure Modes — Q2 2026

| Rank | Failure Mode | Count | Lines Affected | Est. Impact (hrs downtime) |
|---|---|---|---|---|
| 1 | CNC spindle/bearing wear (accelerated) | 4 | L2 (3), L1 (1) | 94 |
| 2 | Coolant system (pump, filter, nozzle) | 3 | L1 (2), L3 (1) | 28 |
| 3 | Hydraulic cylinder seal / leakage | 2 | L3 (2) | 22 |
| 4 | Encoder / servo drive fault | 2 | L2 (1), L4 (1) | 14 |
| 5 | Chip conveyor jams / motor | 3 | L2 (2), L3 (1) | 12 |
| Other | Various | 8 | Various | 31 |
| **Total** | | **22** | | **201** |

**Finding:** CNC spindle/bearing wear is the dominant failure mode and is specific to Line 2. This failure mode was essentially absent from Q2 2025 data (0 occurrences). The causal link to harder-than-nominal titanium material (MFG-001) is confirmed.

---

## 6. Preventive Maintenance Compliance

| Line / Area | Q2 PM Tasks Scheduled | Completed On-Time | Deferred | Compliance % |
|---|---|---|---|---|
| Line 1 (Plant A) | 42 | 41 | 1 | 97.6% |
| Line 2 (Plant A) | 48 | 38 | 10 | **79.2%** |
| Line 3 (Plant A) | 39 | 39 | 0 | 100.0% |
| Line 4 (Plant B) | 36 | 35 | 1 | 97.2% |
| Support Systems | 28 | 27 | 1 | 96.4% |
| **Total** | **193** | **180** | **13** | **93.3%** |

**Line 2 PM compliance (79.2%) is below the 95% target.** The 10 deferred PM tasks on Line 2 were deferred in January–February 2026 when operator headcount was reduced due to attrition and maintenance technician time was reallocated to production support. This deferral directly contributed to the spindle wear events in Q2.

**Corrective action:** Manufacturing Director Gonzalez has established a policy that PM tasks on Line 2 cannot be deferred without COO approval. George Walker is responsible for compliance.

---

## 7. Capital vs. Maintenance Decisions

Two equipment items were evaluated for repair-vs.-replace during Q2:

**CNC Cell 2-B (Haas ST-30, 2014):**
- Repair cost incurred (Q2): $38K
- Estimated remaining economic life if maintained: 3–4 years
- Replacement cost estimate: $285K
- Decision: Repair and maintain; continue as-is with more frequent PM intervals (6-month bearing inspection vs. 12-month)

**Line 3 Hydraulic Unit (Bosch Rexroth, 2012):**
- Seal failures in Q2 (2 events)
- Maintenance estimate for rebuild: $22K
- Replacement unit: $68K
- Decision: Rebuild (hydraulic specialist engaged July 2026). If a third failure occurs within 12 months, replace.

---

## 8. Q3 2026 Maintenance Priorities

| Priority | Action | Owner | Target Date |
|---|---|---|---|
| 1 | Proactive inspection and replacement of L2 CNC 2-A and 2-D spindle bearings | George Hill | July 15 |
| 2 | Complete 10 deferred L2 PM tasks from Q2 | George Hill | July 31 |
| 3 | PM interval reduction: L2 CNC spindles from 12-month to 6-month cycle | George Walker | Effective July 1 |
| 4 | Procure spare CNC spindle bearing set for L2 (on-hand inventory) | George Hill / Sarah Nelson | July 31 |
| 5 | Evaluate CMMS (computerized maintenance management system) to prevent PM deferrals | Ashley Rodriguez | Q4 2026 feasibility |
| 6 | Line 3 hydraulic unit rebuild | Contracted specialist | July 2026 |

**Q3 Unplanned Maintenance Budget (revised):** $180K (vs. $125K original). The revision reflects the elevated L2 risk until scrap root cause is fully resolved and material spec is tightened.

---

*Prepared by: George Hill, Manufacturing Coordinator (Maintenance Lead)*
*Approved: Kimberly Gonzalez, Manufacturing Director — July 6, 2026*
