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
        # The history's PostgreSQL triggers: the ORM's writes tagged, so
        # the triggers record only the others; installed - or removed -
        # after every migrate.
        from django.db.models.signals import post_migrate

        from generic import checks  # noqa: F401
        from generic.conf import generic_settings
        from generic.history import triggers

        if generic_settings.HISTORY and (
            generic_settings.HISTORY_TRIGGERS is not False
        ):
            triggers.install_tagging()

        post_migrate.connect(
            triggers.post_migrate, dispatch_uid="generic.history.triggers"
        )

        # The permission managing each model's custom fields
        # (generic.customfields), made like Django's own after migrate.
        from generic.customfields.signals import create_permissions

        post_migrate.connect(
            create_permissions, dispatch_uid="generic.customfields.permissions"
        )

        # Sign-ins, sign-outs, failures, API tokens: the security log.
        from generic.audit import signals as audit_signals

        # Importing the module registers its signal receivers.
        from generic.events import signals  # noqa: F401

        audit_signals.connect_tokens()

        # Every app's tasks.py declares what it knows how to run. Celery
        # imports these too, at its own start; the site needs them here,
        # before resources.py decides whether to offer the task pages.
        autodiscover_modules("tasks")

        # The framework's own task: the dispatcher of the mailings.
        from generic.conf import generic_settings

        if generic_settings.SHOW_MAILINGS:
            from generic.mailings import dispatch  # noqa: F401

        # Every app's resources.py registers its models on the site, the
        # way admin.py does for the admin. It has to happen before the
        # URLconf is read, which is why it happens here.
        autodiscover_modules("resources")

        # The trash's task, once a resource keeps one: it is the
        # resources that say so.
        from generic import trash

        trash.register_task()

        # The retention periods' task: always there to be scheduled.
        from generic import retention

        retention.register_task()

        # After them, so the framework's own screens come last in the
        # navigation: what the project declared is what it opens on.
        from generic.access.resources import register_screens as accesses
        from generic.accounts.resources import register_screens as people
        from generic.audit.resources import register_screens as security
        from generic.customfields.resources import (
            register_screens as custom_fields,
        )
        from generic.events.resources import register_screens as messages
        from generic.grants.resources import register_screens as grants
        from generic.history.resources import register_screens as history
        from generic.mailings.resources import register_screens as mailings
        from generic.status.resources import register_screens as status
        from generic.tasks.resources import register_screens as tasks

        tasks()
        mailings()
        history()
        custom_fields()
        accesses()
        security()
        people()
        grants()
        messages()
        status()

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
