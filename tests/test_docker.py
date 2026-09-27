"""The production stacks: Caddy's and nginx's, kept the same elsewhere.

``docker-compose.prod-nginx.yml`` is a copy of ``docker-compose.prod.yml``
with nginx in place of Caddy - a copy people read on their own, so
nothing but the proxy may drift. And the nginx configuration keeps what
the application needs from any proxy: the WebSocket, the scheme and the
client's address set by nginx alone, uploads the size imports send.
CI runs ``nginx -t`` on it (.github/workflows/ci.yml, job nginx).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

DOCKER = Path(__file__).resolve().parent.parent / "docker"
NGINX = DOCKER / "nginx"


def compose(name: str) -> dict:
    return yaml.safe_load((DOCKER / name).read_text())


class TestTheTwoStacks:
    def test_everything_but_the_proxy_is_the_same(self):
        caddy = compose("docker-compose.prod.yml")
        nginx = compose("docker-compose.prod-nginx.yml")

        for stack in (caddy, nginx):
            del stack["services"]["proxy"]
            del stack["name"]
            for volume in ("caddy-data", "caddy-config"):
                stack["volumes"].pop(volume, None)

        assert nginx == caddy

    def test_nginx_takes_the_proxy_s_place(self):
        proxy = compose("docker-compose.prod-nginx.yml")["services"]["proxy"]

        assert proxy["build"]["target"] == "nginx"
        assert proxy["depends_on"] == {"web": {"condition": "service_healthy"}}

    def test_behind_the_server_s_own_nginx(self):
        override = compose("docker-compose.host-nginx.yml")["services"]

        # The stack's proxy is not started, Daphne is reachable from
        # this machine only, and the static files are handed over.
        assert override["proxy"] == {"profiles": ["bundled-proxy"]}
        assert override["web"]["ports"] == ["127.0.0.1:${WEB_PORT:-8000}:8000"]
        assert override["static"]["build"]["target"] == "prod"


class TestTheNginxConfiguration:
    def conf(self) -> str:
        return (NGINX / "django-generic.conf").read_text()

    def location(self, path: str) -> str:
        match = re.search(
            rf"location {re.escape(path)} \{{(.*?)\n\}}", self.conf(), re.S
        )
        assert match, path

        return match.group(1)

    def test_uploads_the_size_imports_send(self):
        """nginx refuses bodies above 1 MB unless told; an import may
        send IMPORT_MAX_FILE_SIZE (5 MB)."""
        from generic.conf import DEFAULTS

        size = re.search(r"client_max_body_size (\d+)m;", self.conf())

        assert int(size.group(1)) * 1024 * 1024 > (
            DEFAULTS["IMPORT_MAX_FILE_SIZE"]
        )

    def test_the_websocket_is_upgraded_and_kept_open(self):
        from generic.conf import DEFAULTS

        socket = self.location(
            DEFAULTS["EVENTS_WEBSOCKET_URL"].rsplit("/", 2)[0] + "/"
        )

        assert "proxy_set_header Upgrade $http_upgrade;" in socket
        assert 'proxy_set_header Connection "upgrade";' in socket
        # Longer than nginx's 60 seconds: a quiet page keeps its socket.
        assert "proxy_read_timeout 1h;" in socket

    @pytest.mark.parametrize("path", ["/ws/", "/"])
    def test_what_django_trusts_is_what_nginx_saw(self, path):
        """The prod settings trust X-Forwarded-Proto
        (SECURE_PROXY_SSL_HEADER), and Daphne --proxy-headers the
        client's address: set, never appended to a client's own."""
        block = self.location(path)

        assert "proxy_set_header X-Forwarded-Proto $scheme;" in block
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in block
        assert "proxy_set_header Host $host;" in block
        assert "proxy_pass http://$generic_upstream;" in block

    @pytest.mark.parametrize(
        "name",
        [
            "https.conf.template",
            "http.conf.template",
            "host-site.conf.example",
        ],
    )
    def test_each_server_block_names_its_upstream(self, name):
        text = (NGINX / name).read_text()
        upstream = re.search(r"upstream (\w+) \{", text).group(1)

        assert f"set $generic_upstream {upstream};" in text
        assert "django-generic.conf;" in text
        assert "location /static/" in text or "static.conf;" in text

    def test_the_image_copies_what_exists(self):
        dockerfile = (DOCKER / "Dockerfile").read_text()
        stage = dockerfile.split("AS nginx", 1)[1].split("\nFROM ", 1)[0]

        for source in re.findall(r"docker/nginx/[\w.-]+", stage):
            assert (DOCKER.parent / source).is_file(), source
