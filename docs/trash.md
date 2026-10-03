# Trash and access log

Two things a resource turns on, each with one attribute: a **trash**,
where deleted records wait to be restored, and an **access log**, which
says who opened a record and who downloaded its files.

```python
# models.py
from generic.trash import Trashable


class Contract(Trashable):  # adds deleted_at and deleted_by
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="contracts/")


# resources.py
@site.register(Contract)
class ContractResource(ModelResource):
    trash = True
    access_log = True
```

## The trash

With `trash = True`, deleting a record - its row's *Delete*, the bulk
action, the delete page, the API's `DELETE` - sets its `deleted_at`
and `deleted_by` instead. The record keeps its relations; the screens
and endpoints of the resource simply stop showing it. The dialogs say
*Move to the trash*, and list nothing that would go with it, since
nothing does.

The list offers a **Trash** page (the `trash` page of the resource, a
`ResourcePage` behind the delete permission). It is the same table,
asked with `?_trash=1`: the deleted records, and two bulk actions:

| Action | What it does |
| --- | --- |
| *Restore* | puts the selected records back |
| *Delete for good* | deletes them, cascading as usual; a record something protects stays |

Whoever may not delete sees an empty trash; nothing else is offered in
it (no row actions, no transitions, no edits).

The model needs the two fields: inherit `generic.trash.Trashable`, or
declare `deleted_at` (a nullable `DateTimeField`) and `deleted_by`
yourself. A resource with `trash = True` on a model without
`deleted_at` raises `ImproperlyConfigured`.

### Emptying it

```bash
python manage.py empty_trash            # older than GENERIC["TRASH_DAYS"] (30)
python manage.py empty_trash --days 0   # everything
```

The same work is the managed task *Empty the trash*
(`generic.empty_trash`, [Tasks](tasks.md)), declared as soon as one
resource has a trash: schedule it once a day. `TRASH_DAYS = None` keeps
everything. In code:

```python
from generic import trash

trash.move_to_trash(contract, user)
trash.restore(contract)
trash.empty(days=30)
```

### What a project still does

A query of your own (`Contract.objects.filter(...)`) sees the trashed
rows: add `deleted_at__isnull=True` where they must not count -
another resource listing contracts, a dashboard figure, a task.

## The access log

With `access_log = True`, the resource writes an entry when somebody:

| Does | Entry |
| --- | --- |
| opens a record's summary page | *Opened* - once every ten minutes per person and record |
| downloads one of its files | *Downloaded*, with the file's name |

An entry keeps who (and their name as it was), the address
(`REMOTE_ADDR`), when, and the record as `app.model:pk` and its label,
so it outlives the record. The summary page gets an **Access log**
link to its entries; *History > Access log* lists them all, behind
`generic.view_accessentry`. Nobody can add, change or delete one from
the screens.

A page of your own records the same way:

```python
from generic.access import record

record(request, contract, action="viewed", detail="preview 1.0")
```

`GENERIC["ACCESS_LOG_RETENTION_DAYS"]` (None: keep everything) is what
`generic.access.prune()` deletes beyond.

## Who may download a file

`may_download(request, obj, field)` refuses a reader one file field of
a record they still see. The download then answers 404, and the
summary page and the tables show the name without a link:

```python
def may_download(self, request, obj, field):
    return field != "draft" or request.user.has_perm("app.change_contract")
```

The document manager (`docmanager/`) uses all three: deleted documents
go to a trash, previews and downloads are logged, and readers who
change nothing download the published version only.
