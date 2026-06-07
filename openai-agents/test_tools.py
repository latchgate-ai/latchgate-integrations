"""Tests for latchgate-openai-agents.

All tests are self-contained — no running LatchGate or OpenAI required.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from latchgate import (
    ActionResult,
    LatchGateApprovalRequired,
    LatchGateBudgetExhausted,
    LatchGateClient,
    LatchGateDenied,
    LatchGateUnavailable,
)
from latchgate_common.discovery import (
    ActionDescriptor,
    build_description,
    discover_actions,
)
from latchgate_common.serialization import serialize_result

from latchgate_openai_agents._factory import latchgate_tools, latchgate_tools_from_descriptors
from latchgate_openai_agents._tool import _to_strict_schema, create_tool

# ── Fixtures ──────────────────────────────────────────────────────────────

SAMPLE_ACTIONS_RESPONSE = {
    "actions": [
        {"action_id": "http_fetch", "version": "1.0.0", "risk_level": "low"},
        {"action_id": "send_message", "version": "1.0.0", "risk_level": "high"},
        {"action_id": "database", "version": "1.0.0", "risk_level": "medium"},
    ]
}

SAMPLE_HTTP_FETCH_SCHEMA = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string", "description": "Target URL"},
        "method": {"type": "string", "enum": ["GET", "HEAD"], "default": "GET"},
    },
}

SAMPLE_HTTP_FETCH_DETAIL = {
    "action_id": "http_fetch",
    "version": "1.0.0",
    "risk_level": "low",
    "declared_side_effects": ["http_read"],
    "egress": {"profile": "proxy_allowlist", "allowed_domains": ["api.github.com"]},
}

SAMPLE_DATABASE_DETAIL = {
    "action_id": "database",
    "version": "1.0.0",
    "risk_level": "medium",
    "declared_side_effects": ["database_write"],
    "database": {
        "mode": "hybrid",
        "statements": [
            {"id": "get_user", "operation": "select", "tables": ["users"], "param_count": 1}
        ],
        "allows_parameterized_queries": True,
        "parameterized_operations": ["select"],
    },
}

SAMPLE_ACTION_RESULT = ActionResult(
    output={"status": 200, "body": '{"ok": true}'},
    receipt_id="rcpt_01JTEST",
    trace_id="trace_01JTEST",
    grant_id="grant_01JTEST",
    verification={"outcome": "verified", "is_fully_successful": True},
    runtime={"duration_ms": 42, "exit_code": 0, "fuel_consumed": 1200},
)


def _mock_http(routes: dict[str, Any]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_http_with_errors(
    routes: dict[str, Any],
    error_paths: dict[str, Exception],
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in error_paths:
            raise error_paths[path]
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _full_discovery_routes() -> dict[str, Any]:
    return {
        "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
        "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
        "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
        "/v1/actions/send_message/schema/request": {"type": "object"},
        "/v1/actions/send_message": {"action_id": "send_message", "version": "1.0.0"},
        "/v1/actions/database/schema/request": {"type": "object"},
        "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
    }


def _make_descriptor(
    action_id: str = "http_fetch",
    schema: dict[str, Any] | None = None,
) -> ActionDescriptor:
    return ActionDescriptor(
        action_id=action_id,
        version="1.0.0",
        risk_level="low",
        request_schema=schema or SAMPLE_HTTP_FETCH_SCHEMA,
        description="Test tool",
    )


# ── Strict schema conversion tests ───────────────────────────────────────


class TestStrictSchema:
    def test_object_schema_strips_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "additionalProperties": True,
        }
        strict = _to_strict_schema(schema)
        assert strict["additionalProperties"] is False

    def test_object_schema_requires_all_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
            "required": ["a"],
        }
        strict = _to_strict_schema(schema)
        assert set(strict["required"]) == {"a", "b"}

    def test_non_object_schema_wrapped(self) -> None:
        strict = _to_strict_schema({"type": "string"})
        assert strict["type"] == "object"
        assert strict["properties"] == {}
        assert strict["additionalProperties"] is False
        assert strict["required"] == []

    def test_empty_object_schema(self) -> None:
        strict = _to_strict_schema({"type": "object"})
        assert strict["type"] == "object"
        assert strict["properties"] == {}
        assert strict["additionalProperties"] is False

    def test_permissive_fallback_becomes_strict(self) -> None:
        """The discovery permissive fallback must be convertible to strict."""
        permissive = {"type": "object", "additionalProperties": True}
        strict = _to_strict_schema(permissive)
        assert strict["additionalProperties"] is False
        assert strict["required"] == []

    def test_does_not_mutate_original(self) -> None:
        original = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "additionalProperties": True,
        }
        original_copy = json.loads(json.dumps(original))
        _to_strict_schema(original)
        assert original == original_copy

    def test_preserves_description(self) -> None:
        schema = {"type": "object", "properties": {}, "description": "My schema"}
        strict = _to_strict_schema(schema)
        assert strict["description"] == "My schema"

    def test_real_schema_passes_agents_sdk_validation(self) -> None:
        """Verify that the strict schema actually passes the Agents SDK validation."""
        from agents.strict_schema import ensure_strict_json_schema

        strict = _to_strict_schema(SAMPLE_HTTP_FETCH_SCHEMA)
        # Should not raise
        ensure_strict_json_schema(strict)

    def test_permissive_fallback_passes_agents_sdk_validation(self) -> None:
        from agents.strict_schema import ensure_strict_json_schema

        permissive = {"type": "object", "additionalProperties": True}
        strict = _to_strict_schema(permissive)
        ensure_strict_json_schema(strict)


# ── Tool creation tests ──────────────────────────────────────────────────


class TestCreateTool:
    def test_creates_function_tool(self) -> None:
        from agents import FunctionTool

        client = AsyncMock(spec=LatchGateClient)
        tool = create_tool(_make_descriptor(), client)

        assert isinstance(tool, FunctionTool)
        assert tool.name == "http_fetch"
        assert tool.description == "Test tool"

    def test_schema_is_strict(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        tool = create_tool(_make_descriptor(), client)
        assert tool.params_json_schema["type"] == "object"
        assert tool.params_json_schema["additionalProperties"] is False
        assert "url" in tool.params_json_schema.get("properties", {})

    def test_invalid_schema_gets_wrapped(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        descriptor = _make_descriptor(schema={"type": "string"})
        tool = create_tool(descriptor, client)
        assert tool.params_json_schema["type"] == "object"
        assert tool.params_json_schema["additionalProperties"] is False

    def test_permissive_schema_becomes_strict(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        descriptor = _make_descriptor(schema={"type": "object", "additionalProperties": True})
        tool = create_tool(descriptor, client)
        assert tool.params_json_schema["additionalProperties"] is False


# ── Tool invocation tests ────────────────────────────────────────────────


class TestToolInvocation:
    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), '{"url": "https://httpbin.org/get"}')
        parsed = json.loads(result)
        assert parsed == SAMPLE_ACTION_RESULT.output
        assert "receipt_id" not in result
        client.execute.assert_awaited_once_with("http_fetch", {"url": "https://httpbin.org/get"})

    @pytest.mark.asyncio
    async def test_denied_returns_error(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateDenied("http_fetch", "policy_violation"))
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), '{"url": "https://evil.com"}')
        assert "ERROR" in result
        assert "denied" in result.lower()
        assert "policy_violation" in result

    @pytest.mark.asyncio
    async def test_approval_required_excludes_approval_id(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(
            side_effect=LatchGateApprovalRequired("send_message", "apr_01JTEST")
        )
        tool = create_tool(_make_descriptor("send_message"), client)

        result = await tool.on_invoke_tool(AsyncMock(), "{}")
        assert "approval" in result.lower()
        assert "apr_01JTEST" not in result
        assert "approval_id" not in result

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_error(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateBudgetExhausted("http_fetch"))
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), "{}")
        assert "budget" in result.lower()

    @pytest.mark.asyncio
    async def test_unavailable_returns_error(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("redis_down"))
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), "{}")
        assert "redis_down" in result

    @pytest.mark.asyncio
    async def test_invalid_json_input_returns_error(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), "not-json{{{")
        assert "ERROR" in result
        assert "Invalid JSON" in result

    @pytest.mark.asyncio
    async def test_empty_input_passes_empty_dict(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = create_tool(_make_descriptor(), client)

        await tool.on_invoke_tool(AsyncMock(), "")
        client.execute.assert_awaited_once_with("http_fetch", {})

    @pytest.mark.asyncio
    async def test_no_exception_propagates(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("opa_down"))
        tool = create_tool(_make_descriptor(), client)

        result = await tool.on_invoke_tool(AsyncMock(), "{}")
        assert isinstance(result, str)
        assert "ERROR" in result

    @pytest.mark.asyncio
    async def test_all_kwargs_forwarded(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = create_tool(_make_descriptor(), client)

        await tool.on_invoke_tool(AsyncMock(), '{"url": "https://x.com", "method": "HEAD"}')
        client.execute.assert_awaited_once_with(
            "http_fetch", {"url": "https://x.com", "method": "HEAD"}
        )

    @pytest.mark.asyncio
    async def test_audit_callback_invoked_on_success(self) -> None:
        """on_audit receives a correct AuditRecord after successful execution."""
        from latchgate_common.audit import AuditRecord

        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        audit_cb = Mock()

        tool = create_tool(_make_descriptor(), client, on_audit=audit_cb)

        await tool.on_invoke_tool(AsyncMock(), '{"url": "https://example.com"}')

        audit_cb.assert_called_once()
        record = audit_cb.call_args[0][0]
        assert isinstance(record, AuditRecord)
        assert record.action_id == "http_fetch"
        assert record.receipt_id == "rcpt_01JTEST"
        assert record.trace_id == "trace_01JTEST"

    @pytest.mark.asyncio
    async def test_audit_callback_not_invoked_on_error(self) -> None:
        """on_audit is NOT called when the action is denied."""
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateDenied("http_fetch", "denied"))
        audit_cb = Mock()

        tool = create_tool(_make_descriptor(), client, on_audit=audit_cb)

        await tool.on_invoke_tool(AsyncMock(), '{"url": "https://evil.com"}')
        audit_cb.assert_not_called()


# ── Result serialization ─────────────────────────────────────────────────


class TestResultSerialization:
    def test_returns_only_output(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        parsed = json.loads(text)
        assert parsed == SAMPLE_ACTION_RESULT.output

    def test_excludes_receipt_metadata(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        assert "receipt_id" not in text
        assert "rcpt_" not in text
        assert "trace_id" not in text

    def test_excludes_verification(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        assert "verification" not in text
        assert "is_fully_successful" not in text

    def test_produces_valid_json(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        parsed = json.loads(text)
        assert set(parsed.keys()) == {"status", "body"}


# ── Factory tests ─────────────────────────────────────────────────────────


class TestFactory:
    def test_from_descriptors(self) -> None:
        from agents import FunctionTool

        client = AsyncMock(spec=LatchGateClient)
        descriptors = [_make_descriptor("http_fetch"), _make_descriptor("send_message")]

        tools = latchgate_tools_from_descriptors(descriptors, client=client)
        assert len(tools) == 2
        assert all(isinstance(t, FunctionTool) for t in tools)
        assert tools[0].name == "http_fetch"
        assert tools[1].name == "send_message"

    def test_empty_descriptors(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        tools = latchgate_tools_from_descriptors([], client=client)
        assert tools == []

    @pytest.mark.asyncio
    async def test_latchgate_tools_with_mocked_discovery(self) -> None:
        """Test the async latchgate_tools() factory end-to-end."""
        http = _mock_http(_full_discovery_routes())

        with patch("latchgate_common.discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            tools = await latchgate_tools(gate_url="http://localhost:3000")
            assert len(tools) == 3
            names = {t.name for t in tools}
            assert names == {"http_fetch", "send_message", "database"}

    @pytest.mark.asyncio
    async def test_latchgate_tools_falls_back_to_default_transport(self) -> None:
        """Without gate_url, client, or LATCHGATE_URL, latchgate_tools() falls
        back to the default local transport (UDS) and raises a connection error
        when no gate is running."""
        with pytest.raises((httpx.ConnectError, httpx.TransportError, OSError)):
            await latchgate_tools()

    @pytest.mark.asyncio
    async def test_latchgate_tools_discovers_via_client_transport(self) -> None:
        """When client is passed without gate_url, discovery reuses the client's
        internal httpx transport (UDS-compatible)."""
        http = _mock_http(_full_discovery_routes())
        client = AsyncMock(spec=LatchGateClient)
        client.gate_url = "http://localhost"
        client.http_transport = http

        tools = await latchgate_tools(client=client)
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_latchgate_tools_with_include(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
                "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
                "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
            }
        )

        with patch("latchgate_common.discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            tools = await latchgate_tools(gate_url="http://localhost:3000", include={"http_fetch"})
            assert len(tools) == 1
            assert tools[0].name == "http_fetch"


# ── Discovery tests ──────────────────────────────────────────────────────


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_all_actions(self) -> None:
        http = _mock_http(_full_discovery_routes())
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert len(descriptors) == 3

    @pytest.mark.asyncio
    async def test_discover_with_include(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
                "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
                "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000", include={"http_fetch"}, _http=http
        )
        assert len(descriptors) == 1

    @pytest.mark.asyncio
    async def test_discover_with_exclude(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
                "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
                "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
                "/v1/actions/send_message/schema/request": {"type": "object"},
                "/v1/actions/send_message": {"action_id": "send_message"},
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000", exclude={"database"}, _http=http
        )
        assert len(descriptors) == 2
        assert "database" not in {d.action_id for d in descriptors}

    @pytest.mark.asyncio
    async def test_schema_fallback(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [{"action_id": "x", "version": "1.0.0", "risk_level": "low"}]
                },
                "/v1/actions/x": {"action_id": "x"},
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000", allow_schemaless=True, _http=http
        )
        assert descriptors[0].request_schema.get("additionalProperties") is True

    @pytest.mark.asyncio
    async def test_schema_fetch_failure_skips_by_default(self) -> None:
        """Default allow_schemaless=False rejects actions without schemas."""
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [{"action_id": "x", "version": "1.0.0", "risk_level": "low"}]
                },
                "/v1/actions/x": {"action_id": "x"},
            }
        )
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert len(descriptors) == 0

    @pytest.mark.asyncio
    async def test_description_with_database(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [
                        {"action_id": "database", "version": "1.0.0", "risk_level": "medium"}
                    ]
                },
                "/v1/actions/database/schema/request": {"type": "object"},
                "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
            }
        )
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert "hybrid" not in descriptors[0].description
        assert "get_user" not in descriptors[0].description

    @pytest.mark.asyncio
    async def test_description_with_database_debug(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [
                        {"action_id": "database", "version": "1.0.0", "risk_level": "medium"}
                    ]
                },
                "/v1/actions/database/schema/request": {"type": "object"},
                "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000",
            expose_security_details="debug",
            _http=http,
        )
        assert "hybrid" in descriptors[0].description
        assert "get_user" in descriptors[0].description

    @pytest.mark.asyncio
    async def test_empty_actions(self) -> None:
        http = _mock_http({"/v1/actions": {"actions": []}})
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert descriptors == []

    @pytest.mark.asyncio
    async def test_transport_error_propagates(self) -> None:
        http = _mock_http_with_errors(
            routes={},
            error_paths={"/v1/actions": httpx.ConnectError("connection refused")},
        )
        with pytest.raises(httpx.ConnectError):
            await discover_actions("http://localhost:3000", _http=http)

    @pytest.mark.asyncio
    async def test_schema_transport_error_uses_fallback(self) -> None:
        http = _mock_http_with_errors(
            routes={
                "/v1/actions": {
                    "actions": [{"action_id": "flaky", "version": "1.0.0", "risk_level": "low"}]
                },
                "/v1/actions/flaky": {"action_id": "flaky"},
            },
            error_paths={"/v1/actions/flaky/schema/request": httpx.ReadTimeout("timeout")},
        )
        descriptors = await discover_actions(
            "http://localhost:3000", allow_schemaless=True, _http=http
        )
        assert len(descriptors) == 1
        assert descriptors[0].request_schema["additionalProperties"] is True

    @pytest.mark.asyncio
    async def test_description_builder_basic(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", None)
        assert "http_fetch" in desc
        assert "audit receipts" in desc

    @pytest.mark.asyncio
    async def test_description_builder_default_redacts_egress(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", SAMPLE_HTTP_FETCH_DETAIL)
        assert "proxy_allowlist" not in desc
        assert "api.github.com" not in desc
        assert "http_read" in desc

    @pytest.mark.asyncio
    async def test_description_builder_debug_includes_egress(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", SAMPLE_HTTP_FETCH_DETAIL, "debug")
        assert "proxy_allowlist" in desc
        assert "api.github.com" in desc
