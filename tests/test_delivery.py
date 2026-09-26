"""Mail, as generic.delivery sends it: what it asks of Django, and what
happens when Django cannot send. The messages themselves - who hears,
in what language - are covered where they are written (messages,
tasks, watches)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from generic import delivery

ANN = SimpleNamespace(email="ann@example.test")
BOB = SimpleNamespace(email="bob@example.test")


class TestMail:
    def test_it_asks_only_what_django_7_still_takes(self, monkeypatch):
        """Django 7.0's send_mass_mail takes the messages and ``using``.
        ``fail_silently=False`` - deprecated in 6.1 - was passed until
        it: a TypeError there, caught like a mail server that is down,
        would have lost every mail without a word."""
        sent = []

        def send_mass_mail(datatuple, *, using=None):
            sent.extend(datatuple)
            return len(datatuple)

        monkeypatch.setattr(delivery, "send_mass_mail", send_mass_mail)

        delivery.mail([ANN, BOB], "Closed", "Ticket 12 is closed.")

        # One each: a single mail to both would show each the other.
        assert [recipients for _, _, _, recipients in sent] == [
            ["ann@example.test"],
            ["bob@example.test"],
        ]

    def test_a_mail_that_cannot_leave_is_logged(self, monkeypatch, caplog):
        def refused(datatuple, **options):
            raise ConnectionRefusedError("no mail server")

        monkeypatch.setattr(delivery, "send_mass_mail", refused)

        with caplog.at_level(logging.ERROR, logger=delivery.__name__):
            delivery.mail(
                [ANN], "Closed", "Ticket 12 is closed.", context="12"
            )

        assert "Could not send the mail for 12" in caplog.text

    def test_django_has_nothing_to_warn_of(self, mailoutbox, recwarn):
        """Django 6.1 warns on each mail sent without MAILERS - 7.0 will
        have nowhere to send it - and on each argument it retires. Its
        warnings are pending ones there, which no filter turns into
        errors: they come and go with the versions installed. Whatever
        the Django, a mail sent asks for nothing it is retiring."""
        delivery.mail([ANN], "Closed", "Ticket 12 is closed.")

        assert len(mailoutbox) == 1
        assert [
            str(warning.message)
            for warning in recwarn
            if warning.category.__module__ == "django.utils.deprecation"
        ] == []

    def test_nobody_with_an_address_sends_nothing(self, mailoutbox):
        delivery.mail([SimpleNamespace(email="")], "Closed", "Body.")

        assert mailoutbox == []

    def test_the_link_leaves_absolute(self, mailoutbox, settings):
        settings.GENERIC = {"SITE_URL": "https://desk.example.com/"}

        delivery.mail([ANN], "Closed", "Ticket 12.", url="/tickets/12/")

        (message,) = mailoutbox
        assert message.body.endswith("https://desk.example.com/tickets/12/")
