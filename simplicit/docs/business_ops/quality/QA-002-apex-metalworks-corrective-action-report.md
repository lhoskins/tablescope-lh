# 8D Corrective Action Report — Apex Metalworks Nonconforming Bar Stock
**Document ID:** QA-002  
**CAPA Reference:** CAPA-2026-008  
**Supplier SCAR:** SCAR-SUPP-2026-003  
**Initiated by:** Sandra Okonkwo, Director of Quality  
**Date Opened:** April 2, 2026  
**Target Closure:** July 21, 2026  
**Classification:** Internal / Supplier Confidential

---

## D1 — Team

| Name | Role | Department |
|---|---|---|
| Sandra Okonkwo | Team Lead | Quality |
| Tom Hargrove | Manufacturing Engineer | Engineering |
| Kevin Park | Incoming Inspection Lead | Quality |
| Lisa Fontaine | Supply Chain Manager | Procurement |
| Ray Gutierrez | Line 2 Production Supervisor | Manufacturing |

---

## D2 — Problem Description

**Problem Statement:** Beginning in late February 2026, incoming 4140 alloy steel bar stock (2.5" diameter, 12-foot lengths) received from Apex Metalworks (Supplier ID: SUPP-0014) has exhibited an elevated rate of subsurface inclusion defects. These inclusions are not detectable via standard visual or dimensional inspection and are only revealed during machining operations on Line 2.

**Detection Point:** In-process — discovered during turning operations when inclusions cause tool chatter, surface tearing, and unpredictable chip load.

**Defect Data:**
| Lot # | Receipt Date | Qty Received | Qty Rejected | Rejection Rate | Cost Impact |
|---|---|---|---|---|---|
| APX-26-0841 | Feb 24, 2026 | 240 bars | 31 bars | 12.9% | $14,880 |
| APX-26-0902 | Mar 10, 2026 | 180 bars | 28 bars | 15.6% | $13,440 |
| APX-26-0934 | Mar 28, 2026 | 300 bars | 52 bars | 17.3% | $24,960 |
| APX-26-0971 | Apr 15, 2026 | 220 bars | 29 bars | 13.2% | $13,920 |
| **Totals** | | **940 bars** | **140 bars** | **14.9%** | **$67,200** |

Additional downstream impact: Line 2 scrap attributed to bar stock inclusions estimated at $48,600 in finished/semi-finished parts (see MFG-001).

**Total estimated cost of poor quality (COPQ): $115,800**

---

## D3 — Interim Containment Actions

Actions taken April 2, 2026:

1. ✅ All Apex Metalworks bar stock in receiving quarantined (82 bars quarantined, lots APX-26-0971 and APX-26-0972)
2. ✅ 100% incoming inspection via ultrasonic testing (UT) implemented on all future Apex bar stock receipts
3. ✅ Line 2 production paused for 4 hours to sort and segregate suspect in-process material
4. ✅ 34 bars in production queue inspected via UT — 9 bars rejected and quarantined
5. ✅ Emergency purchase order placed with alternate supplier (Ohio Steel Service Center) to cover 6-week supply gap

---

## D4 — Root Cause Analysis

### Fishbone Analysis Performed: April 8, 2026

**Potential Causes Evaluated:**

| Category | Potential Cause | Investigated | Confirmed Root Cause |
|---|---|---|---|
| Material | Ladle chemistry variation at Apex's steel supplier | Yes | Contributing |
| Material | Apex changed steel mill source without notification | Yes | **Primary RC** |
| Process | Apex discontinued UT testing of incoming billets | Yes | **Primary RC** |
| Process | Apex's heat treat process variation | Yes | No |
| Process | Simplicit incoming inspection method inadequate for inclusions | Yes | Contributing |
| Measurement | Simplicit dimensional-only incoming inspection | Yes | Contributing |

### Confirmed Root Causes:

**RC-1 (Primary):** In January 2026, Apex Metalworks transitioned their 4140 bar stock sourcing from Nucor Steel (qualified) to a lower-cost domestic mini-mill (unqualified for aerospace/precision applications) without notifying Simplicit or obtaining approval per the supplier control clause in the MSA (Section 4.3 — Process/Material Changes Requiring Notification). The mini-mill's cleanliness standards are not equivalent to Nucor's for applications requiring ≤1.5mm inclusion size.

**RC-2 (Primary):** Apex discontinued ultrasonic testing of incoming billets from the new mill as a cost-reduction measure, relying solely on mill certifications.

**RC-3 (Contributing):** Simplicit's incoming inspection procedure (PROC-QA-002) specifies visual and dimensional inspection only for bar stock. No UT requirement existed, making the defects undetectable at incoming.

---

## D5 — Permanent Corrective Actions

| Action | Responsible Party | Due Date | Status |
|---|---|---|---|
| Apex to return to Nucor Steel as bar stock source (or equivalent qualified mill) | Apex Metalworks | June 1, 2026 | ✅ Complete |
| Apex to submit revised PPAP with new material source | Apex Metalworks | June 30, 2026 | ✅ Complete |
| Apex to reinstate 100% UT billet inspection and provide test reports with each shipment | Apex Metalworks | June 1, 2026 | ✅ Complete |
| Simplicit to update MSA change notification clause — require 90-day advance notice for material source changes | Procurement / Legal | June 15, 2026 | ✅ Complete |
| Simplicit to update PROC-QA-002 to require UT sampling (10%) on all bar stock ≥1.5" diameter | Quality | July 15, 2026 | In Progress |
| Add UT capability (portable unit) to incoming inspection dock | Quality / Finance | July 30, 2026 | In Progress |

---

## D6 — Implementation Evidence

- Apex corrective action response received June 4, 2026 (on file QA-SUPP-2026-003-R1)
- Updated PPAP package received June 28, 2026 — under review
- First shipment from re-qualified Nucor source received June 22, 2026 (Lot APX-26-1044): 180 bars, 0 rejections on UT inspection
- Second shipment July 1, 2026 (Lot APX-26-1051): 240 bars, 1 rejection (0.4%) — within acceptable AQL

---

## D7 — Prevention of Recurrence

1. Apex Metalworks added to Controlled Shipment Level II program — all shipments require UT report until 6 consecutive clean lots received
2. Supplier audit scheduled July 21, 2026 to verify Apex's incoming inspection process and verify sub-supplier qualification
3. Simplicit MSA template updated to require 90-day advance notification for any material, process, or sub-supplier changes
4. Annual supplier survey to include question on material source stability

---

## D8 — Team Recognition & Closure

**Closure Criteria:** Six consecutive Apex lots with ≤1% UT rejection rate, verified effectiveness of PROC-QA-002 update, and successful July 21 audit.

**Projected Closure Date:** July 31, 2026 (pending audit results and lot 6 receipt)

*Report prepared by S. Okonkwo — April 2 through July 3, 2026*
