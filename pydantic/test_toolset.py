"""Tests for latchgate-pydantic-ai.

All tests are self-contained — no running LatchGate or LLM required.
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
    discover_actions,
)
from latchgate_common.serialization import serialize_result

from latchgate_pydantic_ai._toolset import LatchGateToolset

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
        "/v1/actions/send_message": {"action_id": "send_message"},
        "/v1/actions/database/schema/request": {"type": "object"},
        "/v1/actions/database": {"action_id": "database"},
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


def _make_tool_call(tool_name: str, args: dict[str, Any]) -> Any:
    """Create a ToolCallPart."""
    from pydantic_ai.messages import ToolCallPart

    return ToolCallPart(
        tool_name=tool_name,
        args=args,
        tool_call_id="test-call-id",
    )


def _make_toolset(
    descriptors: list[ActionDescriptor] | None = None,
    client: LatchGateClient | None = None,
    toolset_id: str = "latchgate",
) -> LatchGateToolset:
    """Helper to create a toolset with defaults."""
    if client is None:
        client = AsyncMock(spec=LatchGateClient)
    if descriptors is None:
        descriptors = [_make_descriptor()]
    return LatchGateToolset(client=client, descriptors=descriptors, toolset_id=toolset_id)


# ── Toolset id() tests ──────────────────────────────────────────────────


class TestId:
    def test_default_id(self) -> None:
        toolset = _make_toolset()
        assert toolset.id() == "latchgate"

    def test_custom_id(self) -> None:
        toolset = _make_toolset(toolset_id="my-custom-toolset")
        assert toolset.id() == "my-custom-toolset"


# ── Toolset get_tools tests ──────────────────────────────────────────────


class TestGetTools:
    @pytest.mark.asyncio
    async def test_returns_tool_definitions(self) -> None:
        descriptors = [_make_descriptor("http_fetch"), _make_descriptor("send_message")]
        toolset = _make_toolset(descriptors=descriptors)

        tools = await toolset.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"http_fetch", "send_message"}

    @pytest.mark.asyncio
    async def test_tool_definition_has_schema(self) -> None:
        toolset = _make_toolset()

        tools = await toolset.get_tools()
        schema = tools[0].parameters_json_schema
        assert schema["type"] == "object"
        assert "url" in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_tool_definition_has_description(self) -> None:
        toolset = _make_toolset()

        tools = await toolset.get_tools()
        assert tools[0].description == "Test tool"

    @pytest.mark.asyncio
    async def test_empty_descriptors(self) -> None:
        toolset = _make_toolset(descriptors=[])

        tools = await toolset.get_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_invalid_schema_gets_wrapped(self) -> None:
        descriptor = _make_descriptor(schema={"type": "string"})
        toolset = _make_toolset(descriptors=[descriptor])

        tools = await toolset.get_tools()
        assert tools[0].parameters_json_schema["type"] == "object"

    @pytest.mark.asyncio
    async def test_get_tools_returns_fresh_list(self) -> None:
        toolset = _make_toolset()
        a = await toolset.get_tools()
        b = await toolset.get_tools()
        assert a is not b
        assert len(a) == len(b)


# ── Toolset call_tool tests ──────────────────────────────────────────────


class TestCallTool:
    @pytest.mark.asyncio
    async def test_successful_execution(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {"url": "https://httpbin.org/get"})
        result = await toolset.call_tool(call)
        parsed = json.loads(result)
        assert parsed == SAMPLE_ACTION_RESULT.output
        assert "receipt_id" not in result
        client.execute.assert_awaited_once_with("http_fetch", {"url": "https://httpbin.org/get"})

    @pytest.mark.asyncio
    async def test_denied_returns_error(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateDenied("http_fetch", "policy_violation"))
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {"url": "https://evil.com"})
        result = await toolset.call_tool(call)
        assert "ERROR" in result
        assert "denied" in result.lower()
        assert "policy_violation" in result

    @pytest.mark.asyncio
    async def test_approval_required(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(
            side_effect=LatchGateApprovalRequired("send_message", "apr_01JTEST")
        )
        toolset = _make_toolset(
            descriptors=[_make_descriptor("send_message")],
            client=client,
        )

        call = _make_tool_call("send_message", {})
        result = await toolset.call_tool(call)
        assert "approval" in result.lower()
        assert "apr_01JTEST" not in result
        assert "approval_id" not in result

    @pytest.mark.asyncio
    async def test_budget_exhausted(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateBudgetExhausted("http_fetch"))
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {})
        result = await toolset.call_tool(call)
        assert "budget" in result.lower()

    @pytest.mark.asyncio
    async def test_unavailable(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("redis_down"))
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {})
        result = await toolset.call_tool(call)
        assert "redis_down" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        toolset = _make_toolset()

        call = _make_tool_call("nonexistent", {})
        result = await toolset.call_tool(call)
        assert "ERROR" in result
        assert "Unknown" in result

    @pytest.mark.asyncio
    async def test_no_exception_propagates(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(side_effect=LatchGateUnavailable("opa_down"))
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {})
        result = await toolset.call_tool(call)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_forwards_all_params(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        client.execute = AsyncMock(return_value=SAMPLE_ACTION_RESULT)
        toolset = _make_toolset(client=client)

        call = _make_tool_call("http_fetch", {"url": "https://x.com", "method": "HEAD"})
        await toolset.call_tool(call)
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
        toolset = _make_toolset(client=client)
        toolset._on_audit = audit_cb

        call = _make_tool_call("http_fetch", {"url": "https://example.com"})
        await toolset.call_tool(call)

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
        toolset = _make_toolset(client=client)
        toolset._on_audit = audit_cb

        call = _make_tool_call("http_fetch", {"url": "https://evil.com"})
        await toolset.call_tool(call)
        audit_cb.assert_not_called()


# ── Properties tests ─────────────────────────────────────────────────────


class TestProperties:
    def test_action_ids(self) -> None:
        descriptors = [_make_descriptor("a"), _make_descriptor("b"), _make_descriptor("c")]
        toolset = _make_toolset(descriptors=descriptors)
        assert toolset.action_ids == ["a", "b", "c"]

    def test_client(self) -> None:
        client = AsyncMock(spec=LatchGateClient)
        toolset = _make_toolset(descriptors=[], client=client)
        assert toolset.client is client

    def test_empty_action_ids(self) -> None:
        toolset = _make_toolset(descriptors=[])
        assert toolset.action_ids == []


# ── Result serialization ─────────────────────────────────────────────────


class TestSerialization:
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
    @pytest.mark.asyncio
    async def test_create_falls_back_to_default_transport(self) -> None:
        """Without gate_url, client, or LATCHGATE_URL, create() falls back
        to the default local transport (UDS) and raises a connection error
        when no gate is running."""
        with pytest.raises((httpx.ConnectError, httpx.TransportError, OSError)):
            await LatchGateToolset.create()

    @pytest.mark.asyncio
    async def test_create_with_client_discovers_via_transport(self) -> None:
        """When client is passed without gate_url, discovery reuses the client's
        internal httpx transport (UDS-compatible)."""
        http = _mock_http(_full_discovery_routes())
        client = AsyncMock(spec=LatchGateClient)
        client.gate_url = "http://localhost"
        client.http_transport = http

        toolset = await LatchGateToolset.create(client=client)
        tools = await toolset.get_tools()
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_create_with_mocked_discovery(self) -> None:
        http = _mock_http(_full_discovery_routes())

        with patch("latchgate_common.discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
            tools = await toolset.get_tools()
            assert len(tools) == 3
            assert toolset.id() == "latchgate"

    @pytest.mark.asyncio
    async def test_create_with_custom_id(self) -> None:
        http = _mock_http(_full_discovery_routes())

        with patch("latchgate_common.discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            toolset = await LatchGateToolset.create(
                gate_url="http://localhost:3000",
                toolset_id="my-lg",
            )
            assert toolset.id() == "my-lg"

    @pytest.mark.asyncio
    async def test_create_with_include(self) -> None:
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

            toolset = await LatchGateToolset.create(
                gate_url="http://localhost:3000",
                include={"http_fetch"},
            )
            assert toolset.action_ids == ["http_fetch"]


# ── Discovery tests ──────────────────────────────────────────────────────


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_all(self) -> None:
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
