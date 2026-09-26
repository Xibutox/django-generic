"""Topic registry: a client may only join what the project declared."""

from __future__ import annotations

import pytest

from generic.events.registry import (
    TopicRegistry,
    allow_authenticated,
    allow_staff,
)


class FakeUser:
    def __init__(self, authenticated=True, staff=False):
        self.is_authenticated = authenticated
        self.is_staff = staff


class TestRegistration:
    def test_a_topic_can_be_declared_and_found(self):
        registry = TopicRegistry()
        registry.register("audit.log")

        assert registry.get("audit.log") is not None
        assert len(registry) == 1

    def test_registering_the_same_topic_twice_is_idempotent(self):
        registry = TopicRegistry()
        registry.register("audit.log")
        registry.register("audit.log")

        assert len(registry) == 1

    def test_a_conflicting_redeclaration_is_refused(self):
        registry = TopicRegistry()
        registry.register("audit.log")

        with pytest.raises(ValueError, match="already registered"):
            registry.register("audit.log", permission=allow_staff)

    def test_placeholders_become_parameters(self):
        registry = TopicRegistry()
        topic = registry.register("project.{project_id}")

        assert topic.parameters == ("project_id",)


class TestGroupNames:
    def test_a_plain_topic_maps_to_a_namespaced_group(self):
        registry = TopicRegistry()
        topic = registry.register("audit.log")

        assert topic.group_name() == "generic.topic.audit.log"

    def test_parameters_are_interpolated(self):
        registry = TopicRegistry()
        topic = registry.register("project.{project_id}")

        assert (
            topic.group_name({"project_id": "12"})
            == "generic.topic.project.12"
        )

    def test_a_missing_parameter_is_refused(self):
        registry = TopicRegistry()
        topic = registry.register("project.{project_id}")

        with pytest.raises(ValueError, match="needs parameters"):
            topic.group_name()

    def test_an_illegal_parameter_value_is_refused(self):
        """Channels rejects group names outside a fixed alphabet."""
        registry = TopicRegistry()
        topic = registry.register("project.{project_id}")

        with pytest.raises(ValueError, match="not a valid topic name"):
            topic.group_name({"project_id": "12 OR 1=1"})


class TestResolution:
    def test_a_plain_name_resolves(self):
        registry = TopicRegistry()
        registry.register("audit.log")

        topic, parameters = registry.resolve("audit.log")

        assert topic.name == "audit.log"
        assert parameters == {}

    def test_a_parameterised_name_resolves(self):
        registry = TopicRegistry()
        registry.register("project.{project_id}")

        topic, parameters = registry.resolve("project.12")

        assert topic.name == "project.{project_id}"
        assert parameters == {"project_id": "12"}

    def test_an_undeclared_name_does_not_resolve(self):
        registry = TopicRegistry()
        registry.register("audit.log")

        assert registry.resolve("secrets") is None

    def test_a_partial_match_does_not_resolve(self):
        registry = TopicRegistry()
        registry.register("project.{project_id}")

        assert registry.resolve("project.12.secrets") is None


class TestPermissions:
    def test_authenticated_is_the_default_rule(self):
        registry = TopicRegistry()
        topic = registry.register("audit.log")

        assert topic.allows(FakeUser(), {}) is True
        assert topic.allows(FakeUser(authenticated=False), {}) is False
        assert topic.allows(None, {}) is False

    def test_staff_only_topics(self):
        registry = TopicRegistry()
        topic = registry.register("audit.log", permission=allow_staff)

        assert topic.allows(FakeUser(staff=True), {}) is True
        assert topic.allows(FakeUser(staff=False), {}) is False

    def test_a_custom_rule_receives_the_parameters(self):
        seen = {}

        def only_project_12(user, name, parameters):
            seen.update(parameters)
            return parameters.get("project_id") == "12"

        registry = TopicRegistry()
        topic = registry.register(
            "project.{project_id}",
            permission=only_project_12,
        )

        assert topic.allows(FakeUser(), {"project_id": "12"}) is True
        assert topic.allows(FakeUser(), {"project_id": "13"}) is False
        assert seen == {"project_id": "13"}


def test_allow_authenticated_rejects_anonymous():
    assert allow_authenticated(None, "x", {}) is False
