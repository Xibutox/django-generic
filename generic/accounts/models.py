"""Per-user state, kept apart from the user model."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

#: Appearance preference -> the CSS parameter it sets, the divisor from
#: the stored integer to the CSS number (see tokens.css), and the range
#: the stored integer is held to. The range is enforced again here
#: because these numbers are written into a style attribute: whatever
#: reaches the database, what reaches the page is one of these.
APPEARANCE_PARAMETERS = (
    ("accent_hue", "--ui-hue", 1, (0, 360)),
    ("colorfulness", "--ui-colorfulness", 100, (0, 130)),
    ("tint", "--ui-tint", 100, (0, 100)),
    ("contrast", "--ui-contrast", 100, (-100, 100)),
    ("stripes", "--ui-stripes", 100, (0, 100)),
)


class UserPreferences(models.Model):
    """How one user wants the application to behave.

    Created on the first save only: until then the defaults apply, and a
    user who never opens the preferences page costs no row.
    """

    class Theme(models.TextChoices):
        SYSTEM = "system", _("Follow the system")
        LIGHT = "light", _("Light")
        DARK = "dark", _("Dark")

    class NotificationChannel(models.TextChoices):
        IN_APP = "in_app", _("In the application")
        EMAIL = "email", _("By e-mail")
        BOTH = "both", _("Both")

    class Navigation(models.TextChoices):
        PINNED = "pinned", _("Pinned beside the page")
        FLOATING = "floating", _("Floating over the page")

    PAGE_SIZES = (
        (10, "10"),
        (15, "15"),
        (25, "25"),
        (50, "50"),
        (100, "100"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="generic_preferences",
    )
    theme = models.CharField(
        _("theme"),
        max_length=10,
        choices=Theme.choices,
        default=Theme.SYSTEM,
    )
    #: Not a choice field: the languages a project offers are a setting,
    #: and a migration must not have to follow it. What may be stored is
    #: checked where it is set (``generic.i18n.is_offered``).
    language = models.CharField(
        _("language"),
        max_length=10,
        blank=True,
        default="",
        help_text=_("Leave empty to follow the browser's language."),
    )
    table_page_size = models.PositiveSmallIntegerField(
        _("rows per page"),
        choices=PAGE_SIZES,
        null=True,
        blank=True,
        help_text=_(
            "How many rows a table shows at first. Leave empty to use "
            "each table's own default."
        ),
    )
    remember_table_state = models.BooleanField(
        _("remember table layouts"),
        default=True,
        help_text=_(
            "A table comes back with the filters, columns and sorting "
            "you left it with."
        ),
    )
    notification_channel = models.CharField(
        _("notifications"),
        max_length=10,
        choices=NotificationChannel.choices,
        default=NotificationChannel.IN_APP,
        help_text=_("How you want to hear about what needs you."),
    )
    #: Where the navigation sits. The pin in the top bar sets it too, and
    #: the browser remembers the last choice on its own; this is what a
    #: browser that has never been told applies - so the choice follows
    #: the user to another machine.
    navigation = models.CharField(
        _("navigation"),
        max_length=10,
        choices=Navigation.choices,
        default=Navigation.PINNED,
        help_text=_(
            "Pinned, the navigation holds the page open beside it. "
            "Floating, the page takes the whole width and the "
            "navigation slides out from the left edge."
        ),
    )

    # -- Appearance --------------------------------------------------------
    #
    # The parameters every colour of the interface is computed from.
    # Empty means the project's default, so changing the default still
    # reaches everyone who never moved the slider.

    accent_hue = models.PositiveSmallIntegerField(
        _("accent colour"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(360)],
        help_text=_("Hue of the accent, in degrees."),
    )
    colorfulness = models.PositiveSmallIntegerField(
        _("colourfulness"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(130)],
        help_text=_("0 for greys only, 100 for the standard colours."),
    )
    tint = models.PositiveSmallIntegerField(
        _("tint of the greys"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text=_("How much of the accent the backgrounds carry."),
    )
    contrast = models.SmallIntegerField(
        _("contrast"),
        null=True,
        blank=True,
        validators=[MinValueValidator(-100), MaxValueValidator(100)],
        help_text=_("From -100, soft, to 100, strong."),
    )
    stripes = models.PositiveSmallIntegerField(
        _("table stripes"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text=_("How visible every other table row is."),
    )

    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("preferences")
        verbose_name_plural = _("preferences")

    def __str__(self) -> str:
        return str(_("Preferences of %(user)s") % {"user": self.user})

    @classmethod
    def for_user(cls, user: Any) -> "UserPreferences":
        """The saved preferences, or unsaved defaults.

        Read through the reverse accessor, which Django caches on the
        user instance, so asking twice in a request costs one query.
        """
        try:
            return user.generic_preferences
        except ObjectDoesNotExist:
            return cls(user=user)

    def get_appearance(self) -> dict[str, int]:
        """The appearance parameters this user set, by field name."""
        return {
            name: int(getattr(self, name))
            for name, _parameter, _scale, _range in APPEARANCE_PARAMETERS
            if getattr(self, name) is not None
        }

    def appearance_style(self) -> str:
        """The user's parameters as CSS custom properties.

        Rendered into the ``style`` of ``<html>``, so they apply before
        the first paint. Built from the stored integers alone, clamped
        to their ranges, so nothing else can reach the attribute.
        """
        declarations = []

        for name, parameter, scale, (low, high) in APPEARANCE_PARAMETERS:
            value = getattr(self, name)

            if value is None:
                continue

            number = max(low, min(high, int(value))) / scale
            declarations.append(f"{parameter}: {number:g};")

        return " ".join(declarations)

    def as_client(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "navigation": self.navigation,
            "tablePageSize": self.table_page_size,
            "rememberTableState": self.remember_table_state,
            "appearance": self.get_appearance(),
        }


class SavedView(models.Model):
    """A table layout a user saved under a name.

    ``state`` holds what the table needs to come back the same: visible
    columns, their order, the sorting, the filters and the search.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="generic_saved_views",
    )
    #: The table's state key, such as ``site.example.ticket``.
    table = models.CharField(_("table"), max_length=150, db_index=True)
    name = models.CharField(_("name"), max_length=80)
    state = models.JSONField(_("state"), default=dict)
    is_default = models.BooleanField(
        _("default"),
        default=False,
        help_text=_("Applied when the table opens."),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name = _("saved view")
        verbose_name_plural = _("saved views")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "table", "name"),
                name="generic_saved_view_unique",
            ),
        )

    def __str__(self) -> str:
        return self.name
