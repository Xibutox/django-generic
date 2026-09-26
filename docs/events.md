# Events, notifications and messages

Real-time updates over WebSocket, using Django Channels and a Redis
channel layer - and the notifications that tell people what they need
to know.

## Who hears what

Three things travel, and they answer different questions:

| | What it says | To whom | Where it shows | Stored |
| --- | --- | --- | --- | --- |
| **Notification** | "You need to know this" | one person | the bell, the *Notifications* page, a toast on every page they have open; an e-mail if they asked for one | yes |
| **Event** | "This changed" | open pages, nobody in particular | nothing by itself: a table refreshes, the bell's count moves | no |
| **Planned restart** | "The server restarts at 22:00" | everyone connected | a banner with a countdown ([maintenance](maintenance.md)) | the announcement |

**Everything addressed to a person is a notification**, whatever it
comes from, and reaches them the way they chose under *Account
settings › Notifications*: in the application, by e-mail, or both.

| Comes from | See |
| --- | --- |
| A record, or a model, they watch | [Watching](watch.md) |
| A task they started, or whose audience they are | [Tasks](tasks.md) |
| A message an administrator wrote | [Messages](#messages), below |
| The project's own code | [Telling people from code](#telling-people-from-code) |

A person reads theirs in the bell - the latest, and how many are
unread - and on the *Notifications* page: every one, as a table to
search, mark read and dismiss.

**An event is wiring.** It reaches whoever is connected right now,
publishing one never touches the database - a table telling itself to
refresh should not cost a write - and it is addressed to no one. The
framework's own keep the pages in step: `resource.changed` refreshes
tables, summaries and charts, `notification.*` keeps the bell right in
every window. A project publishes its own for pages of its own
([Publishing](#publishing)). Nothing a person needs to read travels as
an event alone: storing a notification publishes one, and that is how
the bell and the toast hear of it.

## Wiring

Install the extra and add the channel layer:

```python
# settings.py
INSTALLED_APPS = [..., "generic"]

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {"address": "redis://redis:6379/0", "socket_timeout": 15}
            ],
        },
    }
}
```

The in-memory layer is per process. With more than one worker, only the
worker holding the socket would see the event — it is for tests and a
single-process dev server, nothing else.

`socket_timeout` matters from redis-py 8 on. Its default gives up on a
Redis reply after 5 seconds — exactly how long channels-redis waits for
a socket's next event. The two race and the socket loses: a page left
quiet has its WebSocket closed with a `TimeoutError` every few seconds,
reconnected, and deaf in between. Any value above 5 will do; a Redis
that stops answering is still noticed.

Then the ASGI application (a full example is in `tests/asgi.py`):

```python
django_asgi_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from generic.events.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_application,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
```

`AllowedHostsOriginValidator` is what stops another site from opening a
socket with your users' cookies attached. Do not drop it.

Serve with an ASGI server — Daphne or Uvicorn. A WSGI server will serve
the REST API perfectly well and silently drop every socket.

## Publishing

Events for pages of the project's own - a live board, a progress bar.
To tell a *person* something, store a notification instead
([Telling people from code](#telling-people-from-code)).

```python
from generic.events import (
    broadcast_event, publish_to_topic, publish_to_users,
)

publish_to_users([user], "table.changed", {"table": "books"})
publish_to_topic("project.{project_id}", "project.changed",
                 parameters={"project_id": "12"})
broadcast_event("maintenance.scheduled", {"at": "22:00"})
```

Delivery is deferred to `transaction.on_commit`. A rollback cancels the
event, so clients are never told about a row that no longer exists. For
something that is not about stored data, pass `on_commit=False`.

A delivery failure is logged, never raised: an undeliverable event must
not take down the request that produced it.

Channels is an optional dependency. Without it, publishing is a no-op
that logs once — the rest of the framework works without an ASGI server.

## Topics

A client may ask to subscribe to a topic. Letting it name any group
would let it read anyone's stream, so a topic exists only once the
project declares it, together with the rule saying who may listen.

```python
from generic.events import allow_staff, register_topic

register_topic("audit.log", permission=allow_staff)
register_topic("project.{project_id}")

def member_of_project(user, topic, parameters):
    return user.projects.filter(pk=parameters["project_id"]).exists()

register_topic("project.{project_id}", permission=member_of_project)
```

A permission callable receives `(user, topic_name, parameters)` and is
run in a thread where database access is allowed.

Placeholders in the name become parameters automatically. A value
outside `[A-Za-z0-9._-]` is refused, because Channels rejects such group
names anyway — and it keeps a crafted value from reaching the layer.

Declare topics in your `AppConfig.ready()`.

A topic tells no one anything: it keeps a page of your own true while
it is open. The whole round trip, as the example does it for a team's
queue (`example/events.py`, the *Live updates* page):

```python
# 1. The channel, and who may listen: the team's agents.
register_topic("team.{team_id}", permission=member_of_team)

# 2. Say what changed, when it changes - here from the ticket's signals.
@receiver(post_save, sender=Ticket)
def ticket_saved(sender, instance, **kwargs):
    publish_to_topic(
        "team.{team_id}",
        "team.queue",
        {"team": instance.team_id, "open": queue_size(instance.team_id)},
        parameters={"team_id": str(instance.team_id)},
    )
```

```js
// 3. The page follows it, and redraws.
Generic.events.subscribe("team.4");
Generic.events.on("team.queue", (payload) => {
  count.textContent = payload.open;
});
Generic.events.on("subscription.denied", (payload) => { /* not an agent */ });
```

A page that is not open hears nothing and loses nothing: it reads the
current value when it opens. `queryset.update()` sends no signal, so a
bulk action publishes itself.

## Client protocol

Connect to `ws/events/`. An unauthenticated connection is closed with
code **4001**, so the client can tell "signed out" from "server
restarted" and avoid a reconnect storm.

Client to server:

```json
{"action": "subscribe",   "topic": "project.12"}
{"action": "unsubscribe", "topic": "project.12"}
{"action": "ping"}
```

Server to client:

| `type` | Payload |
| --- | --- |
| `connection.ready` | `{"unread": 3}` |
| `subscription.accepted` | `{"topic": "project.12"}` |
| `subscription.denied` | `{"topic": …, "detail": "Not allowed."}` |
| `subscription.removed` | `{"topic": "project.12"}` |
| `pong` | `{}` |
| `error` | `{"detail": "…"}` |
| *your event type* | whatever you published |

Every frame carries `type`, `payload` and an ISO `timestamp`.

On connect, a socket automatically joins the user's private group and
the broadcast group. Those cannot be joined by name: they are not
registered topics, so `{"action": "subscribe", "topic": "generic.user.1"}`
is denied.

A socket may hold at most 50 subscriptions.

## Messages

*People › Messages* is where an administrator tells some people
something, or everyone. A message has a title, a text, a level and an
optional link, and goes to:

- **everyone** - every active account, or
- the **people** and the **groups** chosen - every active member of
  those groups; someone in two of them hears it once.

Each recipient finds it the way they chose in their preferences - a
notification, an e-mail, or both - unless the message says *In the
application*, *By e-mail* or *Both* for everybody. The e-mails are one
per person: nobody sees anybody else's address.

The list is the record of what was said: by whom, when, to how many,
and how many have read it. A message is not edited once sent - the
notifications it left are copies. **Deleting one withdraws them** from
every recipient's bell and notifications page; an e-mail, once sent,
stays sent.

The screen is an ordinary resource over `generic.Message`, gated on its
model permissions: `add_message` to write, `view_message` to read the
list, `delete_message` to withdraw. Grant them to a group like any
other - with `auth.view_user` and `auth.view_group`, which the people
and groups fields search through, as the admin's autocomplete does;
without them only *Everyone* can be chosen. `SHOW_MESSAGES = False`
takes the screen off. Whoever may write
one also finds *Write a message* on their *Notifications* page.

From code, the same:

```python
from generic.events.messages import send
from generic.events.models import Message

message = Message.objects.create(title="Friday: lunch is on us")
message.groups.add(support)
send(message)          # returns how many people it reached
```

## Telling people from code

`generic.delivery` is what watches, tasks and messages all go through:
each reader in their own language, through the channels they chose.

```python
from generic.delivery import by_preference, deliver
from generic.events.models import NotificationLevel

readers = User.objects.filter(...).select_related("generic_preferences")

for channels, group in by_preference(readers).items():
    deliver(
        group,
        channels=channels,               # ("notification",), ("mail",), both
        message=lambda: (
            gettext("Your export is ready"),
            gettext("12 000 rows."),
            NotificationLevel.SUCCESS,
        ),
        url="/exports/12/",
    )
```

`message` is called once per language, inside it, so `gettext` answers
in each reader's. `select_related("generic_preferences")` reads every
reader's language and choice in the same query. A mail server that is
down is logged, never raised.

## Notifications

The stored half, underneath all of the above - to write one directly,
in the application only:

```python
from generic.events.models import Notification, NotificationLevel

Notification.objects.notify(
    users,
    title="Deployment finished",
    body="Version 1.4.0 is live.",
    level=NotificationLevel.SUCCESS,
    url="/releases/140/",
    content_object=release,
)
```

`notify` uses `bulk_create`, which does not fire `post_save` — so it
returns its rows and `publish_notifications()` announces them:

```python
from generic.events import publish_notifications

publish_notifications(
    Notification.objects.notify(users, title="…")
)
```

A single `Notification.objects.create(...)` publishes itself.

### Endpoints

Mounted from `generic.urls`:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `notifications/` | History, as a data table |
| `GET` | `notifications/unread-count/` | Badge count |
| `POST` | `notifications/{pk}/read/` | Mark read |
| `POST` | `notifications/{pk}/unread/` | Mark unread |
| `POST` | `notifications/read-all/` | Mark everything read |
| `DELETE` | `notifications/{pk}/` | Dismiss |

Every one is scoped to `request.user` at the queryset level rather than
by a permission check, so no action can reach another user's rows —
a foreign id returns 404.

`read-all` uses a bulk `update`, which bypasses `post_save`, so it
publishes a `notification.read_all` event explicitly. Otherwise the
badge in the user's other tabs would stay stale.

### Event types

| Type | When |
| --- | --- |
| `notification.created` | A notification is stored |
| `notification.updated` | One is changed, including marked read |
| `notification.deleted` | One is dismissed |
| `notification.read_all` | Everything was marked read at once |

## The browser client

`generic/js/events.js` opens one socket per tab, shared by everything on
the page — the bell, the tables, the charts, a project's own widgets:

```js
Generic.events.subscribe("project.12");

const stop = Generic.events.on("project.changed", (payload, frame) => {
  // ...
});
```

Every frame is also dispatched on `document` as `generic:event` and as
`generic:<type>`. `on()` returns the function that stops listening.

It reconnects with exponential backoff, but **not** on close code 4001
— the session is gone, and retrying would only hammer the server — and
it caps the attempts: a socket refused during the *handshake* never
reaches 4001 (Channels answers with HTTP 403 and the browser reports
1006, the code a network blip gives), so without a cap a signed-out tab
would retry forever. Topics followed are subscribed again after a
reconnection.

## Static files in development

An ASGI server does not serve static files. `manage.py runserver` adds
that for you; running `daphne myproject.asgi:application` directly does
not, and the result is a page that loads with no styling and 404s on
every asset.

Wrap the HTTP half in development, as `example_project/asgi.py` does:

```python
from django.conf import settings

http_application = django_asgi_application

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

    http_application = ASGIStaticFilesHandler(django_asgi_application)

application = ProtocolTypeRouter({"http": http_application, ...})
```

In production a web server or WhiteNoise serves `STATIC_ROOT` instead,
which is why this sits behind `DEBUG`.
