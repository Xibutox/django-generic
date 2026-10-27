# POL-03 Access control policy and user access management procedure

| | |
| --- | --- |
| Code | POL-03 |
| Version | 1.0 |
| Owner | Chief information security officer (CISO) |
| Approved by | [Name, role, date] |
| Reviewed | Every 12 months, and after any change to the roles below |
| ISO/IEC 27001:2022 | 5.15, 5.16, 5.17, 5.18, 8.2, 8.3, 8.5; clause 7.5 |
| Applies to | Every application built on django-generic, the ISO apps included |

> **Using this document.** It describes how a django-generic
> application actually manages accounts, groups and permissions, so
> that what is written is what the software does. Text in [brackets]
> is the organisation's to fill in. The settings quoted are those of
> the example project (`example_project/settings/base.py`); a project
> that changes them changes this document too.

## 1. Purpose

Give each person the access their job needs and no more, keep a record
of who was given what and by whom, and take access away as soon as it
is no longer needed.

## 2. Principles

1. **Need to know, least privilege.** An account starts with no
   permission at all. Rights are added for a job, never "just in case".
2. **Rights go to groups, not to people.** A group is a job (*Security
   officers*, *Auditors*, *Desk agents*...). A person gets the rights of
   the jobs they hold by being put in the groups. A permission given
   directly to an account is the exception, written down with its
   reason.
3. **One person, one account.** Accounts are personal and never shared.
   A script uses an API token of a named person, not a shared password.
4. **Segregation of duties.** Nobody approves, verifies or reviews
   their own work (section 6).
5. **Privileged access is rare and reviewed.** Superusers and staff
   accounts are kept to the minimum [state the number] and reviewed
   every [3] months.
6. **Everything is recorded.** Every change to an account, a group or
   a permission is kept in the application's history, with who made it
   and when.

## 3. How access works in the application

### 3.1 Accounts

The application's accounts are Django's users. They are managed on
the site itself, under **People > Users** (not in Django's `/admin/`):

| Field | Meaning |
| --- | --- |
| Username, name, e-mail | Who the account is |
| Active | Unticked: the account cannot sign in, its API tokens are refused, its open sessions stop at their next request. Its history stays |
| Staff | May open Django's `/admin/` (see 3.6) |
| Superuser | Holds every permission without being given it |
| Groups | The jobs the person holds |
| User permissions | Rights given directly, on top of the groups' |

The **Users**, **Groups** and **Permissions** screens are shown only
to holders of `auth.view_user` and `auth.view_group`. The
**Permissions** screen is read only: permissions are declared by the
code, never created by hand.

### 3.2 Permissions

Every screen and every API endpoint is protected by Django's **model
permissions**, checked by the server on each request - hiding a button
is never the protection:

| Permission | Gives |
| --- | --- |
| `<app>.view_<model>` | The list, the record's page, its exports and its history tab |
| `<app>.add_<model>` | The *New* form and creating records |
| `<app>.change_<model>` | Editing, editing in the table, bulk edit, the actions that change records (being allowed to change implies being allowed to look) |
| `<app>.delete_<model>` | Deleting |

A person who is not signed in gets nothing: every endpoint refuses an
anonymous request.

Beyond the four per model, some actions have a permission of their
own. In the ISO apps:

| Permission | Gives |
| --- | --- |
| `risks.accept_risk` | Accepting a residual risk (the risk owner) |
| `changes.approve_changerequest` | Approving or rejecting a change request |
| `<app>.customize_<model>` | Adding custom fields to a list |

And in the framework:

| Permission | Gives |
| --- | --- |
| `generic.view_historyentry` | *History > Changes*: every recorded change of every model |
| `generic.view_securityevent` | *History > Security events*: sign-ins, failures, lockouts, exports |
| `generic.view_accessentry` | *History > Access log*: who opened which record, downloaded which file |
| `generic.export_rows`, `generic.download_files` | Exporting tables, downloading files, when the project makes them rights given on request (3.4) |
| `generic.validate_accessrequest` | Deciding the requests for those rights |
| `generic_tokens.add_apitoken` | Making personal API tokens (3.5) |
| `generic_tokens.view_apitoken`, `generic_tokens.delete_apitoken` | Seeing and revoking everyone's tokens |
| `generic.view_status` | *Monitoring > Server status* |
| `generic.add_restartannouncement` | Announcing a planned restart |

### 3.3 Finer than a model

- **Fields.** A resource may restrict a single field
  (`field_permissions`): a cost only the buyers see, a date only a
  manager changes. A hidden field is gone from the list, the form, the
  exports, the filters, the charts and the history tab of whoever may
  not see it.
- **Teams.** With `generic.teams` installed, records may belong to
  teams: a person then sees only their teams' records, everywhere -
  lists, searches, exports, forms, files. Groups say what a person may
  *do*, teams *which records* they do it to. `generic_teams.see_every_team`
  lifts the restriction; give it to managers only.
- **Files.** A resource may refuse one file field to a reader who sees
  the record (`may_download`).

### 3.4 Rights given on request

A project may make exporting and downloading rights that people ask
for (`GENERIC["ACCESS_ON_REQUEST"] = ("export", "download")`, as the
example project does). Whoever lacks the right finds *Ask for
permission* where the export or the file would be; the request (who,
what, why, from which page) goes to the superusers and to holders of
`generic.validate_accessrequest`, who grant or refuse it on *People >
Access requests*. Nobody decides on their own request. Each decision is
a security event (`access_granted`, `access_refused`). A reminder may
also be shown, and ticked, before every export and download
(`EXPORT_DISCLAIMER`, `DOWNLOAD_DISCLAIMER`).

### 3.5 API tokens

A token lets a script call the API **with exactly its owner's
permissions**. It is made by its owner on their account page, shown
once, and only its hash is stored. Defaults: valid 90 days, at most 365
(`API_TOKEN_DEFAULT_DAYS`, `API_TOKEN_MAX_DAYS`), at most 10 per person,
*read only* unless *read and write* is chosen. Making tokens needs
`generic_tokens.add_apitoken`, which only superusers hold until it is
given to a group. Tokens of inactive accounts, expired or revoked
tokens are refused. Making and revoking a token are security events.

### 3.6 The rule that protects the People screens

Whoever may edit accounts could otherwise give themselves anything.
The People screens refuse it, on one rule: **what you grant, you must
already have** (`generic/accounts/guard.py`). For anyone who is not a
superuser:

| Attempt | Result |
| --- | --- |
| Ticking *superuser* | Refused |
| Ticking *staff* without being staff | Refused |
| Adding a group, or a permission, that grants something they do not hold | Refused, naming the permission |
| Giving a group a permission they do not hold | Refused |
| Opening a superuser's form, to edit or delete it | Refused: setting their password would make them that superuser |

For everybody, superusers included: nobody deletes or deactivates the
account they are signed in as.

**Django's `/admin/` does not apply this rule**: a staff account
holding `auth.change_user` there can tick *superuser*. The *staff* flag
is therefore a privileged right [given to nobody but the
administrators named in section 4 / not given at all].

### 3.7 Authentication

| Measure | Value in the example project | Setting |
| --- | --- | --- |
| Password rules | Django's four validators: not like the account's name, a minimum length, not a common password, not only digits [projects made by `scripts/new_project.py`: 12 characters minimum] | `AUTH_PASSWORD_VALIDATORS` |
| Password storage | Argon2 (when the `argon2` extra is installed), never stored as typed, never sent back by the API, never kept in the history | `PASSWORD_HASHERS` |
| Lockout | 5 failures in a row on an account lock it for 15 minutes, without the password even being checked; one address failing on any accounts is locked after 20 | `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` |
| Session length | 8 hours at most | `SESSION_COOKIE_AGE` |
| Idle sign-out | After 60 minutes without a click or a key | `SESSION_IDLE_MINUTES` |
| Cookies | Secure and HTTP-only over HTTPS in production | `settings/prod.py` |
| Single sign-on | Optional: a provider (Entra ID, an OIDC or SAML library) leads the sign-in page; local passwords can be forbidden (`SSO_PASSWORD_LOGIN = False`). A provider's second factor applies to its sign-ins | `SSO_PROVIDERS` |

[If the organisation requires multi-factor authentication, it is
obtained through the single sign-on provider: the framework's own
password form has no second factor.]

## 4. Roles

| Role | Holds | Who |
| --- | --- | --- |
| Superuser | Everything | [At most 2 named administrators; their accounts used only for administration] |
| Access administrator | `auth.view_user`, `auth.add_user`, `auth.change_user`, `auth.view_group`, `auth.change_group`, and only the rights they may hand out | [IT manager] |
| Access request validator | `generic.validate_accessrequest` | [Data owner / CISO] |
| Reviewer of access | `access_reviews.*` | [CISO] |
| Auditor (read) | The *Auditors* group | [Internal auditor] |

The ISO apps' demo (`manage.py seed_iso`) creates two groups as a
starting point:

| Group | Permissions |
| --- | --- |
| *Security officers* | Every permission of the installed ISO apps |
| *Auditors* | Read every ISO record (`view_*`), and every permission of `iso.audits` (record audits, findings, corrective actions) |

People in neither group (in the demo, `dev` and `sales`) see none of
the ISO screens. Neither group can read *History > Changes*, the
security events or the access log: those are given deliberately, one
by one (`generic.view_historyentry`, `generic.view_securityevent`,
`generic.view_accessentry`).

[Add here the organisation's own groups and what each is for.]

## 5. Procedure

### 5.1 A person joins (registration, provisioning)

1. The manager asks for the account [by ticket / by e-mail to the
   access administrator], naming the person's job.
2. The access administrator checks the personnel file is ready
   (`iso.people`: screening, signed terms and confidentiality
   agreement).
3. They create the account on **People > Users**: username, name,
   e-mail, *Active* ticked, the **groups** of the job. No direct
   permission unless the request says why.
   - With single sign-on, the account is created at the first sign-in
     by the provider's library, with the group decided there; leave
     the password empty - the account then has no usable password.
   - Otherwise, set a temporary password the person changes on their
     account page at the first sign-in.
4. The person acknowledges the policies that require it (*Policies >
   Acknowledge*, `iso.isms`).

The account's history keeps who created it, with which groups, when.

### 5.2 A person changes job (modification)

1. The manager asks for the change.
2. The access administrator **adds the new job's groups and removes the
   old ones** in the same change. Rights that are no longer needed go
   at once, not at the next review.
3. Permissions given directly are reviewed at the same time.

### 5.3 A person leaves (removal)

1. On the last day [or before, for a dismissal], the access
   administrator **deactivates** the account (untick *Active*, or the
   *Deactivate* bulk action). Accounts are deactivated, not deleted:
   their history and the records they signed stay readable.
2. Their API tokens are revoked (*People > API tokens*); a deactivated
   account's tokens are refused anyway.
3. The personnel file records the date access was removed and the
   assets returned (`iso.people`, `iso.assets`).
4. With single sign-on, the account is also disabled at the provider.

### 5.4 Exceptional rights

A temporary right (an export for an audit, a download) is asked for
through *Ask for permission* (3.4), so that the request, its reason
and its decision are kept. It is taken away when no longer needed, by
removing the permission from the account.

### 5.5 Privileged accounts

- Superusers are created by a person on the server
  (`manage.py createsuperuser`), never by a script with a known
  password. Demo accounts (`seed_iso`, `seed_example`, password `demo`)
  never exist in production.
- A superuser account is not used for daily work: the administrator
  has a second, ordinary account.
- The *staff* flag is given only with a reason (3.6).

### 5.6 Periodic review of access rights

Every [6] months for every account, every [3] months for privileged
accounts, with `iso.access_reviews`:

1. Create an access review: scope *Every active account*, *Privileged
   accounts only* (superusers and staff) or *Members of a group*; a
   reviewer; a due date.
2. **Collect the accounts**: each account in scope is copied as it is
   now - groups, number of permissions, superuser, staff, last sign-in.
3. The reviewer decides each account: *Keep*, *Revoke*, or *Change the
   rights*. Each decision keeps its author and date. **Nobody decides on
   their own account.**
4. **Apply the decisions**: the accounts decided *Revoke* are
   deactivated. Applying needs `auth.change_user` too, never touches the
   reviewer's own account, and only a superuser deactivates a superuser.
   *Change the rights* is carried out by hand on **People > Users** (the
   history records it).
5. Complete the review with its conclusion. The campaign, with every
   decision, is the evidence of control 5.18.

Look in particular at accounts not signed in for [90] days, direct
permissions, and members of privileged groups.

## 6. Segregation of duties enforced by the software

| Rule | Where |
| --- | --- |
| Nobody approves or rejects their own change request | `iso.changes` |
| Nobody verifies their own corrective action | `iso.audits` |
| Nobody decides on their own account in an access review | `iso.access_reviews` |
| Nobody decides their own request for a right | the framework (3.4) |
| Nobody grants what they do not hold | the People screens (3.6) |

## 7. Records

| Record | Where | Who reads it |
| --- | --- | --- |
| Every change to an account, a group, a permission: who, when, before, after (passwords and last sign-in excluded) | The record's *History* tab; *History > Changes* | Holders of `auth.view_user` / `auth.view_group`; `generic.view_historyentry` |
| Sign-ins, failed sign-ins, lockouts, sign-outs, password changes, tokens made and revoked, rights granted and refused, exports | *History > Security events*, and the `generic.security` log | `generic.view_securityevent` |
| Requests for rights and their decisions | *People > Access requests* | `generic.validate_accessrequest`, `generic.view_accessrequest` |
| Access reviews and their decisions | `iso.access_reviews` | The *Security officers*, the *Auditors* |
| Policy acknowledgements | `iso.isms` | The same |

## 8. What the software does not do

- Decide who needs what: this policy and the managers do.
- Expire an account on a date: deactivation is done by a person, on
  the day (5.3).
- Multi-factor authentication on its own password form: use single
  sign-on for it (3.7).
- Protect against a superuser: a superuser can do everything, including
  deleting history entries (POL-06). Keep them few, named, and reviewed.
- Apply the People screens' rule in Django's `/admin/` (3.6).
