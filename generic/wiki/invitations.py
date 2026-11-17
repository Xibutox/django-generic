"""Asking someone by e-mail to join a wiki.

A wiki's manager writes an e-mail address and a role in the members
dialog (``POST wikis/<id>/invitations/``); the address gets a link to
``wiki/invitations/<secret>/``. Whoever opens it signed in with that
address - their account's e-mail - and accepts becomes a member with
that role, or keeps a higher role they already hold. A link works once,
for ``GENERIC["WIKI_INVITATION_DAYS"]`` days; inviting the same address
again sends a new link and the old one stops working.

Only a digest of the secret is stored: the database alone opens no
wiki. Someone with no account yet is asked to get one first - how
accounts are made is the project's to say.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from generic.wiki.models import (
    ROLES,
    Wiki,
    WikiInvitation,
    WikiMember,
)
from generic.wiki.serializers import display_name

logger = logging.getLogger(__name__)


class InvitationError(ValueError):
    """Why an invitation cannot be accepted; the message is for the
    reader."""


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def find(secret: str) -> WikiInvitation | None:
    """The invitation a link's secret belongs to, whatever its state."""
    if not secret or len(secret) > 100:
        return None

    return (
        WikiInvitation.objects.select_related("wiki", "invited_by")
        .filter(token=digest(secret), wiki__deleted_at__isnull=True)
        .first()
    )


def role_label(role: str) -> str:
    return str(dict(WikiMember.ROLE_CHOICES).get(role, role))


def invite(
    wiki: Wiki, email: str, role: str, by: Any, request: Any
) -> tuple[WikiInvitation, bool]:
    """A new invitation, its e-mail sent. Answers it, and whether the
    e-mail went: a mail server that refuses is the inviter's to know."""
    email = email.strip().lower()
    secret = secrets.token_urlsafe(32)

    with transaction.atomic():
        # One invitation per address and wiki: the latest.
        wiki.invitations.filter(
            email__iexact=email, accepted_at__isnull=True
        ).delete()
        invitation = WikiInvitation.objects.create(
            wiki=wiki,
            email=email,
            role=role,
            token=digest(secret),
            invited_by=by if getattr(by, "pk", None) else None,
        )

    link = request.build_absolute_uri(
        reverse("generic_wiki:invitation", kwargs={"secret": secret})
    )

    return invitation, send(invitation, link)


def send(invitation: WikiInvitation, link: str) -> bool:
    values = {
        "name": display_name(invitation.invited_by) or _("Someone"),
        "wiki": invitation.wiki.name,
        "role": role_label(invitation.role).lower(),
        "link": link,
        "date": timezone.localtime(invitation.expires_at).strftime("%Y-%m-%d"),
    }
    body = "\n\n".join(
        [
            _(
                "%(name)s invites you to join the wiki “%(wiki)s”"
                " as %(role)s."
            )
            % values,
            _(
                "To accept, open this link and sign in with this e-mail"
                " address:"
            )
            + f"\n{link}",
            _("The link works once, until %(date)s.") % values,
            _(
                "If you have no account on this site yet, ask %(name)s"
                " for one first."
            )
            % values,
        ]
    )
    message = EmailMessage(
        subject=_("Join the wiki “%(wiki)s”") % values,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[invitation.email],
    )

    try:
        message.send()
    except Exception:
        logger.exception("Could not send the invitation %s", invitation.pk)

        return False

    return True


def problem(invitation: WikiInvitation | None, user: Any) -> str:
    """Why ``user`` may not accept ``invitation``; empty when they may."""
    if invitation is None:
        return _("This invitation does not exist, or was replaced.")

    if invitation.accepted_at is not None:
        return _("This invitation was already accepted.")

    if invitation.expires_at < timezone.now():
        return _("This invitation has expired. Ask for a new one.")

    if (getattr(user, "email", "") or "").strip().lower() != (
        invitation.email.lower()
    ):
        return _(
            "This invitation was sent to %(email)s. Sign in with the "
            "account of that address to accept it."
        ) % {"email": invitation.email}

    return ""


def accept(invitation: WikiInvitation | None, user: Any) -> Wiki:
    """``user`` a member of the wiki, with the role they were invited
    to - or the higher one they hold already."""
    reason = problem(invitation, user)

    if reason or invitation is None:
        raise InvitationError(reason)

    wiki = invitation.wiki

    with transaction.atomic():
        if wiki.owner_id != user.pk:
            member = WikiMember.objects.filter(wiki=wiki, user=user).first()

            if member is None:
                WikiMember.objects.create(
                    wiki=wiki, user=user, role=invitation.role
                )
            elif ROLES.index(invitation.role) > ROLES.index(member.role):
                member.role = invitation.role
                member.save(update_fields=["role"])

        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(update_fields=["accepted_at", "accepted_by"])

    return wiki


def invitation_json(invitation: WikiInvitation) -> dict[str, Any]:
    return {
        "id": invitation.pk,
        "email": invitation.email,
        "role": invitation.role,
        "invited_by_name": (
            display_name(invitation.invited_by)
            if invitation.invited_by_id
            else ""
        ),
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
    }
