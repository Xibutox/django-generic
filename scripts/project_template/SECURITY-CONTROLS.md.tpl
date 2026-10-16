# {{ title }}: security controls

What this project's setup does for the ISO/IEC 27001:2022 Annex A
controls it touches, with the ISO/IEC 27002:2022 guidance they follow -
evidence for an audit, and the list of what remains to do.

ISO/IEC 27001 certifies an organisation's management system (ISMS),
not software: no project "is" compliant. What a project can do is make
the controls easy to meet and leave evidence of them. The last section
says what only the organisation can provide.

## What the setup provides

| Control | How | Where |
| --- | --- | --- |
| 5.17 Authentication information | Every secret - Django's key, the database's and Redis's passwords, the backups' passphrase - random from the system's cryptographic source (256 bits and more), different for development and production, never a default: production refuses to start without one. Files readable by their owner alone (0600), out of git and of every image. | `ops.py env`, `docker/prod.env`, `.gitignore`, `.dockerignore`, `{{ project }}/settings/prod.py` |
| 5.17, 8.5 Secure authentication | Argon2 password hashing; passwords of 12 characters or more, checked against the common ones; sign-in lockout after 5 failures for 15 minutes; sessions of 8 hours; secure, HTTP-only cookies over HTTPS. Postgres checks passwords with SCRAM-SHA-256; Redis requires one. | `{{ project }}/settings/base.py`, `docker/compose.prod.yml` |
| 8.2 Privileged access | No account is created by the setup: the first superuser is made by a person (`ops.py manage createsuperuser`). Every container drops all Linux capabilities and adds back only the few its image needs, with privilege escalation forbidden; the application runs as an unprivileged user and cannot change its own code. | `docker/compose.prod.yml` (`x-hardened`), `docker/Dockerfile` |
| 8.3 Information access restriction | Every page and endpoint behind sign-in and Django's model permissions (django-generic). | the framework |
| 8.6 Capacity management | Memory and process limits per container; logs rotated (10 x 10 MB per container). | `docker/compose.prod.yml` |
| 8.9 Configuration management | The whole configuration in version control (compose files, Dockerfile, settings); the variable part in one env file; read-only container filesystems, so a running container cannot drift from its image. `python ops.py manage check --deploy` checks the production settings. | `docker/`, `{{ project }}/settings/` |
| 8.10 Information deletion | The access and security logs kept 365 days (CNIL), then deleted by `manage.py apply_retention` - schedule it daily from the Tasks pages; backups deleted after `BACKUP_KEEP_DAYS`. | `{{ project }}/settings/base.py`, `docker/backup/backup.sh` |
| 8.13 Information backup | Daily backups of the database and the uploaded files together; encrypted; checked after each is written (checksums, decrypted, read through); a full restore into a throwaway database every week, recorded in `backups/restore-tests.log`; retention; a documented, tested restore that never leaves a half-restored state. | `docker/backup/`, `ops.py`, README.md |
| 8.15 Logging | The application's log to standard output and to the `app-logs` volume; the framework's security log (sign-ins, failures, lockouts, exports); container logs rotated. | `{{ project }}/settings/base.py`, `docker/compose.prod.yml` |
| 8.16 Monitoring | Health checks on every service; errors mailed to `DJANGO_ADMINS`. | `docker/compose.prod.yml`, `docker/Dockerfile` |
| 8.17 Clock synchronisation | One time zone (`TZ`) for every container; UTC timestamps in the backups and the restore tests. The host must run NTP. | `docker/prod.env` |
| 8.19, 8.8 Software installation, vulnerabilities | Base images pinned to a version and upgraded on purpose (`build --pull` for the security fixes); the base image's packages upgraded at build; the framework from a wheel committed in `vendor/`, not fetched by name; `pip-audit` in the dev requirements. | `docker/Dockerfile`, `requirements.txt` |
| 8.20 - 8.22 Network security, segregation | Only Caddy is published (80, 443). The database and Redis sit on a network with no route out and nothing published; the scheduler and the backups reach nothing else. The development stack publishes on 127.0.0.1 only. | `docker/compose.prod.yml`, `docker/compose.dev.yml` |
| 8.24 Use of cryptography | TLS by Caddy (certificates obtained and renewed automatically), HSTS; backups encrypted with AES-256 (GnuPG, iterated and salted key derivation); Postgres pages checksummed. | `docker/Caddyfile`, `docker/backup/common.sh` |
| 8.25 - 8.28 Secure development | Settings split by environment, production failing closed; tests (`pytest`) and the framework's own checks. | `{{ project }}/settings/`, `tests/` |
| 8.31 Separation of environments | Development and production: two stacks, two env files, two sets of secrets, two settings modules; `asgi.py`/`wsgi.py` default to production, so DEBUG is never on by accident. | `docker/`, `{{ project }}/settings/` |
| 8.32 Change management | Everything is a file in git; an update is a commit, a build and `ops.py up`. | the repository |

## What remains to do

The organisation's, before going live, and to keep up:

- **Keep `BACKUP_PASSPHRASE` outside the server** (a password manager,
  a safe), and say who can reach it (5.17, 8.13).
- **Copy `backups/` off the server** every day - another site, an
  object store - and check the copy's restore tests (8.13).
- **Read `backups/restore-tests.log`** regularly and keep it: it is the
  restore test record an auditor asks for.
- **Rotate the secrets** on a schedule and when someone leaves: the
  database password with `ALTER ROLE` then `docker/prod.env`; Redis's
  and Django's in `docker/prod.env` (signing everyone out), then
  `python ops.py up` (5.17).
- **Raise `DJANGO_HSTS_SECONDS`** to a year once HTTPS works everywhere
  (8.24).
- **Set `DJANGO_ADMINS` and `EMAIL_*`**, so errors reach someone (8.16).
- **Schedule `apply_retention`** daily from the Tasks pages (8.10).
- **Apply the security fixes**: `build --pull`, `pip-audit`, the
  framework's releases (8.8).
- **The host**: its own updates, firewall (only 80 and 443 open, SSH
  restricted), NTP, disk encryption, who has `docker` access - that is
  root on the machine (8.1, 8.9, 8.17, 8.20).
- **The ISMS itself**: the information security policy, the risk
  assessment and statement of applicability, the asset inventory, the
  access reviews, the incident procedure, the GDPR register of
  processing - no code provides them.
