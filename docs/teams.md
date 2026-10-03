# Teams

`generic.teams` splits records between teams: a person sees, searches,
opens, downloads and picks only the records of the teams they are a
member of. Groups keep saying what a person may *do* (the model
permissions); teams say *which records* they do it to. A person may be
in several teams, and sees the records of all of them.

The document manager (`docmanager/`) is built on it: each team has its
folders, and a folder's documents and their versions are the team's.

## Installing

```python
INSTALLED_APPS = [
    ...,
    "generic",
    "generic.teams",
    "myapp",
]
```

then `python manage.py migrate`. *People › Teams* appears: a team's
name, colour, description, leaders and members.

## Declaring it

On each resource, the path from the model to its team:

```python
from generic.sites import ModelResource, register


@register(Folder)
class FolderResource(ModelResource):
    team_field = "team"                   # a ForeignKey to generic_teams.Team


@register(Document)
class DocumentResource(ModelResource):
    team_field = "folder__team"           # through the folder


@register(DocumentVersion)
class DocumentVersionResource(ModelResource):
    team_field = "document__folder__team"


@register(Memo)
class MemoResource(ModelResource):
    team_field = "teams"                  # a ManyToManyField: shared by several
```

The model points at the team the ordinary way:

```python
from generic.teams.models import Team

team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="folders")
```

A path that does not lead to `generic_teams.Team` - a typo, a field
that is not a relation - raises `ImproperlyConfigured` at the first
request, naming the model and the field: a declaration error never
reads as an empty list.

## What it does

With `team_field` set:

| Where | What the reader gets |
| --- | --- |
| The list, its search, filters, facets, exports, charts | their teams' rows (`get_queryset`) |
| A record's page, form, summary, history tab, files | 404 for another team's record |
| Related tables, the palette, autocompletes | their teams' rows |
| Forms of **other** models pointing at it | only their teams' records offered, and only those accepted - a key sent by hand is refused with a 400 (`scope_relations`) |
| A watch | told only about their teams' records (`may_watch`) |
| An add form whose `team_field` is the model's own field | opens on the reader's team when they are in exactly one (`get_initial`) |

A record of several teams (`"teams"`) is listed once, whatever the
number of the reader's teams it is in.

Who sees everything: superusers, and holders of the permission
`generic_teams.see_every_team` (*Can see the records of every team*) -
give it to a group of managers. Nobody signed in sees nothing.

The teams themselves are scoped the same way (`TeamResource.team_field
= "pk"`): a member sees their teams, and a form choosing a team offers
only those. Making teams and choosing their members is for holders of
`generic_teams.add_team` / `change_team` who see every team.

## Team leaders

A team has **leaders** beside its members (`Team.leaders`, many to
many). A leader sees the team's records like a member, whether or not
they are one too - `teams_of(user)` and every `team_field` count both.
What leading means beyond that is the project's: the document manager
tells the leaders how each review of their team's documents goes, lets
them steer it, and offers "the team's leaders" as a step's people.

```python
from generic.teams import leaders_of

leaders_of(document.folder.team)       # its active leaders
leaders_of(Team.objects.filter(...))   # of several teams, each person once
```

## Restricting relations without teams

`scope_relations = True` gives the same treatment to forms pointing at
any resource whose `get_queryset(request)` restricts its rows another
way. By default (`None`) it follows `team_field`, so nothing changes
for a resource that never asked.

```python
class CustomerResource(ModelResource):
    scope_relations = True

    def get_queryset(self, request):
        return super().get_queryset(request).filter(region=request.user.region)
```

The hook behind it is `get_relation_queryset(request)` - return a
queryset, or `None` for every row.

## In a view or a task of your own

```python
from generic.teams import in_teams_of, leaders_of, scope_to_teams, sees_every_team, teams_of

documents = scope_to_teams(Document.objects.all(), request.user, "folder__team")
teams_of(request.user)                       # the teams a select may offer
in_teams_of(request.user, document, "folder__team")
sees_every_team(request.user)
```

## What it does not do

- *History › Changes* lists every change to whoever holds
  `generic.view_historyentry`, whatever their teams: it is an
  administrator's page. The *History* tab of a record follows the
  record.
- A `QuerySet.update()` or a task acting for nobody is not narrowed:
  the scope reads the person.
- A team is not a permission. Someone in the team with only the view
  permission reads its records; they do not change them.
