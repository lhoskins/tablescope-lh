# MFG-001 — Line 2 Scrap Rate Increase: Root Cause Investigation Report
## Simplicit Demo Company | Manufacturing / Quality

**Document ID:** MFG-001
**Investigation Initiated:** March 28, 2026
**Report Date:** June 5, 2026
**Prepared By:** Ronald Carter, Manufacturing Analyst / Charles Anderson, Manufacturing Analyst
**Reviewed By:** Kimberly Gonzalez, Manufacturing Director / Jessica Robinson, Quality Director
**Approved By:** Susan Moore, COO
**Classification:** Internal — Cross-functional Distribution

---

## 1. Background and Problem Statement

Line 2 (Plant A, Columbus HQ) is a high-throughput precision turning and milling line producing primarily titanium and specialty steel components for Aerospace and Defense customers. Line 2 runs two shifts (6:00 AM–2:30 PM and 2:30 PM–11:00 PM) and historically accounts for approximately 28% of Plant A's total output.

**Trigger Event:** During the week of March 17–21, 2026, the Line 2 First Pass Yield (FPY) dropped to 91.4%, triggering an alert under PROC-QA-001 (nonconforming material procedure). The Quality team flagged 14 scrapped parts in a single shift — 3.5× the typical daily scrap count.

**Baseline vs. Observed Scrap Rate:**

| Period | Line 2 Scrap Rate | Company Target |
|---|---|---|
| Q4 2025 average | 2.1% | 2.5% |
| January 2026 | 2.4% | 2.5% |
| February 2026 | 2.7% | 2.5% |
| March 2026 | 3.9% | 2.5% |
| April 2026 | 4.4% | 2.5% |
| May 2026 | 4.8% | 2.5% |
| June 2026 (to date) | 3.6% | 2.5% |

The scrap rate increased from a baseline of 2.1% (Q4 2025) to a peak of 4.8% in May 2026 — a 129% increase. At the May peak, Line 2 was generating approximately $85K in scrap cost per month, compared to a baseline of approximately $37K.

---

## 2. Investigation Team

| Member | Role | Department |
|---|---|---|
| Ronald Carter | Lead Investigator | Manufacturing Analysis |
| Charles Anderson | Process Engineer | Manufacturing |
| Jessica Robinson | Quality Director | Quality |
| Michael Miller | Quality Manager | Quality |
| Darnell Washington | Lead Engineer (EPRJ-003) | Engineering |
| Sarah Nelson | Procurement Director | Procurement |
| [Cascade Alloys Rep] | Supplier Representative | External — Cascade Alloys (SUP003) |

---

## 3. Investigation Methodology

The investigation followed an 8D structured problem-solving framework:

- **D1:** Team established (March 28)
- **D2:** Problem description and data collection (March 28 – April 5)
- **D3:** Interim containment actions (April 5)
- **D4:** Root cause analysis (April 5 – May 10)
- **D5–D8:** Corrective actions, verification, and permanent control (May–ongoing)

Data sources reviewed:
- Work order records for Line 2 (January–May 2026): 847 work orders analyzed
- NCR log: 22 Line 2 NCRs in Q1–Q2 2026
- Incoming inspection records: Cascade Alloys lots received January–April 2026
- Maintenance records: Preventive maintenance log, CNC machine calibration history
- Operator shift logs: March–May 2026
- Material certifications (certificates of conformance): 14 Cascade Alloys lots

---

## 4. Interim Containment Actions (D3)

The following containment actions were implemented April 5, 2026 pending root cause determination:

1. **100% incoming inspection** of all Cascade Alloys titanium rod stock prior to release to Line 2 (Quality-hold tag required).
2. **Hold on affected inventory:** Approximately 2,400 lbs of titanium rod stock from Cascade Alloys lots received March 2–28, 2026 placed on quality hold.
3. **Operator notification and enhanced visual inspection** at Line 2 first operation (turning) — supervisors instructed to halt and report if tool wear is abnormal.
4. **Temporary reduction in batch sizes** on Line 2 titanium runs from 50 to 25 pieces, to limit scrap exposure per production run.

Containment effectiveness: Scrap rate declined slightly in April (4.4% vs. March 3.9% trend) but did not recover to baseline, indicating root cause not fully addressed by containment alone.

---

## 5. Root Cause Analysis (D4)

### 5a. Fishbone / Ishikawa Analysis

Potential causes were explored across six dimensions:

| Category | Potential Causes Investigated | Finding |
|---|---|---|
| **Material** | Incoming hardness variance, surface condition, dimensional tolerance | **Confirmed contributing cause** |
| **Machine** | CNC tool wear rate, chuck calibration, spindle runout | **Confirmed contributing cause** |
| **Method** | Cutting speed/feed parameters, coolant application | Partially contributing |
| **Measurement** | Gauge calibration, operator measurement technique | Not a primary cause |
| **Man** | Operator experience (attrition-related), training currency | Secondary contributing cause |
| **Environment** | Temperature variation in Plant A | Not a cause |

### 5b. Root Cause Findings

**Root Cause 1 (Primary) — Incoming Material Specification Variance: Cascade Alloys Titanium Rod Stock**

Material certificates of conformance (CoC) analysis revealed that 9 of 14 Cascade Alloys lots received between January 15 and April 2, 2026 showed hardness values in the upper tail of the Ti-6Al-4V hardness specification (44–46 HRC vs. Simplicit's nominal 38–42 HRC). While technically within the broader ASTM specification, these lots are at the edge of Simplicit's internal working tolerance for the Line 2 turning operations.

The higher hardness material:
- Increases tool wear rate by approximately 35–45% compared to nominal hardness stock
- Requires different cutting parameters (lower feed rate, reduced depth of cut) that were not reflected in the Line 2 standard work instructions
- Produces increased surface irregularity during finish turning that results in dimensional nonconformances

This finding was validated through controlled machining trials (April 22–25, 2026) at two hardness levels: nominal (38–40 HRC) lots produced 2.1% scrap; upper-tail hardness (44–46 HRC) lots produced 4.6% scrap under identical Line 2 parameters.

**Root Cause 2 (Contributing) — CNC Machine Tool Management: Spindle B Wear**

Maintenance records reviewed by Charles Anderson revealed that the planned tool change on Line 2 Spindle B (CNC Cell 2-B, Haas ST-30) was overdue by 32 days at the time the scrap rate spike began. The tool change had been deferred due to the operator workload constraints associated with H1 workforce turnover. An overdue tool change combined with harder-than-nominal material created a compounding tool degradation effect.

CNC Cell 2-B was inspected April 8, 2026. Tool wear was classified as "excessive" by the maintenance technician. Replacement executed April 10.

**Root Cause 3 (Contributing) — Operator Knowledge Gap**

The Line 2 workforce experienced 11 involuntary knowledge exits (attrition) in Q4 2025 and Q1 2026. The standard work instructions (SWI) for Line 2 titanium turning do not explicitly specify that incoming hardness variation requires parameter adjustment. Experienced operators historically applied informal judgment; newer operators are following the SWI exactly, without the contextual knowledge to adjust for material variation.

---

## 6. Corrective and Preventive Actions (D5–D8)

### Immediate Corrective Actions (Completed or In Progress)

| # | Action | Owner | Due | Status |
|---|---|---|---|---|
| CA-01 | Replace tooling on CNC Cell 2-B | Charles Anderson | April 10 | Complete |
| CA-02 | Issue Supplier Corrective Action Request (SCAR) to Cascade Alloys (SUP003) | Jessica Robinson | April 8 | Complete — 8D in process (QA-002) |
| CA-03 | Revise Line 2 SWI to include material hardness check and parameter adjustment table | Darnell Washington (EPRJ-003) | May 31 | Complete (SWI Rev 3 issued May 28) |
| CA-04 | Implement real-time SPC chart for incoming titanium hardness (CAP-004) | Kevin Davis / Ashley Rodriguez | June 30 | In Progress — SPC hardware installed; software calibration ongoing |
| CA-05 | Revise incoming inspection criteria to include hardness testing for all Cascade Alloys titanium lots | Michael Miller | April 15 | Complete |
| CA-06 | Conduct operator cross-training on material-parameter relationship for Line 2 titanium | Kimberly Gonzalez | June 15 | Complete (12 operators trained) |

### Systemic / Long-Term Actions

| # | Action | Owner | Due | Status |
|---|---|---|---|---|
| CA-07 | Qualify secondary titanium supplier (Ironside Materials, SUP009) | Sarah Nelson | Q4 2026 | In Progress |
| CA-08 | Revise supplier material specification to tighten incoming hardness range from ASTM-broad to Simplicit-specific 38–42 HRC | Darnell Washington / Sarah Nelson | August 31 | Drafted |
| CA-09 | Implement PM scheduling tool to prevent deferred tool changes (linked to ERP CAD Integration project) | Ashley Rodriguez | Q1 2027 | Planning |
| CA-10 | Document and formalize Line 2 operator tacit knowledge in operator knowledge base | Charles Anderson / HR | September 30 | In Progress |

---

## 7. Effectiveness Verification

**Metric:** Line 2 scrap rate target: return to ≤2.5% by September 30, 2026.

**Current Status (June 2026):** Scrap rate has declined from 4.8% peak (May) to 3.6% (June to date). The decline is attributable to:
- Implementation of corrective cutting parameters (CA-03)
- 100% incoming inspection filtering out high-hardness lots before they reach the line
- Tool change on CNC Cell 2-B

**Remaining gap:** 3.6% vs. 2.5% target. The remaining gap is expected to close as: (a) the SPC real-time monitoring system (CA-04) goes fully live, enabling dynamic parameter adjustment; and (b) incoming material quality from Cascade Alloys normalizes under the new tighter spec (CA-08).

**Verification checkpoints:**
- July 31, 2026: Review scrap rate; target ≤3.2%
- August 31, 2026: Target ≤2.8%
- September 30, 2026: Target ≤2.5% (gate for closure of investigation)

---

## 8. Financial Impact Assessment

| Category | Q1 2026 | Q2 2026 | Total H1 |
|---|---|---|---|
| Direct scrap material cost | $67K | $182K | $249K |
| Rework labor | $24K | $58K | $82K |
| 100% inspection premium | — | $22K | $22K |
| Downtime during investigation | $15K | $8K | $23K |
| EPRJ-003 overrun (investigation scope) | — | $8.4K | $8.4K |
| **Total** | **$106K** | **$270K** | **$376K** |

Annualized cost of the scrap rate increase (if not corrected): approximately $630K.

---

## 9. Lessons Learned

1. **Supplier specification management:** Simplicit's incoming material specifications should be more explicitly defined than ASTM-broad ranges where process-specific tolerances are tighter. The gap between ASTM Ti-6Al-4V specification and Simplicit's operational sweet spot was not formalized in supplier contracts.

2. **Tacit knowledge risk:** Operator attrition eroded informal process knowledge that was not captured in standard work instructions. Knowledge management is a manufacturing resilience issue, not just an HR issue.

3. **Maintenance deferral:** Tool changes should not be deferrable based on resource availability. A hard stop (electronic lock) in the MES/WO system for overdue PMs is a recommended long-term control (CA-09).

4. **Cross-functional trigger:** This investigation confirmed that the Line 2 scrap issue had multi-cause roots spanning Material (supplier), Machine (maintenance), and Man (training/attrition). Future investigations of persistent quality deviations should engage all three domains from Day 1.

---

*Prepared by: Ronald Carter / Charles Anderson*
*Approved: Kimberly Gonzalez (Manufacturing Director), Jessica Robinson (Quality Director)*
*Final report issued: June 5, 2026*
*Next review: July 31, 2026 (effectiveness check)*
