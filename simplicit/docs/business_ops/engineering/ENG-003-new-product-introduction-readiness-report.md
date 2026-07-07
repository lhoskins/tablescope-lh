# ENG-003 — New Product Introduction (NPI) Readiness Report
## EPRJ-001: Next-Generation Aerospace Bracket | Gate 3 Pre-Review
## Simplicit Demo Company | Engineering

**Document ID:** ENG-003
**NPI Gate:** Gate 3 — Manufacturing Readiness Review
**Report Date:** August 20, 2026
**Gate Review Scheduled:** September 5, 2026
**Prepared By:** Darnell Washington, Lead Engineer / Dana Kovacs, Engineering Specialist (NPI support)
**Reviewed By:** Kevin Davis, Engineering Director / Jessica Robinson, Quality Director
**Distribution:** Gate 3 Review Panel: CEO, COO, Engineering Director, Manufacturing Director, Quality Director, Sales Director (VP)

---

## 1. NPI Stage Overview

The EPRJ-001 Next-Generation Aerospace Bracket program is a new product development initiative targeting high-precision titanium structural brackets for aerospace structural assemblies. The product family consists of 3 part numbers:

| Part Number | Description | Target Customer |
|---|---|---|
| SDC-8810-A | Primary Attachment Bracket — Series A (fuselage) | Northstar Aerospace (CUS014) |
| SDC-8810-B | Primary Attachment Bracket — Series B (empennage) | Northstar Aerospace (CUS014) |
| SDC-8815-T | Structural Tie-Down Bracket (titanium variant) | Apex Aerospace LLC (CUS001) — contingent on contract renewal |

**NPI Gate Structure:**
- Gate 1 (Concept): Passed December 2024
- Gate 2 (Design Verification): Passed June 2026
- **Gate 3 (Manufacturing Readiness): Scheduled September 5, 2026** ← This review
- Gate 4 (Production Release): Target Q4 2026

---

## 2. Gate 3 Readiness Criteria and Status

### 2a. Design Readiness

| Criterion | Requirement | Status | Owner | Evidence |
|---|---|---|---|---|
| Design drawings released to manufacturing | All 3 PNs at Rev C or higher | ✅ Complete | D. Washington | DWG-8810-A Rev C, -8810-B Rev C, -8815-T Rev B issued Aug 10 |
| DVT complete | 100% of load cases passed | ✅ Complete | D. Washington | DVT Report DVTR-EPRJ001-002, May 2026 |
| Material specification finalized | Ti-6Al-4V per Simplicit Spec SDC-MAT-014 | ✅ Complete | D. Washington | Spec updated Aug 2026 with tightened hardness range (38–42 HRC) |
| GD&T review completed | All critical dimensions fully toleranced | ✅ Complete | Thomas Jones | GD&T review completed July 15 |
| Design FMEA completed | All RPN scores ≤100 | 🟡 In Progress | Maria Nguyen | 2 items at RPN 112 and 118; mitigation actions in progress |

**Design FMEA Gap:** Two high-RPN items relate to the bracket retention hole depth tolerance (SDC-8810-A). Maria Nguyen is leading a design iteration to reduce the dimensional sensitivity; updated FMEA expected by August 31.

### 2b. Tooling and Fixturing Readiness

| Item | Supplier | Status | Expected Delivery | Notes |
|---|---|---|---|---|
| Turning fixture — 8810-A/B | Keystone Tooling (SUP011) | ✅ Received July 28 | Complete | Qualified per PROC-QA-002 |
| Milling fixture — 8815-T | Eagle Plastics (SUP005) | ✅ Received August 5 | Complete | Minor drawing revision resolved |
| CMM inspection fixture | Internal (Charles Anderson) | 🟡 In progress | August 28 | Final assembly in progress; 85% complete |
| Line 2 workholding jaw set | Internal | ✅ Complete | July 20 | Tested with prototype material |

**Status: Yellow** — CMM fixture not yet delivered. Expected completion August 28, which provides 8 days of margin before the Gate 3 review. Risk is low if no rework is required.

### 2c. Supplier Readiness

| Supplier | Role | Qualification Status | Risk |
|---|---|---|---|
| Cascade Alloys (SUP003) | Primary Ti-6Al-4V rod stock | ✅ Approved (with tightened spec) | Medium — Cascade Alloys 8D not yet closed; monitoring quality compliance |
| Ironside Materials (SUP009) | Secondary / backup titanium source | 🟡 Qualification in progress | Medium — Target Q4 2026 approval |
| Keystone Tooling (SUP011) | Tooling | ✅ Approved | Low |
| Juniper Coatings (SUP010) | Anodize surface treatment | ✅ Qualified May 2026 | Low |

**Cascade Alloys risk note:** The primary material supplier for this product is the same supplier that provided out-of-spec material causing the Line 2 scrap issue (MFG-001). The revised material spec (SDC-MAT-014 with 38–42 HRC hardness requirement) has been communicated to Cascade Alloys and will be reflected in the production purchase agreement. 100% incoming inspection (hardness test) will remain required for Cascade Alloys titanium lots until the secondary source (Ironside) is qualified.

### 2d. Quality and Inspection Readiness

| Criterion | Requirement | Status | Owner |
|---|---|---|---|
| Control Plan developed | Rev A or higher | ✅ Complete | Michael Miller |
| First Article Inspection (FAI) plan | Per AS9102A | 🟡 In progress | Michael Miller |
| FAI hardware available | 3 articles per PN | 🟡 Planned | D. Washington |
| Inspection gauges calibrated | All gauges on current calibration cycle | ✅ Complete | Quality Lab |
| Process FMEA completed | All RPN ≤100 | 🟡 In progress | Jessica Robinson team |

**FAI status:** FAI inspection hardware (first articles) is planned for production in Plant A during the week of August 25. The CMM inspection fixture (above) must be complete before FAI inspection can be executed. FAI results will be presented at the Gate 3 review meeting if completed in time; otherwise, preliminary dimensional results from standard CMM will be accepted as provisional evidence.

### 2e. Manufacturing Readiness

| Criterion | Requirement | Status | Owner |
|---|---|---|---|
| Manufacturing process defined (routing) | All operations documented | ✅ Complete | Charles Anderson |
| Line 2 capable (Cpk ≥1.33 on critical dims) | Cpk study from prototype run | 🟡 In progress | Charles Anderson |
| Standard work instructions (SWI) written | Rev 1 or higher for all operations | ✅ Complete | George Walker |
| Operator training plan developed | All L2 operators trained before production | 🟡 Planned | George Walker |
| Cycle time validated | vs. product cost model | ✅ Validated | Ronald Carter |

**Cpk Study:** A process capability study was conducted on Line 2 using prototype material in August. Results for 3 of 5 critical dimensions show Cpk ≥1.33; 2 dimensions are at Cpk 1.18–1.22. Darnell Washington and Charles Anderson are reviewing whether a tolerance relaxation on the 2 lower-Cpk features is acceptable to Northstar Aerospace (customer). Customer response expected by September 1.

### 2f. Commercial / Sales Readiness

| Criterion | Requirement | Status | Owner |
|---|---|---|---|
| Customer pricing accepted | Signed quote or LOI | ✅ Complete (SDC-8810-A, -8810-B) | Kimberly Martinez |
| Customer delivery expectations confirmed | Lead time and volume commitment | ✅ Confirmed | Kimberly Martinez |
| Contract / PO in place | For initial production run | 🟡 In progress | Margaret Green |
| SDC-8815-T commercial status | Contingent on Apex renewal | 🟡 Pending | Margaret Green |

**Apex Aerospace status:** Contract renewal discussions with Apex Aerospace are in progress (as of August 2026). The SDC-8815-T bracket is contingent on the Apex relationship. If the renewal is not confirmed before the Gate 3 review, the recommendation is to proceed with Gate 3 for -8810-A and -8810-B (which are Northstar-supported) and defer -8815-T to a conditional Gate 4 path.

---

## 3. Gate 3 Readiness Summary

| Category | Status | Gate 3 Criteria Met? |
|---|---|---|
| Design | 🟡 Yellow | Conditional — FMEA to be resolved by Aug 31 |
| Tooling / Fixturing | 🟡 Yellow | Conditional — CMM fixture by Aug 28 |
| Supplier Readiness | 🟡 Yellow | Conditional — Cascade Alloys spec compliance confirmed |
| Quality / Inspection | 🟡 Yellow | Conditional — FAI provisional results accepted |
| Manufacturing | 🟡 Yellow | Conditional — Cpk disposition by Sep 1 |
| Commercial | 🟡 Yellow | Conditional — Apex status for SDC-8815-T |

**Overall Gate 3 Assessment: CONDITIONAL GO — subject to 6 open items**

All 6 conditional items have resolution paths with clear owners and dates. Kevin Davis's recommendation to the Gate 3 panel:

> "We are in a position to approve Gate 3 passage with documented conditions. The program has no blocking technical risks. All open items are on track for resolution within the gate window. I recommend the panel approve Gate 3 with a 30-day condition close-out period, with formal confirmation of all conditions to Kevin Davis by October 5, 2026."

---

## 4. Financial and Revenue Summary

| Metric | Value | Basis |
|---|---|---|
| Estimated production cost (per unit, SDC-8810-A) | $1,285 | Routing + BOM, August 2026 estimate |
| Target selling price (SDC-8810-A) | $2,175 | Northstar accepted quote |
| Gross margin (SDC-8810-A) | 40.9% | |
| Year 1 volume commitment (Northstar) | 840 units (all PNs) | LOI signed |
| Year 1 revenue opportunity | ~$1.9M | |
| Full ramp revenue potential (Year 2+) | $3.5–4.2M | Northstar + potential Apex |

The product line is margin-accretive (40.9% vs. company 38% target) and represents meaningful revenue upside. Gate 3 approval is a critical milestone for Q4 2026 commercial launch.

---

## 5. Gate 3 Conditions Summary

| # | Open Item | Owner | Resolution Date |
|---|---|---|---|
| C-01 | Design FMEA: reduce RPN on 2 items to ≤100 | Maria Nguyen | August 31, 2026 |
| C-02 | CMM inspection fixture delivery and qualification | Charles Anderson | August 28, 2026 |
| C-03 | FAI preliminary results (at least 1 article per PN) | Michael Miller | September 3, 2026 |
| C-04 | Cascade Alloys: confirm spec compliance for production lots | Sarah Nelson / Michael Miller | September 1, 2026 |
| C-05 | Cpk disposition for 2 low-Cpk features (accept or redesign) | D. Washington / Northstar | September 1, 2026 |
| C-06 | SDC-8815-T commercial confirmation (Apex renewal) | Margaret Green | September 15, 2026 (post-gate) |

---

*Prepared by: Darnell Washington, Lead Engineer / Dana Kovacs, Engineering Specialist*
*Reviewed: Kevin Davis, Engineering Director / Jessica Robinson, Quality Director*
*August 20, 2026*
*Gate 3 Review Date: September 5, 2026*
