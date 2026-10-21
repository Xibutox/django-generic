"""COMET and DES, the two business tools whose use the key figures
count: sign in, read ``status/``, sign out.

Every address and secret comes from the environment - nothing is
written here:

    COMET_API_URL   the API's root, ending in /api/
    COMET_USERNAME, COMET_PASSWORD
    DES_API_URL     the same for DES
    DES_USERNAME, DES_PASSWORD
    KPI_SYNC_VERIFY_TLS   "1" (default) checks the certificates; "0"
                          does not, as the old planner did - better, a
                          CA bundle: KPI_SYNC_CA_BUNDLE=/path/to/ca.pem
    KPI_SYNC_TIMEOUT      seconds, 30 by default

As the old planner did, the calls go straight to the tools, past any
HTTP proxy.
"""

from __future__ import annotations

import os
from typing import Any

#: Past any proxy the environment names: the tools are internal.
NO_PROXY = {"http": "", "https": ""}


class ToolError(Exception):
    pass


class Tool:
    """One tool's API, used for its ``status/`` only."""

    def __init__(self, name: str) -> None:
        import requests

        prefix = name.upper()
        self.name = name
        self.url = os.environ.get(f"{prefix}_API_URL", "")
        self.username = os.environ.get(f"{prefix}_USERNAME", "")
        self.password = os.environ.get(f"{prefix}_PASSWORD", "")
        self.session = requests.Session()
        self.options: dict[str, Any] = {
            "proxies": NO_PROXY,
            "verify": verify(),
            "timeout": float(os.environ.get("KPI_SYNC_TIMEOUT", "30")),
        }

    def __enter__(self) -> "Tool":
        if not self.url:
            raise ToolError(f"{self.name}: set {self.name.upper()}_API_URL.")

        if not self.url.endswith("/"):
            self.url += "/"

        if not self.username or not self.password:
            raise ToolError(
                f"{self.name}: set {self.name.upper()}_USERNAME and "
                f"{self.name.upper()}_PASSWORD."
            )

        response = self.session.post(
            self.url + "auth/login/",
            data={"username": self.username, "password": self.password},
            **self.options,
        )

        if response.status_code != 200:
            raise ToolError(
                f"{self.name}: sign-in refused ({response.status_code})."
            )

        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.session.post(self.url + "auth/logout/", **self.options)
        finally:
            self.session.close()

    def status(self) -> dict[str, Any]:
        response = self.session.get(self.url + "status/", **self.options)

        if response.status_code != 200:
            raise ToolError(
                f"{self.name}: status/ answered {response.status_code}."
            )

        return response.json()


def verify() -> Any:
    bundle = os.environ.get("KPI_SYNC_CA_BUNDLE")

    if bundle:
        return bundle

    return os.environ.get("KPI_SYNC_VERIFY_TLS", "1") != "0"


def comet() -> Tool:
    return Tool("comet")


def des() -> Tool:
    return Tool("des")
