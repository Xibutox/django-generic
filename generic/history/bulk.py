"""The writes that bypass ``save()``, recorded all the same.

``QuerySet.update()``, ``bulk_update()`` and ``bulk_create()`` send no
signal, so the recorder that listens to ``post_save`` never hears of
them - and a history that misses some changes is not one an auditor can
rely on (ISO/IEC 27001 A.8.15). The three are wrapped, once, for every
queryset; a model nobody records costs one dictionary lookup:

* ``update()`` reads the keys of the rows it is about to change, makes
  the change, reads those rows back and records a version of each - the
  values as the database now holds them, ``F()`` expressions included;
* ``bulk_update()`` does the same for the records it was given;
* ``bulk_create()`` records each record it created, as a creation -
  where the database said which rows it wrote: ``ignore_conflicts``
  never says, so nothing is recorded for it.

Each version is a row of the history like any other: the person and
the source come from the request or the ``acting_as`` block, a write
that changed nothing writes nothing. It costs, per row, what a
``save()`` of it costs the history: so a million-row ``update()`` writes
a million versions. ``generic.history.unrecorded()`` is the explicit
way out, for a migration or a rebuild nobody needs a version of.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Any, Iterable, Iterator

from django.db import transaction
from django.db.models.query import QuerySet

#: Keys read back per query: well under SQLite's variable limit.
CHUNK = 500

#: The resources recording each concrete model, from ``watch()``.
RECORDED: dict[type, list[Any]] = {}

#: Inside one of the wrappers - or ``unrecorded()``: the nested
#: ``update()`` that ``bulk_update()`` makes is not recorded twice.
_quiet: ContextVar[bool] = ContextVar("generic_history_quiet", default=False)

_installed = False


def watch(resource: Any) -> None:
    """Record ``resource``'s model's bulk writes from now on."""
    install()
    model = resource.model._meta.concrete_model
    resources = RECORDED.setdefault(model, [])

    if resource not in resources:
        resources.append(resource)


def unwatch(resource: Any) -> None:
    model = resource.model._meta.concrete_model
    resources = RECORDED.get(model, [])

    if resource in resources:
        resources.remove(resource)

    if not resources:
        RECORDED.pop(model, None)


def recording(model: Any) -> list[Any]:
    """The resources a write to ``model`` is recorded for, if any."""
    if _quiet.get() or not RECORDED:
        return []

    from generic.history.recording import is_recorded

    return [
        resource
        for resource in RECORDED.get(model._meta.concrete_model, ())
        if is_recorded(resource)
    ]


@contextlib.contextmanager
def unrecorded() -> Iterator[None]:
    """Bulk writes inside the block keep no history - said in code, so
    a reader knows it was meant."""
    token = _quiet.set(True)

    try:
        yield
    finally:
        _quiet.reset(token)


def chunks(keys: list[Any]) -> Iterable[list[Any]]:
    for start in range(0, len(keys), CHUNK):
        yield keys[start : start + CHUNK]


def record_rows(
    queryset: QuerySet,
    resources: list[Any],
    keys: list[Any],
    action: str,
) -> None:
    """A version of each row ``keys`` names, as the database has it."""
    from generic.history.recording import record

    manager = queryset.model._base_manager.using(queryset.db)

    for keys_chunk in chunks(keys):
        for obj in manager.filter(pk__in=keys_chunk).order_by("pk"):
            for resource in resources:
                record(resource, obj, action)


def install() -> None:
    """Wrap the three methods, once per process."""
    global _installed

    if _installed:
        return

    _installed = True
    update = QuerySet.update
    bulk_update = QuerySet.bulk_update
    bulk_create = QuerySet.bulk_create

    def recorded_update(self: QuerySet, **kwargs: Any) -> int:
        from generic.history.models import HistoryEntry

        resources = recording(self.model)

        if not resources:
            return update(self, **kwargs)

        with transaction.atomic(using=self.db):
            # Before: the filter may match nothing once the update has
            # changed what it filters on.
            keys = list(self.values_list("pk", flat=True))

            with unrecorded():
                count = update(self, **kwargs)

            record_rows(self, resources, keys, HistoryEntry.Action.UPDATED)

        return count

    def recorded_bulk_update(
        self: QuerySet, objs: Any, fields: Any, *args: Any, **kwargs: Any
    ) -> int:
        from generic.history.models import HistoryEntry

        resources = recording(self.model)

        if not resources:
            return bulk_update(self, objs, fields, *args, **kwargs)

        objs = list(objs)

        with transaction.atomic(using=self.db):
            with unrecorded():
                count = bulk_update(self, objs, fields, *args, **kwargs)

            keys = [obj.pk for obj in objs if obj.pk is not None]
            record_rows(self, resources, keys, HistoryEntry.Action.UPDATED)

        return count

    def recorded_bulk_create(
        self: QuerySet, objs: Any, *args: Any, **kwargs: Any
    ) -> list[Any]:
        from generic.history.models import HistoryEntry
        from generic.history.recording import record

        resources = recording(self.model)

        if not resources:
            return bulk_create(self, objs, *args, **kwargs)

        objs = list(objs)
        # An upsert may have changed an existing row rather than added
        # one: recorded as a change, which a row seen for the first
        # time turns into its first version anyway.
        action = (
            HistoryEntry.Action.UPDATED
            if kwargs.get("update_conflicts")
            else HistoryEntry.Action.CREATED
        )

        with transaction.atomic(using=self.db):
            with unrecorded():
                created = bulk_create(self, objs, *args, **kwargs)

            for obj in created:
                if obj.pk is None:
                    continue

                for resource in resources:
                    record(resource, obj, action)

        return created

    for name, wrapper, original in (
        ("update", recorded_update, update),
        ("bulk_update", recorded_bulk_update, bulk_update),
        ("bulk_create", recorded_bulk_create, bulk_create),
    ):
        wrapper.__name__ = original.__name__
        wrapper.__qualname__ = original.__qualname__
        wrapper.__doc__ = original.__doc__
        wrapper.__wrapped__ = original  # type: ignore[attr-defined]
        setattr(QuerySet, name, wrapper)
        # Django keeps the alters_data marker templates rely on.
        wrapper.alters_data = True  # type: ignore[attr-defined]


__all__ = ["install", "recording", "unrecorded", "unwatch", "watch"]
