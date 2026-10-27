# POL-04 Backup and restore policy

| | |
| --- | --- |
| Code | POL-04 |
| Version | 1.0 |
| Owner | IT manager |
| Approved by | [Name, role, date] |
| Reviewed | Every 12 months, and after every failed restore test |
| ISO/IEC 27001:2022 | 8.13, 8.14, 5.29, 5.30, 8.10, 8.24 |
| Applies to | Every application built on django-generic and deployed with its Docker stack |

> **Using this document.** It describes what must be backed up in a
> django-generic application and how the stacks of this repository do
> it. Text in [brackets] is the organisation's to fill in.

## 1. Purpose

Be able to bring the application back, with its data, within the
recovery objectives set by the business impact analysis
(`iso.continuity`: RTO, RPO), and prove it by testing restores.

## 2. What is backed up

Two things hold the application's state, and **they are backed up
together, from the same moment**:

| What | Where | Why |
| --- | --- | --- |
| The database | PostgreSQL, the `postgres-data` volume | Every record, the history, the security events, the access log, the accounts and their permissions |
| The uploaded files | `MEDIA_ROOT`, the `app-media` volume | Attachments, policies' documents, incidents' evidence, the wiki's images. The database names them: one without the other is incomplete |

Not backed up, because they are rebuilt: Redis (the task queue and the
cache), the static files (collected into the image), the images
themselves (built from the repository). The configuration -
`docker/prod.env` and its secrets - is kept [in the password manager],
**not** with the backups.

## 3. How

### 3.1 A project made by `scripts/new_project.py`

Its `backup` service does it every day at `BACKUP_TIME`:

1. `pg_dump` (custom format) of the database and a `tar` of the
   uploaded files, each streamed straight into GnuPG - AES-256, from
   `BACKUP_PASSPHRASE` - so nothing unencrypted reaches the disk;
2. a `MANIFEST` (versions, SHA-256 of both files), then a check: the
   checksums, then both files decrypted and read through
   (`pg_restore --list`, `tar -t`). Only a checked backup takes its
   final name;
3. backups older than `BACKUP_KEEP_DAYS` are deleted, never the newest;
4. on `BACKUP_TEST_WEEKDAY`, the newest is restored in full into a
   throwaway database, its tables, migrations and files counted, and the
   result appended to `backups/restore-tests.log`.

| Command | Does |
| --- | --- |
| `python ops.py backup` | A backup now |
| `python ops.py backups` | The list |
| `python ops.py verify [NAME]` | The checks of step 2 |
| `python ops.py restore-test [NAME]` | Step 4, now |
| `python ops.py restore NAME` | Asks to type the project's name, takes a backup of the present state, stops the site, restores the database and the files beside the live ones, switches only once both are complete, starts again |

### 3.2 The example stack (`docker/docker-compose.prod.yml`)

It has no backup service. The two commands below are run [every day by
the host's cron at 02:00], their output encrypted and copied off the server as section 4 says:

```bash
C="docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env"
$C exec -T db pg_dump -U generic generic > backup.sql
$C exec -T web tar -C /app/media -czf - . > media.tar.gz
```

## 4. Rules

| Rule | Value |
| --- | --- |
| Frequency | Every day [, and before every change that migrates the database - POL-07] |
| Retention | [`BACKUP_KEEP_DAYS` = 30 days on the server; 12 monthly copies off site] |
| Copies | `backups/` copied off the server every day [to ...], in another place than the server |
| Encryption | AES-256 (GnuPG). The passphrase is kept outside the server [in ...], known to [names] |
| Access | Only [the IT manager and their deputy] read the backups and the passphrase |
| Restore test | Weekly, automatic (3.1, step 4); a full restore exercise [twice a year], recorded in `iso.continuity` |
| RPO / RTO | Those of the service in `iso.continuity` [e.g. RPO 24 h, RTO 4 h] |

A daily backup gives an RPO of 24 hours at best. A service whose RPO
is shorter needs more [PostgreSQL WAL archiving, replicas].

## 5. Restore tests: the evidence

- `backups/restore-tests.log`: each weekly test, its date and result.
  [Read every month by the IT manager; a failed line is an incident -
  POL-08.]
- `iso.continuity`: an **exercise** of kind *Backup restore* for each
  full test, with the recovery time and data loss achieved. The
  exercise compares them with the service's RTO and RPO and shows
  whether the target was met.
- A failed or partly passed exercise opens a nonconformity in
  `iso.audits`.

## 6. Restoring

1. Decide the restore [the IT manager, with the service owner], and
   which backup: the newest before the damage.
2. Announce the interruption (*Plan a restart*, POL-07).
3. `python ops.py restore NAME` (3.1), or by hand: database and files
   from the **same** backup.
4. Check: sign in, open recent records and their files, *Server status*
   all green, `manage.py showmigrations` complete.
5. Record it: an incident's timeline when it follows one, an exercise
   in `iso.continuity` otherwise.

Restoring brings back the history, the security events and the access
log as they were at the backup: what happened after is in the
application log copied off the server (POL-06).

## 7. Deletion

Backups are deleted after their retention, so the personal data they
hold is not kept longer than the register of processing says. A record
deleted from the application stays in the backups until they expire;
[say so in the register].
