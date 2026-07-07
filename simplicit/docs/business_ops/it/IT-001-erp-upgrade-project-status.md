# ERP Upgrade Project — Status Report
**Document ID:** IT-001  
**Project:** ERP System Modernization (Infor CloudSuite Industrial → Infor CSI v11 + Cloud Migration)  
**Project ID:** IT-PROJ-2024-003  
**Prepared by:** Derek Huang, IT Director  
**Date:** July 1, 2026  
**Distribution:** CEO, CFO, Steering Committee  
**Classification:** Internal

---

## 1. Project Overview

| Field | Detail |
|---|---|
| Project Start | September 1, 2024 |
| Planned Go-Live | March 1, 2027 |
| Total Budget | $1,840,000 |
| Spent to Date | $712,400 |
| EAC (Estimate at Completion) | $1,920,000 |
| Budget Variance | +$80,000 (4.3% over) |
| Implementation Partner | Nexus ERP Consulting Group |
| Executive Sponsor | CFO (Angela Torres) |

---

## 2. Phase Summary

| Phase | Description | Planned End | Actual/Forecast End | Status |
|---|---|---|---|---|
| Phase 1 | Discovery, requirements, system design | Feb 28, 2025 | Feb 28, 2025 | ✅ Complete |
| Phase 2 | Configuration, data migration design, integrations | Aug 31, 2026 | Sep 30, 2026 | 🟡 Delayed 1 month |
| Phase 3 | UAT, training, parallel run | Dec 31, 2026 | Jan 31, 2027 | 🟡 At risk |
| Phase 4 | Go-live, hypercare, stabilization | Mar 1, 2027 | Mar 1, 2027 | ⬜ Not started |

**Current Phase:** Phase 2 (Configuration & Data Migration Design)  
**Phase 2 Completion:** 68% complete as of July 1, 2026

---

## 3. Phase 2 Status Detail

### Module Configuration Progress

| Module | Owner | % Complete | Issues |
|---|---|---|---|
| Finance / GL | A. Torres / Nexus | 90% | Minor chart of accounts mapping TBD |
| Purchasing / Procurement | L. Fontaine / Nexus | 85% | 3-way match logic under review |
| Inventory / Warehouse | K. Reynolds / Nexus | 70% | Lot traceability design in progress |
| Production (Shop Floor) | T. Kowalczyk / Nexus | 55% | Work order integration with MES pending |
| Sales / Order Mgmt | D. Kowalski / Nexus | 65% | Customer pricing matrix complex |
| Quality (QMS Integration) | S. Okonkwo / Nexus | 40% | NCR workflow design delayed — see issues |
| HR / Payroll | M. Chen / Nexus | 80% | Benefit plan mapping complete |
| Engineering (PDM Link) | J. Alvarez / Nexus | 35% | ECR/BOM integration scoping in progress |

### Data Migration Status

| Data Domain | Records | Extract Complete | Clean/Transform | Load Test |
|---|---|---|---|---|
| Customer master | 412 | ✅ | ✅ | ✅ |
| Supplier master | 147 | ✅ | ✅ | 🔄 In progress |
| Item master / BOM | 8,340 | ✅ | 🔄 In progress | ⬜ |
| Open POs | ~220 | ✅ | ✅ | ⬜ |
| Open sales orders | ~180 | ✅ | 🔄 In progress | ⬜ |
| Historical GL (3 years) | ~420K rows | ✅ | 🔄 In progress | ⬜ |
| Fixed assets | 634 | ✅ | ✅ | ✅ |
| Employee master | 320 | ✅ | ✅ | ✅ |

---

## 4. Open Issues & Risks

### Active Issues

| Issue ID | Description | Impact | Owner | Status |
|---|---|---|---|---|
| ISS-047 | MES (shop floor system) integration API not finalized — MES vendor delayed specs | Phase 2 delay, Phase 3 risk | D. Huang / T. Kowalczyk | Escalated to MES vendor; weekly calls |
| ISS-051 | QMS integration scope expanded — NCR workflow requires custom development | +$45,000 estimated; 3-week schedule impact | S. Okonkwo / Nexus | Change order under review |
| ISS-054 | Item master data quality: 1,200+ records have missing or inconsistent unit-of-measure | Data migration blocked for these records | K. Reynolds (data steward) | Cleansing in progress; due July 31 |
| ISS-058 | License count for concurrent users may be insufficient — 85 seats purchased, 104 needed | Cost impact ~$38K/year additional licensing | D. Huang / A. Torres | Negotiating with Infor |

### Key Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 3 UAT compressed by Phase 2 delay | High | High | Evaluate parallel path options; consider staggered module go-live |
| End-user change resistance (especially shop floor) | Medium | High | Change management plan in development; super-user program to launch August |
| Data quality issues delay go-live | Medium | High | Data governance owner assigned (K. Reynolds); weekly data quality review |
| Key IT resource (M. Patel, integration lead) departure risk | Low | High | Knowledge transfer documentation required by August |

---

## 5. Change Management Plan (Preview)

Formal change management program launching August 2026:
- **Super-user network:** 22 super-users identified across all departments; training begins September
- **Communication plan:** Monthly all-hands ERP update; department-specific sessions Q4
- **Training curriculum:** Role-based training modules by Nexus; 4–8 hours per role
- **Parallel run:** 30-day parallel operation planned (Finance and Production) before cutover

---

## 6. Steering Committee Action Items

| Action | Owner | Due |
|---|---|---|
| Approve change order for QMS custom development (ISS-051) | CFO | July 15 |
| Resolve MES integration escalation — VP Manufacturing to engage MES vendor exec | VP Mfg | July 10 |
| Approve license count expansion (ISS-058) | CFO | July 22 |
| Review and approve revised project schedule | Steering Committee | July 29 |

---

*Next status report: August 1, 2026 | Next steering committee meeting: July 29, 2026*
