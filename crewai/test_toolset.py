"""Tests for latchgate-crewai.

Unit tests are self-contained — no running LatchGate instance required.
HTTP discovery is mocked via httpx.MockTransport, and the LatchGateClient
is mocked at the SDK level.
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
from latchgate_common.schema import schema_to_pydantic
from latchgate_common.serialization import serialize_result
from pydantic import BaseModel

from latchgate_crewai._tool import LatchGateTool
from latchgate_crewai._toolset import LatchGateToolset

# ── Fixtures ──────────────────────────────────────────────────────────────


SAMPLE_ACTIONS_RESPONSE = {
    "actions": [
        {"action_id": "http_fetch", "version": "1.0.0", "risk_level": "low"},
        {"action_id": "send_message", "version": "1.0.0", "risk_level": "high"},
        {
            "action_id": "database",
            "version": "1.0.0",
            "risk_level": "medium",
            "database_mode": "hybrid",
        },
    ]
}

SAMPLE_HTTP_FETCH_SCHEMA = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string", "description": "Target URL"},
        "method": {
            "type": "string",
            "enum": ["GET", "HEAD"],
            "default": "GET",
            "description": "HTTP method",
        },
        "headers": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Request headers",
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "default": 10,
            "description": "Request timeout",
        },
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
            {"id": "get_user", "operation": "select", "tables": ["users"], "param_count": 1},
            {
                "id": "update_order_status",
                "operation": "update",
                "tables": ["orders"],
                "param_count": 2,
            },
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
    """Create a mock httpx.AsyncClient backed by route-based responses."""

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
    """Mock client that raises exceptions for specific paths."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in error_paths:
            raise error_paths[path]
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _full_discovery_routes() -> dict[str, Any]:
    """Routes needed for full 3-action discovery."""
    return {
        "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
        "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
        "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
        "/v1/actions/send_message/schema/request": {"type": "object"},
        "/v1/actions/send_message": {
            "action_id": "send_message",
            "version": "1.0.0",
            "risk_level": "high",
        },
        "/v1/actions/database/schema/request": {"type": "object"},
        "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
    }


def _make_tool(mock_client: LatchGateClient) -> LatchGateTool:
    """Helper to create a tool from the standard http_fetch descriptor."""
    descriptor = ActionDescriptor(
        action_id="http_fetch",
        version="1.0.0",
        risk_level="low",
        request_schema=SAMPLE_HTTP_FETCH_SCHEMA,
        description="Test tool",
    )
    return LatchGateTool.from_descriptor(descriptor, mock_client)


# ── Schema conversion tests ──────────────────────────────────────────────


class TestSchemaConversion:
    def test_basic_properties(self) -> None:
        model = schema_to_pydantic("http_fetch", SAMPLE_HTTP_FETCH_SCHEMA)
        assert issubclass(model, BaseModel)
        assert model.__name__ == "HttpFetchInput"
        assert "url" in model.model_fields
        assert "method" in model.model_fields

    def test_required_field_has_no_default(self) -> None:
        model = schema_to_pydantic("http_fetch", SAMPLE_HTTP_FETCH_SCHEMA)
        assert model.model_fields["url"].is_required()

    def test_optional_field_has_default(self) -> None:
        model = schema_to_pydantic("http_fetch", SAMPLE_HTTP_FETCH_SCHEMA)
        assert not model.model_fields["method"].is_required()
        assert model.model_fields["method"].default == "GET"

    def test_empty_properties(self) -> None:
        model = schema_to_pydantic("empty", {"type": "object"})
        assert len(model.model_fields) == 0

    def test_model_name_sanitization(self) -> None:
        model = schema_to_pydantic("slack-post_message", {"type": "object"})
        assert model.__name__ == "SlackPostMessageInput"

    def test_type_mapping(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "s": {"type": "string"},
                "i": {"type": "integer"},
                "f": {"type": "number"},
                "b": {"type": "boolean"},
                "a": {"type": "array"},
                "o": {"type": "object"},
            },
        }
        model = schema_to_pydantic("types", schema)
        instance = model(s="x", i=1, f=1.5, b=True, a=[1], o={"k": "v"})
        assert instance.s == "x"
        assert instance.i == 1

    def test_union_type_takes_first_non_null(self) -> None:
        schema = {
            "type": "object",
            "properties": {"value": {"type": ["string", "null"]}},
        }
        model = schema_to_pydantic("union", schema)
        instance = model(value="hello")
        assert instance.value == "hello"

    def test_unknown_type_defaults_to_str(self) -> None:
        schema = {
            "type": "object",
            "properties": {"x": {"type": "foobar"}},
        }
        model = schema_to_pydantic("unknown", schema)
        instance = model(x="test")
        assert instance.x == "test"

    def test_generated_model_produces_valid_json_schema(self) -> None:
        model = schema_to_pydantic("http_fetch", SAMPLE_HTTP_FETCH_SCHEMA)
        schema = model.model_json_schema()
        assert "properties" in schema
        assert "url" in schema["properties"]


# ── Description builder tests ────────────────────────────────────────────


class TestDescriptionBuilder:
    def test_basic_description(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", None)
        assert "http_fetch" in desc
        assert "v1.0.0" in desc
        assert "risk=low" in desc
        assert "audit receipts" in desc

    def test_with_side_effects(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", SAMPLE_HTTP_FETCH_DETAIL)
        assert "http_read" in desc

    def test_default_redacts_egress_details(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", SAMPLE_HTTP_FETCH_DETAIL)
        assert "proxy_allowlist" not in desc
        assert "api.github.com" not in desc

    def test_default_redacts_database_details(self) -> None:
        desc = build_description("database", "1.0.0", "medium", SAMPLE_DATABASE_DETAIL)
        assert "hybrid" not in desc
        assert "get_user" not in desc

    def test_debug_includes_egress(self) -> None:
        desc = build_description("http_fetch", "1.0.0", "low", SAMPLE_HTTP_FETCH_DETAIL, "debug")
        assert "proxy_allowlist" in desc
        assert "api.github.com" in desc

    def test_debug_includes_database(self) -> None:
        desc = build_description("database", "1.0.0", "medium", SAMPLE_DATABASE_DETAIL, "debug")
        assert "hybrid" in desc
        assert "get_user" in desc
        assert "Parameterized" in desc

    def test_empty_detail(self) -> None:
        desc = build_description("test", "1.0.0", "low", {})
        assert "test" in desc
        assert "audit receipts" in desc


# ── Result serialization tests ───────────────────────────────────────────


class TestResultSerialization:
    def test_serialize_returns_only_output(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        parsed = json.loads(text)
        assert parsed == SAMPLE_ACTION_RESULT.output

    def test_serialize_excludes_receipt_metadata(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        assert "receipt_id" not in text
        assert "rcpt_" not in text
        assert "trace_id" not in text

    def test_serialize_excludes_verification(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        assert "verification" not in text
        assert "is_fully_successful" not in text

    def test_serialize_produces_valid_json(self) -> None:
        text = serialize_result(SAMPLE_ACTION_RESULT)
        parsed = json.loads(text)
        assert isinstance(parsed, dict)
        assert "status" in parsed


# ── Tool execution tests ─────────────────────────────────────────────────


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = _make_tool(client)

        result = await tool._arun(url="https://httpbin.org/get")
        parsed = json.loads(result)
        assert parsed == SAMPLE_ACTION_RESULT.output
        assert "receipt_id" not in result
        client.execute.assert_awaited_once_with("http_fetch", {"url": "https://httpbin.org/get"})

    @pytest.mark.asyncio
    async def test_denied_returns_error_string(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateDenied("http_fetch", "policy_violation"))
        tool = _make_tool(client)

        result = await tool._arun(url="https://evil.com")
        assert "ERROR" in result
        assert "denied" in result.lower()
        assert "policy_violation" in result

    @pytest.mark.asyncio
    async def test_approval_required_excludes_approval_id(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(
            side_effect=LatchGateApprovalRequired("send_message", "apr_01JTEST")
        )
        tool = _make_tool(client)

        result = await tool._arun(url="https://example.com")
        assert "approval" in result.lower()
        assert "apr_01JTEST" not in result
        assert "approval_id" not in result

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_error_string(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateBudgetExhausted("http_fetch"))
        tool = _make_tool(client)

        result = await tool._arun(url="https://example.com")
        assert "budget" in result.lower()

    @pytest.mark.asyncio
    async def test_unavailable_returns_error_string(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("redis_down"))
        tool = _make_tool(client)

        result = await tool._arun(url="https://example.com")
        assert "redis_down" in result.lower()

    @pytest.mark.asyncio
    async def test_no_exception_propagates_from_latchgate_errors(self) -> None:
        """All LatchGate errors are caught and returned as strings, never raised."""
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("opa_down"))
        tool = _make_tool(client)

        result = await tool._arun(url="https://example.com")
        assert isinstance(result, str)
        assert "ERROR" in result

    def test_sync_run_outside_event_loop(self) -> None:
        """_run works synchronously when no event loop is running."""
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = _make_tool(client)

        result = tool._run(url="https://httpbin.org/get")
        parsed = json.loads(result)
        assert parsed == SAMPLE_ACTION_RESULT.output
        assert "receipt_id" not in result

    @pytest.mark.asyncio
    async def test_execution_passes_all_kwargs(self) -> None:
        """Verify that all keyword arguments are forwarded to client.execute."""
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        tool = _make_tool(client)

        await tool._arun(url="https://example.com", method="HEAD", timeout_seconds=5)
        client.execute.assert_awaited_once_with(
            "http_fetch",
            {"url": "https://example.com", "method": "HEAD", "timeout_seconds": 5},
        )

    def test_from_descriptor_sets_all_fields(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        tool = _make_tool(client)
        assert tool.name == "http_fetch"
        assert tool.action_id == "http_fetch"
        assert tool.action_version == "1.0.0"
        assert tool.action_risk_level == "low"
        assert "Test tool" in tool.description
        assert tool.args_schema is not None

    @pytest.mark.asyncio
    async def test_audit_callback_invoked_on_success(self) -> None:
        """on_audit receives a correct AuditRecord after successful execution."""
        from latchgate_common.audit import AuditRecord

        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        audit_cb = Mock()

        descriptor = ActionDescriptor(
            action_id="http_fetch",
            version="1.0.0",
            risk_level="low",
            request_schema=SAMPLE_HTTP_FETCH_SCHEMA,
            description="Test tool",
        )
        tool = LatchGateTool.from_descriptor(descriptor, client, on_audit=audit_cb)

        await tool._arun(url="https://example.com")

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

        descriptor = ActionDescriptor(
            action_id="http_fetch",
            version="1.0.0",
            risk_level="low",
            request_schema=SAMPLE_HTTP_FETCH_SCHEMA,
            description="Test tool",
        )
        tool = LatchGateTool.from_descriptor(descriptor, client, on_audit=audit_cb)

        await tool._arun(url="https://evil.com")
        audit_cb.assert_not_called()


# ── Discovery tests ──────────────────────────────────────────────────────


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_all_actions(self) -> None:
        http = _mock_http(_full_discovery_routes())
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert len(descriptors) == 3
        assert {d.action_id for d in descriptors} == {"http_fetch", "send_message", "database"}

    @pytest.mark.asyncio
    async def test_discover_with_include_filter(self) -> None:
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
        assert descriptors[0].action_id == "http_fetch"

    @pytest.mark.asyncio
    async def test_discover_with_exclude_filter(self) -> None:
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
    async def test_schema_fetch_failure_uses_fallback(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [{"action_id": "no_schema", "version": "1.0.0", "risk_level": "low"}]
                },
                "/v1/actions/no_schema": {
                    "action_id": "no_schema",
                    "version": "1.0.0",
                    "risk_level": "low",
                },
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000", allow_schemaless=True, _http=http
        )
        assert len(descriptors) == 1
        assert descriptors[0].request_schema.get("additionalProperties") is True

    @pytest.mark.asyncio
    async def test_schema_fetch_failure_skips_by_default(self) -> None:
        """Default allow_schemaless=False rejects actions without schemas."""
        http = _mock_http(
            {
                "/v1/actions": {
                    "actions": [{"action_id": "no_schema", "version": "1.0.0", "risk_level": "low"}]
                },
                "/v1/actions/no_schema": {"action_id": "no_schema"},
            }
        )
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert len(descriptors) == 0

    @pytest.mark.asyncio
    async def test_empty_actions_returns_empty_list(self) -> None:
        http = _mock_http({"/v1/actions": {"actions": []}})
        descriptors = await discover_actions("http://localhost:3000", _http=http)
        assert descriptors == []

    @pytest.mark.asyncio
    async def test_transport_error_during_action_list_propagates(self) -> None:
        """Network error fetching /v1/actions should raise, not silently return empty."""
        http = _mock_http_with_errors(
            routes={},
            error_paths={"/v1/actions": httpx.ConnectError("connection refused")},
        )
        with pytest.raises(httpx.ConnectError):
            await discover_actions("http://localhost:3000", _http=http)

    @pytest.mark.asyncio
    async def test_schema_transport_error_uses_fallback(self) -> None:
        """Network error fetching a schema should fall back to permissive, not crash."""
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
    async def test_include_and_exclude_combined(self) -> None:
        http = _mock_http(
            {
                "/v1/actions": SAMPLE_ACTIONS_RESPONSE,
                "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
                "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
            }
        )
        descriptors = await discover_actions(
            "http://localhost:3000",
            include={"http_fetch", "send_message"},
            exclude={"send_message"},
            _http=http,
        )
        assert len(descriptors) == 1
        assert descriptors[0].action_id == "http_fetch"


# ── LatchGateToolset container tests ────────────────────────────────────────


class TestLatchGateToolset:
    def test_from_descriptors(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        descriptors = [
            ActionDescriptor(
                action_id="http_fetch",
                version="1.0.0",
                risk_level="low",
                request_schema=SAMPLE_HTTP_FETCH_SCHEMA,
                description="Test",
            ),
        ]
        lg = LatchGateToolset.from_descriptors(descriptors, client=client)
        tools = lg.all()
        assert len(tools) == 1
        assert tools[0].name == "http_fetch"
        assert lg.action_ids == ["http_fetch"]

    def test_get_tool_by_id(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        descriptors = [
            ActionDescriptor(
                action_id="http_fetch",
                version="1.0.0",
                risk_level="low",
                request_schema={"type": "object"},
                description="Test",
            ),
            ActionDescriptor(
                action_id="send_message",
                version="1.0.0",
                risk_level="high",
                request_schema={"type": "object"},
                description="Test",
            ),
        ]
        lg = LatchGateToolset.from_descriptors(descriptors, client=client)
        tool = lg.get("send_message")
        assert tool.action_id == "send_message"

    def test_get_tool_unknown_raises_keyerror(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        lg = LatchGateToolset.from_descriptors([], client=client)
        with pytest.raises(KeyError, match="nonexistent"):
            lg.get("nonexistent")

    def test_exposes_client(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        lg = LatchGateToolset.from_descriptors([], client=client)
        assert lg.client is client

    def test_empty_descriptors(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        lg = LatchGateToolset.from_descriptors([], client=client)
        assert lg.all() == []
        assert lg.action_ids == []

    def test_multiple_tools(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        descriptors = [
            ActionDescriptor(
                action_id=f"action_{i}",
                version="1.0.0",
                risk_level="low",
                request_schema={"type": "object"},
                description=f"Action {i}",
            )
            for i in range(5)
        ]
        lg = LatchGateToolset.from_descriptors(descriptors, client=client)
        assert len(lg.all()) == 5
        assert len(lg.action_ids) == 5

    def test_all_returns_copy(self) -> None:
        """all() should return a new list, not a mutable reference to internals."""
        client = AsyncMock(spec=LatchGateClient)
        descriptors = [
            ActionDescriptor(
                action_id="test",
                version="1.0.0",
                risk_level="low",
                request_schema={"type": "object"},
                description="Test",
            ),
        ]
        lg = LatchGateToolset.from_descriptors(descriptors, client=client)
        a = lg.all()
        b = lg.all()
        assert a is not b
        assert a == b

    @pytest.mark.asyncio
    async def test_create_async_factory(self) -> None:
        """Test the async create() factory with mocked discovery."""
        http = _mock_http(_full_discovery_routes())

        with patch("latchgate_common.discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            lg = await LatchGateToolset.create(gate_url="http://localhost:3000")
            assert len(lg.all()) == 3
            assert set(lg.action_ids) == {"http_fetch", "send_message", "database"}

    @pytest.mark.asyncio
    async def test_create_falls_back_to_default_transport(self) -> None:
        """Without gate_url, client, or LATCHGATE_URL, create() falls back
        to the default local transport (UDS) and raises a connection error
        when no gate is running."""
        with pytest.raises((httpx.ConnectError, httpx.TransportError, OSError)):
            await LatchGateToolset.create()

    @pytest.mark.asyncio
    async def test_create_discovers_via_client_transport(self) -> None:
        """When client is passed without gate_url, discovery reuses the client's
        internal httpx transport (UDS-compatible)."""
        http = _mock_http(_full_discovery_routes())
        client = AsyncMock(spec=LatchGateClient)
        client.gate_url = "http://localhost"
        client.http_transport = http

        toolset = await LatchGateToolset.create(client=client)
        assert len(toolset.all()) == 3

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Async context manager calls close() on exit."""
        client = AsyncMock(spec=LatchGateClient)
        descriptors = [
            ActionDescriptor(
                action_id="test",
                version="1.0.0",
                risk_level="low",
                request_schema={"type": "object"},
                description="Test",
            ),
        ]
        lg = LatchGateToolset.from_descriptors(descriptors, client=client)

        async with lg as toolset:
            assert len(toolset.all()) == 1

        client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_delegates_to_client(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        lg = LatchGateToolset.from_descriptors([], client=client)
        await lg.close()
        client.close.assert_awaited_once()
