# POL-07 Change management procedure

| | |
| --- | --- |
| Code | POL-07 |
| Version | 1.0 |
| Owner | IT manager |
| Approved by | [Name, role, date] |
| Reviewed | Every 12 months |
| ISO/IEC 27001:2022 | 8.32, 5.3, 8.9, 8.25, 8.29, 8.31; clause 6.3 |
| Applies to | Changes to the applications built on django-generic, their configuration, their servers and their data model |

> **Using this document.** It describes how changes are requested,
> approved, made and reviewed, with `iso.changes` and the tools the
> repository provides. Text in [brackets] is the organisation's to
> fill in.

## 1. Purpose

No change reaches production without being described, assessed,
tested, approved by someone other than its author, and reviewed
afterwards - and each step leaves a record.

## 2. What is a change

| Kind | Examples | Approval |
| --- | --- | --- |
| **Normal** | A new version of the application, a new app installed, a settings change, a database migration, a new server | A holder of `changes.approve_changerequest`, never the requester |
| **Standard** (pre-approved) | [Applying the base images' security fixes (`build --pull`), adding a user to a group under POL-03] | Listed here; recorded as a change request of kind *Standard*. The app does not skip the approval step for them: the approver approves on sight |
| **Emergency** | A fix for a vulnerability being exploited, restoring a service | Approved [by the CISO or the IT manager, by phone if need be], recorded at once, reviewed afterwards |

Changes to **rights** (accounts, groups, permissions) follow POL-03,
not this procedure: they are recorded in the history of the account or
group.

## 3. The steps, in `iso.changes`

| Step | Who | In the application |
| --- | --- | --- |
| 1. Request | The requester | A change request (CHG-0001...): title, kind, category, description, reason, the assets affected, the risk (low, medium, high) and the impact, the **test plan** and the **rollback plan**, the implementer and the planned dates. The requester is recorded by the application |
| 2. Submit | The requester | *Submit*: the request waits in the *Awaiting approval* view |
| 3. Approve or reject | An approver, not the requester | *Approve* or *Reject*, which keep the approver's name and the time. The button is not offered to the requester, and the server refuses it |
| 4. Implement | The implementer | The work, in the planned window (*Change calendar*), then *Implemented*, which records the time |
| 4'. Roll back | The implementer | If it fails: the rollback plan, then *Failed, rolled back* |
| 5. Review | The requester or the approver | The review field: did it work, what was learnt; then *Close* |

The status moves only through these buttons: it cannot be typed in the
form. Every step is in the request's history.

## 4. A new version of the application

The code lives in git; a change to it is a commit, reviewed and tested
before it is deployed.

1. **Develop** on a branch, in the development environment
   (`example_project.settings.dev`, `docker/docker-compose.dev.yml`),
   never against production data.
2. **Review**: a pull request, read by [someone other than its author].
3. **Test**: the CI runs on every push. django-generic's own
   (`.github/workflows/ci.yml`) runs black, isort, flake8, bandit,
   pip-audit, mypy, the tests with an 80 % coverage gate, PostgreSQL
   and Redis integration, the browser tests, the package build and the
   Docker stacks; a project's CI runs at least its tests and the same
   linters. [Branch protection requires a green CI to merge.]
4. **Change request**: one per deployment, linking the pull request(s)
   and the release notes (`CHANGELOG.md`).
5. **Back up** just before (POL-04) when the version migrates the
   database.
6. **Announce** the interruption: *Plan a restart* in the account menu
   (`generic.add_restartannouncement`) warns every connected person, in
   their language, and restarts the server at the hour unless the
   restart is manual.
7. **Deploy**:

   ```bash
   docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
   ```

   The images are rebuilt, `migrate` runs once, and the web server, the
   worker and the scheduler are replaced only once it has succeeded.
8. **Check**: `manage.py check --deploy` silent, *Monitoring > Server
   status* green, a sign-in, the screens the change touched.
9. **Rollback** if needed: deploy the previous tag; restore the backup
   of step 5 if a migration cannot be reversed.

## 5. Configuration

- Production and development are separated: two settings modules, two
  stacks, two env files with different secrets. `asgi.py` and `wsgi.py`
  default to production, so `DEBUG` is never on by accident.
- The whole configuration is in git (compose files, Dockerfile,
  settings) except the secrets, in `docker/prod.env`, which never is.
- The containers' filesystems are read only [in projects made by
  `scripts/new_project.py`]: a running server cannot drift from its
  image.
- A change to a setting quoted in POL-03, POL-04 or POL-06 updates that
  document in the same change.

## 6. Records

| Record | Where |
| --- | --- |
| Change requests, their approval, implementation and review | `iso.changes`, and each request's history |
| The code change, its review and its tests | git, the pull request, the CI's run |
| What changed in each version | `CHANGELOG.md`, shown on *Help > What changed* |
| Data changed by the change (a migration, an import) | The records' history |
| Planned restarts | The announcement and its notification |

## 7. Segregation of duties

Requester and approver are always two different people: the
application refuses the requester's approval. [When the team is too
small for it, the CISO approves and the management review looks at the
changes they requested.]
