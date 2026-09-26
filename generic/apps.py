from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules
from django.utils.translation import gettext_lazy as _


class GenericConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "generic"
    verbose_name = _("Generic framework")

    def ready(self) -> None:
        # What `manage.py check` says about how the project plugged the
        # framework in (generic/checks.py).
        from generic import checks  # noqa: F401

        # Importing the module registers its signal receivers.
        from generic.events import signals  # noqa: F401

        # Every app's tasks.py declares what it knows how to run. Celery
        # imports these too, at its own start; the site needs them here,
        # before resources.py decides whether to offer the task pages.
        autodiscover_modules("tasks")

        # Every app's resources.py registers its models on the site, the
        # way admin.py does for the admin. It has to happen before the
        # URLconf is read, which is why it happens here.
        autodiscover_modules("resources")

        # After them, so the framework's own screens come last in the
        # navigation: what the project declared is what it opens on.
        from generic.accounts.resources import register_screens as people
        from generic.events.resources import register_screens as messages
        from generic.history.resources import register_screens as history
        from generic.tasks.resources import register_screens as tasks

        tasks()
        history()
        people()
        messages()

        # Last of all: a related model an auto() resource names gets
        # pages of its own - unless something above declared it, the
        # People screens included.
        from generic.sites import site

        site.complete_auto()

        self.arm_restart_announcements()

    def arm_restart_announcements(self) -> None:
        """Pick up a restart this process was not around to warn about.

        On the first request rather than here: ``ready()`` runs for
        every management command, migrations included, and a table that
        does not exist yet must not turn into a crash on ``migrate``.
        """
        from django.core.signals import request_started

        def arm(**kwargs: object) -> None:
            request_started.disconnect(arm, dispatch_uid="generic.restart")

            from generic.maintenance.scheduler import arm_pending

            try:
                arm_pending()
            except Exception:  # pragma: no cover - a fresh database
                pass

        request_started.connect(
            arm,
            weak=False,
            dispatch_uid="generic.restart",
        )
