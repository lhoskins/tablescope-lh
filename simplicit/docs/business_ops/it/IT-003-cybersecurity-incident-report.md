# Cybersecurity Incident Report — Phishing Campaign
**Document ID:** IT-003  
**Incident ID:** SEC-INC-2026-004  
**Incident Date:** May 7, 2026  
**Detected:** May 7, 2026, 10:42 AM  
**Contained:** May 7, 2026, 1:15 PM  
**Report Date:** May 14, 2026  
**Prepared by:** Derek Huang, IT Director  
**Distribution:** CEO, CFO, Legal, HR Director  
**Classification:** Confidential — Restricted

---

## 1. Incident Summary

On May 7, 2026, three Simplicit employees clicked on a link in a targeted phishing email impersonating Microsoft 365 account security. The email prompted credential entry on a spoofed login page. Credentials for two of the three employees were captured by the attacker before IT Security detected the anomaly and revoked access. **No data breach, unauthorized data exfiltration, or lateral movement was confirmed.** All affected accounts were secured within 2.5 hours of initial detection.

**Severity:** Medium (credentials compromised; no confirmed data loss)  
**Affected Users:** 3  
**Credentials Captured:** 2  
**Data Exfiltrated:** None confirmed  
**Systems Accessed by Attacker:** Microsoft 365 mailbox of 1 user (read-only access, ~22 minutes)

---

## 2. Timeline

| Time (EDT) | Event |
|---|---|
| 09:14 AM | Phishing email delivered to 47 Simplicit employees via external sender spoofing Microsoft |
| 09:14–10:38 AM | 3 employees click link; 2 enter credentials on spoofed page |
| 10:42 AM | Microsoft Defender for Office 365 flags anomalous sign-in from Eastern European IP for user account (J. Morrison, Finance) |
| 10:48 AM | IT Security (M. Linden) receives automated alert; begins investigation |
| 10:55 AM | M. Linden contacts J. Morrison — confirms phishing; password reset initiated |
| 11:02 AM | Second affected account identified (P. Vasquez, Sales) — password reset initiated |
| 11:10 AM | Third click-through identified (B. Ochoa, Manufacturing) — credentials not captured (user left page before submitting) |
| 11:15 AM | Both compromised accounts revoked; MFA tokens reset |
| 11:30 AM | Phishing email quarantined from all 47 mailboxes via Microsoft Defender retroactive pull |
| 11:45 AM | Attacker access to J. Morrison mailbox confirmed via audit log — read access only, 22-minute window (10:21–10:43 AM) |
| 1:15 PM | All affected systems confirmed clean; incident contained |
| 1:30 PM | CEO, CFO, and Legal notified |
| May 8 | All-employee phishing awareness notification sent |
| May 14 | Incident report finalized |

---

## 3. Technical Analysis

### Phishing Email Characteristics
- **Sender:** noreply-security@microsoftsupport-365.net (spoofed domain registered May 5, 2026)
- **Subject:** "Action Required: Unusual sign-in activity detected on your account"
- **Lure:** Fabricated Microsoft 365 security alert with Simplicit company logo
- **Link target:** microsoftsupport-365.net/verify — credential harvesting page (taken down by registrar May 8)

### Attack Vector Assessment
The email bypassed Simplicit's standard spam filter because:
1. The spoofed domain was freshly registered (not yet on threat feeds)
2. The email contained no malicious attachments or links to flagged domains
3. The social engineering was well-crafted with accurate Simplicit branding (logo sourced from public website)

### Scope of Attacker Access (J. Morrison Account)
Audit log review confirms attacker accessed J. Morrison's Microsoft 365 mailbox for 22 minutes. Actions observed:
- Email search queries: "invoice," "wire transfer," "bank," "ACH" — consistent with BEC (Business Email Compromise) reconnaissance
- No emails forwarded, downloaded, or deleted
- No SharePoint, Teams, or OneDrive access observed
- No emails sent from the compromised account

**Assessment:** Attacker was conducting reconnaissance consistent with a Business Email Compromise (BEC) precursor. The rapid detection and containment prevented any wire fraud or follow-on attack.

---

## 4. Affected Users

| User | Dept | Credentials Captured | Duration of Risk | Status |
|---|---|---|---|---|
| J. Morrison | Finance | Yes | 22 min | Secured; MFA re-enrolled; password changed |
| P. Vasquez | Sales | Yes | <5 min (no access observed) | Secured; MFA re-enrolled; password changed |
| B. Ochoa | Manufacturing | No (did not submit) | N/A | Notified; security awareness training assigned |

---

## 5. Root Cause

| Cause | Category |
|---|---|
| Freshly registered spoofed domain not on threat intelligence feeds | Technical — detection gap |
| Email filter did not block sender due to no prior reputation data | Technical — detection gap |
| Two employees submitted credentials despite anomalous URL | Human — security awareness |
| MFA was enrolled but used SMS-based OTP (phishable via real-time proxy) | Technical — MFA strength |

---

## 6. Corrective Actions

| Action | Owner | Due | Status |
|---|---|---|---|
| Reset all affected credentials and MFA tokens | IT Security | May 7 (done) | ✅ Complete |
| Retroactive quarantine of phishing email from all mailboxes | IT Security | May 7 (done) | ✅ Complete |
| Enable Microsoft Defender — block newly registered domains (<30 days old) | IT Security | May 14 | ✅ Complete |
| Migrate SMS-based MFA to Microsoft Authenticator app (phishing-resistant) for all Finance users | IT Security | June 30 | ✅ Complete (Finance) |
| Extend Authenticator-app MFA to all employees (company-wide) | IT Security | Sept 30 | 🔄 In progress (65% enrolled) |
| Conduct targeted phishing simulation for all employees who did not report the email | IT Security | June 15 | ✅ Complete — 31% click rate (down from 42% in 2025 simulation) |
| Mandatory phishing awareness training — all employees | HR / IT | June 30 | ✅ Complete — 97% completion |
| Add Finance team to enhanced monitoring (Defender for Cloud Apps) | IT Security | June 15 | ✅ Complete |
| Brief Legal on BEC risk and wire transfer verification procedures | IT / Legal | May 21 | ✅ Complete |

---

## 7. Regulatory / Notification Assessment

**Legal Review (completed May 9, 2026):**
- No customer PII or regulated data was confirmed accessed or exfiltrated
- Ohio data breach notification statute (ORC §1349.19) — threshold not triggered (no confirmed breach)
- Cyber liability insurance carrier notified per policy requirements on May 8
- No customer notification required at this time; situation continues to be monitored

---

## 8. Lessons Learned

1. **Detection was effective** — Defender for Office 365 anomalous sign-in alert fired within minutes of unauthorized access. Investment in Microsoft E5 licensing (2024) was justified.
2. **SMS MFA is insufficient** — real-time phishing proxies can capture and relay OTPs. Migration to app-based (TOTP) or hardware key MFA is a priority.
3. **Finance department is a high-value target** — BEC attacks targeting Finance are common and high-impact. Enhanced monitoring and stricter wire transfer verification controls are warranted.
4. **Employee reporting culture needs improvement** — of 47 employees who received the email, only 6 reported it proactively to IT. Training reinforcement needed.

---

*Incident closed: May 14, 2026 | Post-incident review: June 3, 2026*  
*Approved by: Derek Huang, IT Director*
