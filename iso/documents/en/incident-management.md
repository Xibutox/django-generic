# POL-08 Information security incident management procedure

| | |
| --- | --- |
| Code | POL-08 |
| Version | 1.0 |
| Owner | Chief information security officer (CISO) |
| Approved by | [Name, role, date] |
| Reviewed | Every 12 months, and after every major incident |
| ISO/IEC 27001:2022 | 5.24, 5.25, 5.26, 5.27, 5.28, 5.5, 6.8; clause 10.2; GDPR art. 33, 34 |
| Applies to | Every event that may affect the information the organisation holds, in or around the applications built on django-generic |

> **Using this document.** It describes how an event is reported,
> assessed, handled and learnt from with `iso.incidents`, and which of
> the application's records an investigation uses. Text in [brackets]
> is the organisation's to fill in.

## 1. Purpose

Report every security event quickly, decide whether it is an incident,
contain it, keep the evidence, tell whoever must be told in time -
the data protection authority within 72 hours for a personal data
breach - and learn from it.

## 2. Reporting an event (6.8)

Everyone reports what they notice: a phishing mail, a lost laptop, a
strange sign-in, data sent to the wrong person, a screen that shows
what it should not.

- **In the application:** *Incidents > New*. Reporting needs only
  `incidents.add_incident`; [give it to every member of staff through a
  group *Staff*]. Someone who holds only that permission files the
  report but cannot read the register. The application records who
  reported it and when.
- **Otherwise:** [phone number / mailbox of the security team], when
  the application is unreachable or is itself affected.

Report at once, even when unsure. Do not investigate on your own, do
not delete anything, do not warn the suspected person.

## 3. Roles

| Role | Who | Permissions |
| --- | --- | --- |
| Reporter | Anyone | `incidents.add_incident` |
| Incident handler | [IT manager, the *Security officers*] | Every `incidents.*` permission |
| Incident manager | [CISO] | The same, and decides the notifications |
| Data protection officer | [Name] | Reads the breaches (`incidents.view_incident`) |
| Investigator | [CISO] | `generic.view_securityevent`, `generic.view_accessentry`, `generic.view_historyentry` |

## 4. The steps

| Step | Status in `iso.incidents` | What is done |
| --- | --- | --- |
| 1. Reported | *Reported* | The report: title, category (phishing, malware, unauthorised access, data leak, loss or theft, denial of service, misconfiguration, physical, other), description, when it was detected, the assets affected |
| 2. Assessment (5.25) | *Being assessed* | The handler decides within [4 working hours]: an incident, or *Not an incident* (the reason in the timeline). Sets the **severity** and the **handler**. Ticks **Personal data breach** when personal data was lost, disclosed, altered or made unavailable |
| 3. Containment (5.26) | *Contained* | Stop the damage: deactivate an account (POL-03), revoke its API tokens, isolate a machine, change a secret. Each action is an update of kind *Action taken* in the timeline |
| 4. Resolution | *Resolved* | Eradicate the cause, restore (POL-04), check |
| 5. Lessons learned (5.27) | *Closed* | Root cause, lessons learned; corrective actions recorded as a nonconformity in `iso.audits` when a control failed |

The status is changed on the incident, or by dragging its card on the
*Response board*. Every update of the **timeline** - note, action
taken, decision, communication - keeps its author and time; the
incident's history keeps every change of its fields.

## 5. Personal data breach (GDPR art. 33, 34)

- Ticking *Personal data breach* gives the incident a deadline:
  **72 hours after its detection** to notify the authority [CNIL:
  notifications.cnil.fr]. The list shows it in *Notify by*, and
  *late* once it has passed without notification.
- The DPO and the incident manager decide whether to notify the
  authority and whether to tell the people concerned (art. 34). The
  dates go in *Authority notified at* and *Data subjects notified at*;
  the reasoning in the timeline as a *Decision*.
- A breach not notified is still recorded, with the reason (art. 33(5)).

Authorities and contacts (CNIL, CERT-FR, the police's cybercrime unit,
[insurer, lawyer]) are listed in *Contacts* (`iso.isms`, 5.5).

## 6. Evidence (5.28)

- Each piece of evidence is added to the incident (*Evidence*): a file,
  who collected it, when, where it is stored, and its chain of custody.
- The application computes the file's **SHA-256** on upload; checking
  the hash later proves the file did not change.
- Every download of a piece of evidence is written in the **access
  log**: who, when, from which address. It is part of the custody.
- Export from the application what the investigation needs **before**
  anything is restored or retention deletes it (section 7), and add it
  as evidence.

## 7. What the application tells the investigator

| Question | Where | Permission |
| --- | --- | --- |
| Who signed in, from which address, when; failed passwords; lockouts | *History > Security events* (`signed_in`, `sign_in_failed`, `locked_out`), and the `generic.security` lines of the application log | `generic.view_securityevent` |
| Who exported which table, how many rows | Security events `exported` | the same |
| Who was given a right, by whom | Security events `access_granted`; *People > Access requests* | the same |
| Which API tokens exist, when each was last used; who made or revoked one | *People > API tokens*; security events `token_created`, `token_deleted` | `generic_tokens.view_apitoken` |
| What changed in a record, who changed it, what it was before | The record's *History* tab; *History > Changes* | `generic.view_historyentry` |
| Who opened a record or downloaded a file | *History > Access log* (resources with an access log) | `generic.view_accessentry` |
| What failed on the server | The application log, the error mails (POL-06) | Server access |

Deleted records leave a *deleted* entry holding what they last were.
The address recorded is the one the server saw, never one a client
could forge.

## 8. Containment in the application

| Need | How |
| --- | --- |
| Stop an account | Untick *Active* on **People > Users**: it cannot sign in, its sessions stop at their next request, its tokens are refused |
| Stop a script | Revoke its token on **People > API tokens** |
| Stop exports and downloads | Take away `generic.export_rows` / `generic.download_files` from the group, when they are rights given on request |
| Take the site down for a fix | *Plan a restart* (POL-07), or stop the stack |
| Sign everyone out | Change `DJANGO_SECRET_KEY` and restart [as a last resort: it also invalidates password-reset links] |

## 9. Records

The incident, its timeline, its evidence and their access log, its
history, and the nonconformities it opened are the records of controls
5.24 to 5.28. They are kept [5 years].
