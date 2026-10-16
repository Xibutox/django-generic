# Security policy

## Reporting a vulnerability

Please report a vulnerability **privately**, never in a public issue:
on GitHub, *Security › Report a vulnerability* on
[Xibutox/django-generic](https://github.com/Xibutox/django-generic/security/advisories/new).
Say what is affected (a module, a page, an endpoint), how to reproduce
it, and what an attacker gains.

What happens next:

| When | What |
| --- | --- |
| 5 working days | The report is acknowledged, and its severity assessed (CVSS) |
| 30 days | A fix is released for a critical or high severity, sooner when it is exploited |
| 90 days | At the latest, for the others |
| With the fix | A GitHub security advisory, a CVE where one applies, and an entry under *Security* in the changelog |

You are credited in the advisory unless you prefer not to be.

## Supported versions

Only the latest minor release receives security fixes. A project built
on django-generic upgrades within the same major version without
changing its declarations (semantic versioning, see
[generic/CHANGELOG.md](generic/CHANGELOG.md)).

| Version | Supported |
| --- | --- |
| 1.3.x | Yes |
| < 1.3 | No |

The framework requires a Django release that still receives security
fixes (5.2 LTS or later): a Django that has left support is not a
supported setup.

## What the project does

- **Code**: every change goes through a pull request, the CI's linters,
  the test suite (coverage at least 80 %) and `bandit` over the
  framework and the example applications.
- **Dependencies**: `pip-audit` checks every installed dependency
  against the known vulnerabilities on every push; Dependabot proposes
  updates of the Python packages, the GitHub Actions and the Docker
  images every week. The JavaScript libraries are vendored, with their
  versions, in
  [generic/static/generic/vendor/README.md](generic/static/generic/vendor/README.md).
- **Defaults**: permissions enforced by every endpoint, sign-in
  attempts limited, security events and record history logged
  ([docs/security-log.md](docs/security-log.md),
  [docs/history.md](docs/history.md)), production settings that refuse
  to start without their secrets ([docs/deployment.md](docs/deployment.md)).

## Known vulnerabilities accepted

A vulnerability a dependency carries, but which no code path of
django-generic can reach, is skipped by the dependency audit - by its
identifier, with the reason here, until a fixed release exists:

| Identifier | Package | Why it does not apply | Drop when |
| --- | --- | --- | --- |
| CVE-2026-106454 (GHSA-8pqf-f4m5-798g) | twisted 26.4.0 (through daphne, the `events` extra) | A regular-expression denial of service in Twisted's IMAP server (`twisted/mail/imap4.py`). Daphne serves HTTP and WebSocket; nothing here starts an IMAP server. | Twisted releases a fix: raise the floor and remove the `--ignore-vuln` in the CI |
