"""Tests for action discovery — identifier safety, description redaction, HTTP flow.

Security-critical behaviors tested here:

1. _is_safe_identifier rejects path traversal and injection attempts
2. build_description omits enforcement topology in default mode
3. discover_actions skips actions with unsafe identifiers
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest

from latchgate_common.discovery import (
    _filter_actions,
    _is_safe_identifier,
    build_description,
    discover_actions,
)

# ── Identifier validation ─────────────────────────────────────────────────


class TestIsSafeIdentifier:
    """Path traversal and injection defense for action_id URL interpolation."""

    @pytest.mark.parametrize(
        "value",
        [
            "http_fetch",
            "send-email",
            "db.query.select",
            "Action_v2",
            "a",
            "1password_lookup",
        ],
    )
    def test_valid_identifiers(self, value: str) -> None:
        assert _is_safe_identifier(value) is True

    @pytest.mark.parametrize(
        "value,reason",
        [
            ("", "empty string"),
            ("../../admin", "path traversal"),
            ("../etc/passwd", "path traversal"),
            ("action/nested", "forward slash"),
            ("action\\nested", "backslash"),
            ("action?q=1", "query string"),
            ("action#frag", "fragment"),
            ("action id", "space"),
            ("-starts-with-hyphen", "leading hyphen"),
            (".dotfile", "leading dot"),
            ("_leading", "leading underscore"),
            ("a" * 257, "exceeds 256 chars"),
        ],
    )
    def test_rejects_unsafe(self, value: str, reason: str) -> None:
        assert _is_safe_identifier(value) is False, reason

    def test_max_length_accepted(self) -> None:
        assert _is_safe_identifier("a" * 256) is True

    def test_one_over_max_rejected(self) -> None:
        assert _is_safe_identifier("a" * 257) is False


# ── Filter actions ────────────────────────────────────────────────────────


class TestFilterActions:
    ACTIONS: ClassVar[list[dict[str, str]]] = [
        {"action_id": "http_fetch"},
        {"action_id": "send_email"},
        {"action_id": "db_query"},
    ]

    def test_no_filters(self) -> None:
        assert _filter_actions(self.ACTIONS, None, None) == self.ACTIONS

    def test_include(self) -> None:
        result = _filter_actions(self.ACTIONS, {"http_fetch", "db_query"}, None)
        ids = [a["action_id"] for a in result]
        assert ids == ["http_fetch", "db_query"]

    def test_exclude(self) -> None:
        result = _filter_actions(self.ACTIONS, None, {"send_email"})
        ids = [a["action_id"] for a in result]
        assert ids == ["http_fetch", "db_query"]

    def test_include_then_exclude(self) -> None:
        result = _filter_actions(self.ACTIONS, {"http_fetch", "send_email"}, {"send_email"})
        ids = [a["action_id"] for a in result]
        assert ids == ["http_fetch"]


# ── Description redaction ─────────────────────────────────────────────────


class TestBuildDescriptionRedaction:
    """build_description must omit enforcement topology when security_detail='none'."""

    DETAIL: ClassVar[dict[str, Any]] = {
        "declared_side_effects": ["http_read"],
        "egress": {
            "profile": "proxy_allowlist",
            "allowed_domains": ["api.github.com", "internal.corp"],
        },
        "database": {
            "mode": "prepared_statements",
            "statements": [{"id": "get_user"}, {"id": "list_orders"}],
            "allows_parameterized_queries": True,
            "parameterized_operations": ["SELECT", "INSERT"],
        },
    }

    def test_none_omits_egress_profile(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "proxy_allowlist" not in desc

    def test_none_omits_allowed_domains(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "api.github.com" not in desc
        assert "internal.corp" not in desc

    def test_none_omits_database_mode(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "prepared_statements" not in desc

    def test_none_omits_statement_ids(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "get_user" not in desc
        assert "list_orders" not in desc

    def test_none_omits_parameterized_operations(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "SELECT" not in desc
        assert "INSERT" not in desc

    def test_none_includes_side_effects(self) -> None:
        """Side effects are operational metadata, not enforcement topology."""
        desc = build_description("act", "1.0", "low", self.DETAIL, "none")
        assert "http_read" in desc

    def test_none_includes_action_id_and_risk(self) -> None:
        desc = build_description("act", "1.0", "high", self.DETAIL, "none")
        assert "act" in desc
        assert "high" in desc

    def test_debug_includes_egress(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "debug")
        assert "proxy_allowlist" in desc
        assert "api.github.com" in desc

    def test_debug_includes_database(self) -> None:
        desc = build_description("act", "1.0", "low", self.DETAIL, "debug")
        assert "prepared_statements" in desc
        assert "get_user" in desc
        assert "list_orders" in desc
        assert "SELECT" in desc

    def test_no_detail(self) -> None:
        desc = build_description("act", "1.0", "low", None, "none")
        assert "act" in desc
        assert "audit receipts" in desc

    def test_empty_detail(self) -> None:
        desc = build_description("act", "1.0", "low", {}, "none")
        assert "act" in desc


# ── Full discovery flow ───────────────────────────────────────────────────


def _mock_gate(
    actions: list[dict[str, Any]],
    schemas: dict[str, dict[str, Any]] | None = None,
    details: dict[str, dict[str, Any]] | None = None,
    fail_schemas: set[str] | None = None,
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient with mocked gate endpoints."""
    schemas = schemas or {}
    details = details or {}
    fail_schemas = fail_schemas or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/v1/actions":
            return httpx.Response(200, json={"actions": actions})

        # /v1/actions/{id}/schema/request
        for aid, schema in schemas.items():
            if path == f"/v1/actions/{aid}/schema/request":
                if aid in fail_schemas:
                    return httpx.Response(500)
                return httpx.Response(200, json=schema)

        # /v1/actions/{id}
        for aid, detail in details.items():
            if path == f"/v1/actions/{aid}":
                return httpx.Response(200, json=detail)

        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


BASIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["url"],
    "properties": {"url": {"type": "string"}},
}


class TestDiscoverActions:
    async def test_happy_path(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "http_fetch", "version": "1.0.0", "risk_level": "low"}],
            schemas={"http_fetch": BASIC_SCHEMA},
            details={"http_fetch": {"declared_side_effects": ["http_read"]}},
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "http_fetch"
        assert descriptors[0].version == "1.0.0"
        assert descriptors[0].risk_level == "low"
        assert descriptors[0].request_schema == BASIC_SCHEMA

    async def test_multiple_actions(self) -> None:
        client = _mock_gate(
            actions=[
                {"action_id": "http_fetch", "version": "1.0.0", "risk_level": "low"},
                {"action_id": "send_email", "version": "2.0.0", "risk_level": "high"},
            ],
            schemas={
                "http_fetch": BASIC_SCHEMA,
                "send_email": {"type": "object", "properties": {"to": {"type": "string"}}},
            },
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert len(descriptors) == 2
        assert {d.action_id for d in descriptors} == {"http_fetch", "send_email"}

    async def test_include_filter(self) -> None:
        client = _mock_gate(
            actions=[
                {"action_id": "http_fetch"},
                {"action_id": "send_email"},
            ],
            schemas={"http_fetch": BASIC_SCHEMA, "send_email": BASIC_SCHEMA},
        )
        descriptors = await discover_actions(
            "http://testgate", include={"http_fetch"}, _http=client
        )
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "http_fetch"

    async def test_exclude_filter(self) -> None:
        client = _mock_gate(
            actions=[
                {"action_id": "http_fetch"},
                {"action_id": "send_email"},
            ],
            schemas={"http_fetch": BASIC_SCHEMA, "send_email": BASIC_SCHEMA},
        )
        descriptors = await discover_actions(
            "http://testgate", exclude={"send_email"}, _http=client
        )
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "http_fetch"

    async def test_empty_actions_returns_empty(self) -> None:
        client = _mock_gate(actions=[])
        descriptors = await discover_actions("http://testgate", _http=client)
        assert descriptors == []

    async def test_unsafe_identifier_skipped(self) -> None:
        """Actions with path-traversal IDs must be silently skipped."""
        client = _mock_gate(
            actions=[
                {"action_id": "../../admin"},
                {"action_id": "http_fetch"},
            ],
            schemas={"http_fetch": BASIC_SCHEMA},
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "http_fetch"

    async def test_missing_schema_skipped_by_default(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "no_schema"}, {"action_id": "has_schema"}],
            schemas={"has_schema": BASIC_SCHEMA},
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "has_schema"

    async def test_schemaless_allowed(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "no_schema"}],
            schemas={},
        )
        descriptors = await discover_actions("http://testgate", allow_schemaless=True, _http=client)
        assert len(descriptors) == 1
        assert descriptors[0].request_schema["type"] == "object"
        assert descriptors[0].request_schema["additionalProperties"] is True

    async def test_schema_fetch_failure_skips_action(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "broken"}],
            schemas={"broken": BASIC_SCHEMA},
            fail_schemas={"broken"},
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert descriptors == []

    async def test_missing_version_defaults(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "bare"}],
            schemas={"bare": BASIC_SCHEMA},
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert descriptors[0].version == "0.0.0"
        assert descriptors[0].risk_level == "unknown"

    async def test_description_uses_none_security_detail_by_default(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "act", "version": "1.0", "risk_level": "high"}],
            schemas={"act": BASIC_SCHEMA},
            details={
                "act": {
                    "egress": {
                        "profile": "secret_profile",
                        "allowed_domains": ["secret.internal"],
                    },
                }
            },
        )
        descriptors = await discover_actions("http://testgate", _http=client)
        assert "secret_profile" not in descriptors[0].description
        assert "secret.internal" not in descriptors[0].description

    async def test_trailing_slash_on_gate_url(self) -> None:
        client = _mock_gate(
            actions=[{"action_id": "act"}],
            schemas={"act": BASIC_SCHEMA},
        )
        descriptors = await discover_actions("http://testgate/", _http=client)
        assert len(descriptors) == 1
