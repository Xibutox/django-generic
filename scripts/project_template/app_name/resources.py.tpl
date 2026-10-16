"""The screens of {{ app }}: one line per model gives its list, forms,
summary page and API. See django-generic's docs/auto.md, then
docs/tables.md and docs/forms.md for a resource of your own."""

from generic.sites import auto

from {{ app }}.models import Item

auto(Item)
