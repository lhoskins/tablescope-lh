# POL-002: Information Security Policy

**Policy ID:** POL-002  
**Title:** Information Security Policy  
**Effective Date:** January 1, 2026  
**Owner:** Chief Information Officer  
**Scope:** All employees, contractors, and systems of Simplicit Demo Company  
**Next Review Date:** January 1, 2027  

---

## 1. Purpose

This policy establishes Simplicit Demo Company's commitment to protecting the confidentiality, integrity, and availability of its information assets. It defines the minimum-security standards required to protect company data, systems, and networks from unauthorized access, disclosure, alteration, or destruction.

---

## 2. Information Classification

All company information must be classified into one of four levels:

| Level | Description | Examples |
|-------|-------------|---------|
| **Public** | Approved for external distribution | Marketing materials, product catalogs |
| **Internal** | For employees only; limited business risk if disclosed | Org charts, internal newsletters |
| **Confidential** | Sensitive; significant business risk if disclosed | Customer data, financial reports, product designs |
| **Restricted** | Highest sensitivity; legal or regulatory obligations | ITAR-controlled data, PII, trade secrets |

Employees must handle information in accordance with its classification level. When in doubt, treat information as Confidential.

---

## 3. Access Control

### 3.1 Principle of Least Privilege
Access to systems and data is granted based on job function and business need. No employee shall have access beyond what is required for their role.

### 3.2 Authentication Requirements
- All accounts must use a minimum 12-character password meeting complexity requirements
- Multi-factor authentication (MFA) is mandatory for all remote access, cloud services, and administrative accounts
- Shared accounts are prohibited except for designated service accounts approved by IT

### 3.3 Account Management
- Access is provisioned by IT upon manager-approved request (see PROC-IT-001)
- Access is reviewed quarterly for all privileged accounts and annually for all standard accounts
- Access is revoked within 24 hours of employment termination

---

## 4. Acceptable Use

Employees must use company systems in accordance with POL-003 (Acceptable Use). Key prohibitions include:

- Installing unauthorized software on company devices
- Connecting personal storage devices without prior IT approval
- Accessing company systems from unmanaged personal devices without using the approved VPN
- Attempting to circumvent security controls or access systems beyond authorized scope

---

## 5. Data Protection

### 5.1 Encryption
- All laptops must have full-disk encryption enabled (BitLocker or equivalent)
- Confidential and Restricted data must be encrypted in transit (TLS 1.2+) and at rest
- Portable media containing Confidential data must be encrypted

### 5.2 Data Handling
- Confidential and Restricted data must not be stored on personal devices or unapproved cloud services
- Customer PII must be handled in compliance with applicable privacy laws (see POL-015)
- Physical documents containing Confidential data must be stored in locked cabinets and shredded when no longer needed

---

## 6. Incident Response

All employees must report suspected security incidents (phishing, malware, unauthorized access, lost/stolen devices) to IT immediately via:
- **IT Help Desk:** ext. 4357 or helpdesk@simplicitdemo.internal
- **After hours:** Security hotline ext. 4911

Do not attempt to investigate or remediate suspected incidents independently. Preserve all evidence and do not power off affected systems unless instructed by IT.

---

## 7. Third-Party and Vendor Security

Vendors and contractors who access company systems or data must sign the Simplicit Demo Company Vendor Security Addendum and comply with the minimum security standards defined therein. Procurement must notify IT prior to onboarding any vendor with system access.

---

## 8. Physical Security

- Badge access is required for all secure areas (production floors, data center, engineering labs)
- Visitors must sign in at reception and be escorted in secure areas at all times
- Tailgating (following another person through a secured door) is prohibited

---

## 9. Training and Awareness

All employees must complete Information Security Awareness training (IT-001) annually. New employees must complete training within 30 days of hire. Targeted phishing simulation exercises are conducted quarterly.

---

## 10. Compliance and Enforcement

Non-compliance with this policy may result in disciplinary action up to and including termination, and may expose the company and individual to legal liability. IT audits system access and configurations on an ongoing basis. Significant deviations are reported to the CIO and CHRO.

---

## 11. Revision History

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0 | June 1, 2019 | CIO | Initial policy |
| 2.0 | January 1, 2022 | CIO | Added MFA mandate, cloud security |
| 3.0 | January 1, 2026 | CIO | Updated encryption standards, AI use references |
