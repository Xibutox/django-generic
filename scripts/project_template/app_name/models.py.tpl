"""{{ app }}: the first model, to replace with the project's own.

Each model gets its list, forms and summary page from resources.py.
"""

from django.db import models


class Item(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
