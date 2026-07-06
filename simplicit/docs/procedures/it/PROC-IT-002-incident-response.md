# PROC-IT-002: IT Security Incident Response Procedure

**Procedure ID:** PROC-IT-002  
**Title:** IT Security Incident Response  
**Department:** Information Technology  
**Effective Date:** January 1, 2026  
**Owner:** IT Director / CISO  

---

## 1. Purpose

To provide a structured process for identifying, containing, eradicating, and recovering from IT security incidents, and for communicating appropriately with affected stakeholders.

---

## 2. Scope

All IT security incidents affecting Simplicit Demo Company systems, networks, data, or users.

---

## 3. Incident Severity Levels

| Level | Description | Examples | Response Time |
|-------|-------------|---------|--------------|
| P1 Critical | Active breach, ransomware, data exfiltration in progress | Ransomware on production systems, confirmed data theft | Immediate (< 15 min) |
| P2 High | Significant compromise; potential data exposure | Phishing success with credential theft, malware on endpoint | < 1 hour |
| P3 Medium | Suspicious activity; limited confirmed impact | Failed intrusion attempt, policy violation | < 4 hours |
| P4 Low | Minor; no confirmed compromise | User received phishing email (not clicked), suspicious email | < 24 hours |

---

## 4. Response Phases

### Phase 1: Detection and Triage
- Incident reported by user, security tool alert, or external notification
- IT Help Desk logs ticket and immediately notifies IT Security Analyst
- IT Security Analyst performs initial triage to classify severity within 30 minutes

### Phase 2: Containment
- Isolate affected systems from the network as appropriate (without destroying forensic evidence)
- Disable compromised user accounts
- Block malicious IPs/domains at perimeter
- Preserve system images and logs before remediation

### Phase 3: Eradication and Recovery
- Remove malware or unauthorized access
- Patch exploited vulnerabilities
- Restore systems from clean backups if necessary
- Verify integrity of restored systems before returning to production

### Phase 4: Communication
- P1/P2: Notify CIO and COO within 30 minutes; Legal and HR as appropriate
- Data breach involving personal data: Legal initiates breach notification assessment (see POL-015)
- Customer notification: coordinated by Legal and VP Sales

### Phase 5: Post-Incident Review
Conduct post-mortem within 5 business days for P1 and P2 incidents. Document root cause, timeline, impact, and corrective actions.

---

## 5. Revision History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0 | January 1, 2022 | IT Director | Initial procedure |
| 2.0 | January 1, 2026 | IT Director | Added Legal/Privacy notification trigger; updated severity table |
