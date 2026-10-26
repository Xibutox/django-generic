"""``manage.py personal_data``: the GDPR's everyday requests, from a
shell or a cron (generic.privacy, docs/privacy.md)::

    manage.py personal_data inventory [--json]
    manage.py personal_data export --user alice [--output alice.json]
    manage.py personal_data export --email alice@example.com
    manage.py personal_data anonymize --user alice [--dry-run] [--no-input]
    manage.py personal_data retention [--dry-run]
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Personal data (GDPR): where it lives (inventory), everything "
        "kept about one person (export), their erasure (anonymize), "
        "and the declared retentions (retention)."
    )

    def add_arguments(self, parser: Any) -> None:
        commands = parser.add_subparsers(dest="command", required=True)

        inventory = commands.add_parser(
            "inventory",
            help="Where personal data lives, model by model.",
        )
        inventory.add_argument("--json", action="store_true")

        for name, text in (
            ("export", "Everything kept about one person, as JSON."),
            ("anonymize", "Erase one person's data, account included."),
        ):
            command = commands.add_parser(name, help=text)
            command.add_argument("--user", help="Their account's login.")
            command.add_argument("--email", help="An address of theirs.")

            if name == "export":
                command.add_argument(
                    "--output", help="A file to write; default the output."
                )
            else:
                command.add_argument("--dry-run", action="store_true")
                command.add_argument(
                    "--no-input",
                    action="store_false",
                    dest="interactive",
                    help="Do not ask for a confirmation.",
                )

        retention = commands.add_parser(
            "retention",
            help="Anonymize or delete what is past its retention.",
        )
        retention.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        getattr(self, f"handle_{options['command']}")(options)

    # -- the subcommands -------------------------------------------------

    def handle_inventory(self, options: dict[str, Any]) -> None:
        from generic.privacy.inventory import inventory

        findings = inventory()

        if options["json"]:
            self.stdout.write(
                json.dumps([f.as_dict() for f in findings], indent=2)
            )

            return

        width = max((len(f.model) for f in findings), default=10)

        for finding in findings:
            field = finding.field or "-"
            self.stdout.write(
                f"{finding.model:<{width}}  {field:<20}  "
                f"{finding.kind:<10}  {finding.detail}"
            )

        suspected = sum(1 for f in findings if f.kind == "suspected")

        if suspected:
            self.stdout.write(
                self.style.WARNING(
                    f"{suspected} field(s) look personal and are not "
                    f"declared: declare them (PersonalData) or say why "
                    f"not."
                )
            )

    def handle_export(self, options: dict[str, Any]) -> None:
        from generic.privacy import export

        data = export(self.subject(options))
        text = json.dumps(data, indent=2, ensure_ascii=False)

        if options.get("output"):
            with open(options["output"], "w", encoding="utf-8") as stream:
                stream.write(text)

            self.stdout.write(
                f"{len(data['records'])} record(s) and "
                f"{len(data['references'])} kind(s) of reference written "
                f"to {options['output']}."
            )
        else:
            self.stdout.write(text)

    def handle_anonymize(self, options: dict[str, Any]) -> None:
        from generic.privacy import anonymize_subject
        from generic.privacy.engine import label_of

        subject = self.subject(options)
        rows = anonymize_subject(subject, dry_run=True)

        if not rows:
            self.stdout.write("Nothing to anonymize.")

            return

        for _declaration, obj in rows:
            self.stdout.write(
                f"  {obj._meta.label_lower} {obj.pk}: " f"{label_of(obj)}"
            )

        if options["dry_run"]:
            self.stdout.write(f"{len(rows)} record(s) would be anonymized.")

            return

        if options["interactive"]:
            answer = input(
                f"Anonymize these {len(rows)} record(s)? This cannot be "
                f"undone. Type 'yes' to go on: "
            )

            if answer.strip().lower() != "yes":
                raise CommandError("Nothing was anonymized.")

        done = anonymize_subject(subject)
        self.stdout.write(
            self.style.SUCCESS(f"{len(done)} record(s) anonymized.")
        )

    def handle_retention(self, options: dict[str, Any]) -> None:
        from generic.privacy import apply_retention

        done = apply_retention(dry_run=options["dry_run"])
        verb = "would be processed" if options["dry_run"] else "processed"

        for label, count in done.items():
            self.stdout.write(f"  {label}: {count}")

        self.stdout.write(
            f"{sum(done.values())} record(s) past their retention {verb}."
        )

    # -- helpers ---------------------------------------------------------

    def subject(self, options: dict[str, Any]) -> Any:
        from django.contrib.auth import get_user_model

        from generic.privacy import Subject

        login, email = options.get("user"), options.get("email")

        if not login and not email:
            raise CommandError("Name the person: --user, --email or both.")

        user = None

        if login:
            model = get_user_model()

            try:
                user = model._default_manager.get_by_natural_key(login)
            except model.DoesNotExist:
                raise CommandError(f"No account '{login}'.")

        return Subject(user=user, email=email or "")
