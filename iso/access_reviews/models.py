"""Access review campaigns (ISO/IEC 27002 5.18, 8.2).

A review collects every account in its scope as it is now - its groups,
how many permissions it holds, whether it is privileged, when it last
signed in - into items a reviewer decides one by one: keep, or revoke.
Applying the decisions deactivates the revoked accounts; the campaign,
with each decision's author and date, is the record the standard asks
for.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

USER = settings.AUTH_USER_MODEL


class AccessReview(models.Model):
    class Scope(models.TextChoices):
        ALL = "all", _("Every active account")
        PRIVILEGED = "privileged", _("Privileged accounts only")
        GROUP = "group", _("Members of a group")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        IN_PROGRESS = "in_progress", _("In progress")
        COMPLETED = "completed", _("Completed")

    title = models.CharField(_("title"), max_length=200)
    scope = models.CharField(
        _("scope"), max_length=10, choices=Scope.choices, default="all"
    )
    group = models.ForeignKey(
        "auth.Group",
        verbose_name=_("group"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reviewer = models.ForeignKey(
        USER,
        verbose_name=_("reviewer"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    due_on = models.DateField(_("due on"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="draft"
    )
    started_on = models.DateField(
        _("started on"), null=True, blank=True, editable=False
    )
    completed_on = models.DateField(
        _("completed on"), null=True, blank=True, editable=False
    )
    conclusion = models.TextField(_("conclusion"), blank=True)

    class Meta:
        ordering = ("-pk",)
        verbose_name = _("access review")
        verbose_name_plural = _("access reviews")

    def __str__(self) -> str:
        return self.title

    def accounts(self):
        """The accounts in the review's scope, now."""
        users = get_user_model().objects.filter(is_active=True)
        if self.scope == self.Scope.PRIVILEGED:
            users = users.filter(
                models.Q(is_superuser=True) | models.Q(is_staff=True)
            )
        elif self.scope == self.Scope.GROUP:
            users = users.filter(groups=self.group)
        return users.prefetch_related("groups").order_by("username")

    def collect(self) -> int:
        """Add an item for each account in scope not yet listed; start
        the campaign. Returns how many were added."""
        listed = set(
            self.items.exclude(account=None).values_list(
                "account_id", flat=True
            )
        )
        added = 0
        with transaction.atomic():
            for user in self.accounts():
                if user.pk in listed:
                    continue
                AccessReviewItem.objects.create(
                    review=self,
                    account=user,
                    account_label=user.get_username(),
                    is_superuser=user.is_superuser,
                    is_staff=user.is_staff,
                    groups=", ".join(
                        sorted(group.name for group in user.groups.all())
                    ),
                    permission_count=len(user.get_all_permissions()),
                    last_login=user.last_login,
                )
                added += 1
            if self.status == self.Status.DRAFT:
                self.status = self.Status.IN_PROGRESS
                self.started_on = timezone.localdate()
                self.save(update_fields=["status", "started_on"])
        return added


class AccessReviewItem(models.Model):
    """One account, as it was when collected, and the decision on it."""

    class Decision(models.TextChoices):
        PENDING = "pending", _("To decide")
        KEEP = "keep", _("Keep")
        REVOKE = "revoke", _("Revoke")
        MODIFY = "modify", _("Change the rights")

    review = models.ForeignKey(
        AccessReview,
        verbose_name=_("access review"),
        on_delete=models.CASCADE,
        related_name="items",
    )
    account = models.ForeignKey(
        USER,
        verbose_name=_("account"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    account_label = models.CharField(
        _("account name"), max_length=150, editable=False
    )
    is_superuser = models.BooleanField(
        _("superuser"), default=False, editable=False
    )
    is_staff = models.BooleanField(_("staff"), default=False, editable=False)
    groups = models.TextField(_("groups"), blank=True, editable=False)
    permission_count = models.PositiveIntegerField(
        _("permissions"), default=0, editable=False
    )
    last_login = models.DateTimeField(
        _("last sign-in"), null=True, blank=True, editable=False
    )
    decision = models.CharField(
        _("decision"),
        max_length=8,
        choices=Decision.choices,
        default="pending",
    )
    comment = models.CharField(_("comment"), max_length=300, blank=True)
    decided_by = models.ForeignKey(
        USER,
        verbose_name=_("decided by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    decided_at = models.DateTimeField(
        _("decided at"), null=True, blank=True, editable=False
    )
    applied_at = models.DateTimeField(
        _("applied at"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("review", "account_label")
        verbose_name = _("reviewed account")
        verbose_name_plural = _("reviewed accounts")
        constraints = [
            models.UniqueConstraint(
                fields=("review", "account"),
                name="access_reviews_one_item_per_account",
            )
        ]

    def __str__(self) -> str:
        return f"{self.review} - {self.account_label}"

    @property
    def privileged(self) -> bool:
        return self.is_superuser or self.is_staff
