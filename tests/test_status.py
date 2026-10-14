"""The server status: what it measures, who may read it, and the other
servers it shows."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from generic.history import history_of
from generic.status import checks, register_check
from generic.status import remote as remote_module
from generic.status import system as system_module
from generic.status import unregister_check
from generic.status.collect import FORMAT, snapshot
from generic.status.models import (
    StatusServer,
    status_address,
    validate_status_url,
)
from generic.status.remote import TOKEN_HEADER, fetch
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

STATUS = "/api/generic/status/"
HEALTH = "/api/generic/status/health/"
PAGE = "/status/"
SERVERS = "/api/generic/statusserver/"


@pytest.fixture
def watcher(db):
    """Someone who may read the status, and nothing else."""
    user = UserFactory(username="watcher")
    user.user_permissions.add(Permission.objects.get(codename="view_status"))

    return user


@pytest.fixture
def watcher_client(client, watcher):
    client.force_login(watcher)

    return client


@pytest.fixture
def declared():
    """Checks declared for one test, withdrawn afterwards."""
    names: list[str] = []

    def declare(function, **options):
        name = options.setdefault("name", f"tests.{function.__name__}")
        names.append(name)

        return register_check(function, **options)

    yield declare

    for name in names:
        unregister_check(name)


@pytest.fixture
def products(db):
    return StatusServer.objects.create(
        name="Products",
        url="https://products.example.com",
        token="s3cret",
        description="Products and milestones",
    )


def a_status(**changes) -> dict:
    """What another server answers, trimmed to what is read here."""
    status = {
        "format": FORMAT,
        "level": "ok",
        "server": {
            "title": "Products",
            "page_url": "https://products.example.com/status/",
            "site_url": "https://products.example.com/",
            "api_url": "https://products.example.com/api/generic/status/",
        },
        "system": {},
        "checks": [],
    }
    status.update(changes)

    return status


class Answer(io.BytesIO):
    """An urllib response, as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answering(payload=None, *, body=None, error=None):
    """Patch the opener the status of another server is read with."""

    def open_(request, timeout):
        open_.request = request

        if error is not None:
            raise error

        data = body if body is not None else json.dumps(payload).encode()

        return Answer(data)

    return mock.patch.object(remote_module.opener, "open", side_effect=open_)


class TestTheSnapshot:
    def test_it_names_its_shape(self):
        status = snapshot()

        assert status["format"] == FORMAT
        assert status["level"] in ("ok", "warning", "error")

    def test_it_measures_the_machine(self):
        machine = snapshot()["system"]

        assert machine["cpu"]["count"] >= 1
        assert machine["memory"]["total"] > 0
        assert machine["disks"], "at least the system's disk"
        assert machine["process"]["pid"] > 0

    def test_it_checks_every_database_and_cache(self, settings):
        names = {check["name"] for check in snapshot()["checks"]}

        for alias in settings.DATABASES:
            assert f"database.{alias}" in names

        for alias in settings.CACHES:
            assert f"cache.{alias}" in names

        assert "migrations" in names

    def test_the_migrations_are_up_to_date_in_the_tests(self):
        found = {check["name"]: check for check in snapshot()["checks"]}

        assert found["migrations"]["level"] == "ok"

    def test_a_failed_check_makes_the_server_fail(self, declared):
        def broken():
            raise RuntimeError("the provider is down")

        declared(broken, label="Provider")
        status = snapshot()
        found = {check["name"]: check for check in status["checks"]}

        assert found["tests.broken"]["level"] == "error"
        assert found["tests.broken"]["detail"] == "the provider is down"
        assert status["level"] == "error"

    def test_a_full_disk_is_an_error(self, settings):
        settings.GENERIC = {"STATUS_THRESHOLDS": {"disk": (0, 0)}}

        assert snapshot()["level"] == "error"

    def test_it_tells_of_a_planned_restart(self):
        from datetime import timedelta

        from django.utils import timezone

        from generic.maintenance.models import RestartAnnouncement

        RestartAnnouncement.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=1)
        )

        assert snapshot()["application"]["restart"]["durationMinutes"] == 5

    def test_it_holds_no_secret(self, settings):
        settings.GENERIC = {"STATUS_TOKEN": "s3cret"}
        text = json.dumps(snapshot())

        assert "s3cret" not in text
        assert settings.SECRET_KEY not in text


class TestWhatAChecksReturns:
    @pytest.mark.parametrize(
        "result, expected",
        [
            (None, ("ok", "")),
            (True, ("ok", "")),
            (False, ("error", "")),
            ("warning", ("warning", "")),
            ("Answered", ("ok", "Answered")),
            (("warning", "slow"), ("warning", "slow")),
            ({"level": "off", "detail": "unused"}, ("off", "unused")),
            ({"status": False}, ("error", "")),
        ],
    )
    def test_it_is_read_as_a_level_and_a_detail(self, result, expected):
        assert checks.normalize(result) == expected

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(ValueError):
            checks.normalize(("bad", "detail"))

    def test_anything_else_is_refused(self):
        with pytest.raises(TypeError):
            checks.normalize(42)

    def test_a_check_returning_nonsense_is_shown_as_broken(self, declared):
        declared(lambda: 42, name="tests.nonsense", label="Nonsense")
        found = {check["name"]: check for check in checks.run_checks()}

        assert found["tests.nonsense"]["level"] == "error"

    def test_off_does_not_make_a_server_fail(self):
        assert checks.worst(["off", "ok"]) == "ok"
        assert checks.worst(["off"]) == "ok"
        assert checks.worst(["ok", "warning", "error"]) == "error"

    def test_a_check_can_be_listed_in_the_settings(self, settings):
        settings.GENERIC = {
            "STATUS_CHECKS": ["tests.test_status.listed_check"]
        }
        found = {check["name"]: check for check in checks.run_checks()}

        assert found["tests.test_status.listed_check"]["detail"] == "listed"

    def test_declaring_a_check_again_replaces_it(self, declared):
        declared(lambda: "first", name="tests.twice", label="Twice")
        declared(lambda: "second", name="tests.twice", label="Twice")
        found = [
            check
            for check in checks.run_checks()
            if check["name"] == "tests.twice"
        ]

        assert [check["detail"] for check in found] == ["second"]

    def test_a_dummy_cache_is_off(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.dummy.DummyCache"
            }
        }

        assert checks.cache_check("default").run()["level"] == "off"

    def test_without_a_broker_celery_is_off(self):
        app = mock.Mock()
        app.conf = {"broker_url": "", "task_always_eager": False}

        with mock.patch.object(checks, "celery_app", return_value=app):
            assert checks.celery_check()[0] == "off"

    def test_a_broker_without_a_worker_needs_attention(self):
        app = mock.MagicMock()
        app.conf = {"broker_url": "redis://", "task_always_eager": False}
        app.control.ping.return_value = []

        with mock.patch.object(checks, "celery_app", return_value=app):
            assert checks.celery_check()[0] == "warning"

    def test_a_missing_media_folder_is_an_error(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path / "nowhere")

        assert checks.media_check()[0] == "error"


class FakeConnection:
    """A backend that speaks no plain SQL and says nothing of its version,
    like django-salesforce."""

    vendor = "salesforce"
    display_name = "Salesforce"

    class features:
        bare_select_suffix = ""

    def __init__(self):
        self.executed = []

    def cursor(self):
        connection = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, query):
                if query.startswith("SELECT 1"):
                    raise ValueError(f"invalid SQL: {query}")

                connection.executed.append(query)

            def fetchone(self):
                return ("00D000000000001",)

        return Cursor()

    def get_database_version(self):
        raise NotImplementedError


class TestADatabaseThatSpeaksNoSql:
    """A Salesforce database answered "invalid SQL: SELECT 1"."""

    @pytest.fixture
    def salesforce(self):
        connection = FakeConnection()

        with mock.patch(
            "generic.status.checks.connections",
            {"salesforce": connection},
        ):
            yield connection

    def test_salesforce_is_asked_in_soql(self, salesforce):
        result = checks.database_check("salesforce").run()

        assert result["level"] == "ok"
        assert result["detail"] == "Salesforce"
        assert salesforce.executed == ["SELECT Id FROM Organization LIMIT 1"]

    def test_the_project_may_give_the_query(self, salesforce, settings):
        settings.GENERIC = {
            "STATUS_DATABASE_QUERIES": {"salesforce": "SELECT Id FROM User"}
        }

        checks.database_check("salesforce").run()

        assert salesforce.executed == ["SELECT Id FROM User"]

    def test_none_leaves_a_database_out(self, settings):
        settings.GENERIC = {"STATUS_DATABASE_QUERIES": {"default": None}}
        names = {check["name"] for check in checks.run_checks()}

        assert "database.default" not in names
        assert "default" not in checks.database_aliases()

    def test_oracle_asks_from_dual(self):
        oracle = FakeConnection()
        oracle.vendor = "oracle"
        oracle.features = mock.Mock(bare_select_suffix=" FROM DUAL")

        with mock.patch(
            "generic.status.checks.connections", {"other": oracle}
        ):
            assert checks.probe_for("other") == "SELECT 1 FROM DUAL"


def listed_check():
    return "listed"


class TestTheMachine:
    def test_a_gauge_turns_by_the_thresholds(self, settings):
        settings.GENERIC = {"STATUS_THRESHOLDS": {"cpu": (50, 90)}}

        assert system_module.level_of("cpu", 10) == "ok"
        assert system_module.level_of("cpu", 50) == "warning"
        assert system_module.level_of("cpu", 95) == "error"
        assert system_module.level_of("cpu", None) == "ok"

    def test_two_places_on_one_disk_are_one_gauge(self, settings, tmp_path):
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        settings.GENERIC = {
            "STATUS_DISKS": [("A", str(first)), ("B", str(second))]
        }

        disks = system_module.disks()

        assert len(disks) == 1
        assert disks[0]["label"] == "A, B"

    def test_a_path_not_made_yet_is_measured_where_it_will_be(
        self, settings, tmp_path
    ):
        settings.GENERIC = {"STATUS_DISKS": [str(tmp_path / "later" / "x")]}

        assert system_module.disks()[0]["path"] == str(tmp_path)

    def test_without_psutil_the_figures_come_from_the_system(self):
        with mock.patch.object(system_module, "psutil", None):
            machine = system_module.system()

        assert machine["host"]["psutil"] is False
        assert machine["cpu"]["count"] >= 1
        assert machine["process"]["memory"] is None
        # Linux gives memory through /proc; elsewhere it is not measured.
        assert machine["memory"]["percent"] is None or (
            0 <= machine["memory"]["percent"] <= 100
        )


class TestTheEndpoint:
    def test_nobody_signed_in_is_asked_to_sign_in(self, client):
        assert client.get(STATUS).status_code == 401

    def test_an_account_without_the_permission_is_refused(self, auth_client):
        assert auth_client.get(STATUS).status_code == 403

    def test_the_permission_reads_it(self, watcher_client):
        response = watcher_client.get(STATUS)

        assert response.status_code == 200
        assert response.json()["format"] == FORMAT
        assert response["Cache-Control"] == "no-store"

    def test_another_server_reads_it_with_the_token(self, client, settings):
        settings.GENERIC = {"STATUS_TOKEN": "s3cret"}
        response = client.get(STATUS, headers={TOKEN_HEADER: "s3cret"})

        assert response.status_code == 200
        assert response.json()["server"]["api_url"].endswith(STATUS)

    def test_any_of_several_tokens_will_do(self, client, settings):
        settings.GENERIC = {"STATUS_TOKEN": ["old", "new"]}

        assert (
            client.get(STATUS, headers={TOKEN_HEADER: "old"}).status_code
            == 200
        )

    def test_a_wrong_token_is_refused(self, client, settings):
        settings.GENERIC = {"STATUS_TOKEN": "s3cret"}

        assert (
            client.get(STATUS, headers={TOKEN_HEADER: "guess"}).status_code
            == 403
        )

    def test_without_a_token_configured_none_is_accepted(self, client):
        assert (
            client.get(STATUS, headers={TOKEN_HEADER: ""}).status_code == 401
        )
        assert (
            client.get(STATUS, headers={TOKEN_HEADER: "None"}).status_code
            == 403
        )


class TestTheHealthCheck:
    def test_it_says_ok_to_anybody(self, client):
        response = client.get(HEALTH)

        assert response.status_code == 200
        assert response.json() == {"level": "ok"}

    def test_a_database_down_is_a_503(self, client):
        def down():
            raise RuntimeError("down")

        broken = checks.Check(
            name="database.default", label="x", function=down
        )

        with mock.patch(
            "generic.status.api.database_check", return_value=broken
        ):
            response = client.get(HEALTH)

        assert response.status_code == 503
        assert response.json() == {"level": "error"}


class TestTheAddressOfAnotherServer:
    @pytest.mark.parametrize(
        "typed, expected",
        [
            (
                "https://erp.example.com",
                "https://erp.example.com/api/generic/status/",
            ),
            (
                "https://erp.example.com/",
                "https://erp.example.com/api/generic/status/",
            ),
            (
                "https://erp.example.com/app/api/generic/status/",
                "https://erp.example.com/app/api/generic/status/",
            ),
        ],
    )
    def test_a_bare_site_gets_the_usual_endpoint(self, typed, expected):
        assert status_address(typed) == expected

    @pytest.mark.parametrize(
        "typed",
        ["file:///etc/passwd", "ftp://erp.example.com", "erp.example.com"],
    )
    def test_only_a_web_address_is_accepted(self, typed):
        with pytest.raises(ValidationError):
            validate_status_url(typed)

    def test_credentials_stay_out_of_the_address(self):
        with pytest.raises(ValidationError):
            validate_status_url("https://me:pw@erp.example.com")


class TestAskingAnotherServer:
    def test_its_status_comes_back_with_its_token_sent(self, products):
        with answering(a_status(level="warning")) as opened:
            card = fetch(products)

        request = opened.call_args.args[0]

        assert card["reachable"] is True
        assert card["level"] == "warning"
        assert card["status"]["server"]["title"] == "Products"
        assert request.full_url == (
            "https://products.example.com/api/generic/status/"
        )
        assert request.get_header(TOKEN_HEADER.capitalize()) == "s3cret"

    def test_an_answer_that_is_not_a_status_is_an_error(self, products):
        with answering({"hello": "world"}):
            card = fetch(products)

        assert card["reachable"] is False
        assert card["level"] == "error"
        assert "django-generic status" in card["error"]

    def test_a_page_of_html_is_an_error(self, products):
        with answering(body=b"<html>sign in</html>"):
            card = fetch(products)

        assert "status endpoint" in card["error"]

    def test_a_refusal_points_at_the_token(self, products):
        error = urllib.error.HTTPError(
            products.status_url, 403, "Forbidden", {}, None
        )

        with answering(error=error):
            card = fetch(products)

        assert "token" in card["error"]

    def test_a_server_that_is_down_says_why(self, products):
        with answering(error=urllib.error.URLError("Connection refused")):
            card = fetch(products)

        assert card["error"] == "Unreachable: Connection refused"

    def test_a_level_it_made_up_is_an_error(self, products):
        with answering(a_status(level="splendid")):
            assert fetch(products)["level"] == "error"

    def test_a_link_that_is_not_a_web_address_is_dropped(self, products):
        status = a_status()
        status["server"]["page_url"] = "javascript:alert(1)"

        with answering(status):
            card = fetch(products)

        assert card["status"]["server"]["page_url"] == ""
        assert card["status"]["server"]["site_url"] == (
            "https://products.example.com/"
        )

    def test_redirections_are_not_followed(self):
        handler = remote_module.NoRedirect()

        assert handler.redirect_request(None, None, 302, "", {}, "x") is None

    def test_an_answer_too_large_is_refused(self, products):
        with answering(body=b" " * (remote_module.MAX_BYTES + 10)):
            card = fetch(products)

        assert "too large" in card["error"]


class TestTheRemoteEndpoint:
    def test_it_answers_the_card(self, watcher_client, products):
        with answering(a_status()):
            response = watcher_client.get(
                f"/api/generic/status/servers/{products.pk}/"
            )

        assert response.status_code == 200
        assert response.json()["reachable"] is True
        assert "token" not in json.dumps(response.json()).lower()

    def test_it_needs_the_permission(self, auth_client, products):
        response = auth_client.get(
            f"/api/generic/status/servers/{products.pk}/"
        )

        assert response.status_code == 403

    def test_an_unknown_server_is_a_404(self, watcher_client):
        assert (
            watcher_client.get("/api/generic/status/servers/999/").status_code
            == 404
        )


class TestThePage:
    def test_it_lists_the_servers_shown(self, admin_client, products):
        StatusServer.objects.create(
            name="Hidden", url="https://hidden.example.com", is_active=False
        )

        response = admin_client.get(PAGE)
        config = response.context["status_config"]

        assert response.status_code == 200
        assert [server["name"] for server in config["servers"]] == ["Products"]
        assert config["localUrl"] == STATUS
        assert config["servers"][0]["changeUrl"]
        assert "s3cret" not in response.content.decode()

    def test_it_shows_the_address_to_plug_in(self, admin_client, settings):
        settings.GENERIC = {"STATUS_TOKEN": "s3cret"}
        plug = admin_client.get(PAGE).context["plug"]

        assert plug["address"] == "http://testserver/api/generic/status/"
        assert plug["has_token"] is True

    def test_a_reader_without_the_screen_gets_no_edit_link(
        self, watcher_client, products
    ):
        config = watcher_client.get(PAGE).context["status_config"]

        assert config["servers"][0]["changeUrl"] == ""

    def test_it_needs_the_permission(self, auth_client):
        assert auth_client.get(PAGE).status_code == 403

    def test_a_project_without_it_answers_404(self, admin_client, settings):
        settings.GENERIC = {"SHOW_STATUS": False}

        assert admin_client.get(PAGE).status_code == 404

    def test_it_is_in_the_navigation(self, admin_client):
        assert PAGE.encode() in admin_client.get("/").content


class TestTheServersScreen:
    def test_the_token_is_never_sent_back(self, admin_client, products):
        record = admin_client.get(f"{SERVERS}{products.pk}/").json()

        assert "token" not in record
        assert "s3cret" not in json.dumps(record)

    def test_an_empty_token_keeps_the_current_one(
        self, admin_client, products
    ):
        response = admin_client.patch(
            f"{SERVERS}{products.pk}/",
            {"name": "Renamed", "token": ""},
            content_type="application/json",
        )
        products.refresh_from_db()

        assert response.status_code == 200
        assert products.name == "Renamed"
        assert products.token == "s3cret"

    def test_a_new_token_replaces_it(self, admin_client, products):
        admin_client.patch(
            f"{SERVERS}{products.pk}/",
            {"token": "fresh"},
            content_type="application/json",
        )
        products.refresh_from_db()

        assert products.token == "fresh"

    def test_the_history_keeps_no_token(self, admin_client):
        admin_client.post(
            SERVERS,
            {
                "name": "Archive",
                "url": "https://archive.example.com",
                "token": "hidden",
            },
            content_type="application/json",
        )
        server = StatusServer.objects.get(name="Archive")

        entries = list(history_of(server))

        assert entries, "the server is in the history"
        assert "hidden" not in json.dumps(
            [entry.values for entry in entries], default=str
        )

    def test_a_file_address_is_refused(self, admin_client):
        response = admin_client.post(
            SERVERS,
            {"name": "Local", "url": "file:///etc/passwd"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_testing_the_connection_reports_each_server(
        self, admin_client, products
    ):
        down = StatusServer.objects.create(
            name="Down", url="https://down.example.com"
        )

        def open_(request, timeout):
            if "down" in request.full_url:
                raise urllib.error.URLError("refused")

            return Answer(json.dumps(a_status()).encode())

        with mock.patch.object(
            remote_module.opener, "open", side_effect=open_
        ):
            response = admin_client.post(
                f"{SERVERS}actions/",
                {"action": "test_connection", "ids": [products.pk, down.pk]},
                content_type="application/json",
            )

        report = response.json()["operation"]["report"]
        levels = {
            node["title"].split(":")[0]: node["level"] for node in report
        }

        assert response.status_code == 200
        assert levels == {"Products": "success", "Down": "error"}
