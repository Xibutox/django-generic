"""Messages: what an administrator says to some people, or to everyone,
delivered to each of them as a notification, an e-mail or both."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("generic", "0013_remove_userpreferences_interface_scale"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Message",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "title",
                    models.CharField(max_length=200, verbose_name="Title"),
                ),
                (
                    "body",
                    models.TextField(
                        blank=True, default="", verbose_name="Message"
                    ),
                ),
                (
                    "level",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "Info"),
                            (2, "Success"),
                            (3, "Warning"),
                            (4, "Critical"),
                        ],
                        default=1,
                        verbose_name="Level",
                    ),
                ),
                (
                    "url",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Where clicking the notification leads: an address on this site, such as /tickets/, or a full one.",
                        max_length=500,
                        verbose_name="Link",
                    ),
                ),
                (
                    "everyone",
                    models.BooleanField(
                        default=False,
                        help_text="Every active account, whatever is chosen below.",
                        verbose_name="Everyone",
                    ),
                ),
                (
                    "delivery",
                    models.CharField(
                        choices=[
                            ("preference", "As each person chose"),
                            ("in_app", "In the application"),
                            ("email", "By e-mail"),
                            ("both", "Both"),
                        ],
                        default="preference",
                        help_text="In the application: the bell, the notifications page, and a toast on every page open. Each person chooses in their preferences unless this says otherwise.",
                        max_length=12,
                        verbose_name="Delivered",
                    ),
                ),
                (
                    "sent_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="Sent at",
                    ),
                ),
                (
                    "recipient_count",
                    models.PositiveIntegerField(
                        default=0, editable=False, verbose_name="Recipients"
                    ),
                ),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Every active member of these groups.",
                        related_name="+",
                        to="auth.group",
                        verbose_name="Groups",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Sent by",
                    ),
                ),
                (
                    "users",
                    models.ManyToManyField(
                        blank=True,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="People",
                    ),
                ),
            ],
            options={
                "verbose_name": "Message",
                "verbose_name_plural": "Messages",
                "ordering": ("-sent_at", "-pk"),
            },
        ),
    ]
