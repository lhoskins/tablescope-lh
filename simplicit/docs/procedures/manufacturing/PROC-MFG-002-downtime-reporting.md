# PROC-MFG-002: Equipment Downtime Reporting Procedure

**Procedure ID:** PROC-MFG-002  
**Title:** Equipment Downtime Identification and Reporting  
**Department:** Manufacturing  
**Effective Date:** January 1, 2026  
**Owner:** VP Manufacturing  

---

## 1. Purpose

To ensure all equipment downtime is promptly identified, documented, and reported so that OEE metrics are accurate and root cause analysis can be completed.

---

## 2. Scope

All production equipment on lines L1–L4 at Plant A and Plant B.

---

## 3. Downtime Categories

| Code | Category | Description |
|------|----------|-------------|
| DT-01 | Unplanned Mechanical | Equipment failure, breakdown |
| DT-02 | Unplanned Electrical/Control | Electrical fault, PLC error |
| DT-03 | Tooling | Tool breakage, tool change |
| DT-04 | Material | Wrong material, material shortage |
| DT-05 | Quality Hold | First article failure, inspection hold |
| DT-06 | Setup/Changeover | Job changeover, setup adjustment |
| DT-07 | Planned Maintenance | Scheduled PM |
| DT-08 | No Operator | Staffing gap |
| DT-09 | Other | Any other reason |

---

## 4. Reporting Procedure

### Step 1: Identify Downtime
When a line stops for any reason, the operator immediately notates the start time in the production system.

### Step 2: Classify and Log
Within 15 minutes of the line stopping, the operator or Shift Lead enters the downtime event in the MES:
- Date and time start
- Line ID
- Downtime category code
- Brief description (free text)
- Estimated vs. actual duration when line restarts

### Step 3: Escalation
- Downtime > 30 minutes: Shift Lead notifies Maintenance
- Downtime > 2 hours: Shift Lead notifies Production Manager; maintenance escalation to Maintenance Supervisor
- Downtime > 4 hours or threatening customer ship date: Production Manager notifies VP Manufacturing

### Step 4: Root Cause Analysis
All unplanned downtime events > 1 hour require a root cause analysis (5-Why or fishbone) completed by the Shift Lead and Maintenance within 48 hours. Results are entered in the maintenance system.

---

## 5. OEE Reporting

Downtime data feeds the weekly OEE report reviewed by the VP Manufacturing every Monday. Lines with OEE below 75% for two consecutive weeks trigger a formal improvement plan.

---

## 6. Revision History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0 | March 1, 2020 | VP Manufacturing | Initial procedure |
| 2.0 | January 1, 2026 | VP Manufacturing | Added DT-08 staffing code; updated OEE threshold for improvement plan |
