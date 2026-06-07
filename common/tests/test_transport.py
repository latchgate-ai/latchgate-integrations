"""Tests for discovery transport resolution.

Validates the resolution priority: explicit gate_url > LATCHGATE_URL env > client.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

from latchgate_common.transport import resolve_discovery_params


class StubClient:
    """Minimal stand-in for LatchGateClient."""

    def __init__(
        self,
        gate_url: str | None = None,
        http_transport: httpx.AsyncClient | None = None,
    ) -> None:
        self.gate_url = gate_url
        self.http_transport = http_transport


class TestResolveDiscoveryParams:
    def test_explicit_gate_url(self) -> None:
        url, http = resolve_discovery_params("http://explicit:3000", None)
        assert url == "http://explicit:3000"
        assert http is None

    def test_explicit_url_takes_priority_over_env(self) -> None:
        with patch.dict(os.environ, {"LATCHGATE_URL": "http://env:3000"}):
            url, _ = resolve_discovery_params("http://explicit:3000", None)
            assert url == "http://explicit:3000"

    def test_explicit_url_takes_priority_over_client(self) -> None:
        client = StubClient(gate_url="http://client:3000")
        url, http = resolve_discovery_params("http://explicit:3000", client)
        assert url == "http://explicit:3000"
        assert http is None

    def test_env_var_fallback(self) -> None:
        with patch.dict(os.environ, {"LATCHGATE_URL": "http://env:3000"}):
            url, http = resolve_discovery_params(None, None)
            assert url == "http://env:3000"
            assert http is None

    def test_client_fallback_with_transport(self) -> None:
        mock_transport = httpx.AsyncClient()
        client = StubClient(
            gate_url="http://client:3000",
            http_transport=mock_transport,
        )
        url, http = resolve_discovery_params(None, client)
        assert url == "http://client:3000"
        assert http is mock_transport

    def test_client_without_gate_url_raises(self) -> None:
        client = StubClient(gate_url=None)
        with pytest.raises(ValueError, match="gate_url is required"):
            resolve_discovery_params(None, client)

    def test_client_with_empty_gate_url_raises(self) -> None:
        client = StubClient(gate_url="")
        with pytest.raises(ValueError, match="gate_url is required"):
            resolve_discovery_params(None, client)

    def test_nothing_provided_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Ensure LATCHGATE_URL is not set
            os.environ.pop("LATCHGATE_URL", None)
            with pytest.raises(ValueError, match="gate_url is required"):
                resolve_discovery_params(None, None)
