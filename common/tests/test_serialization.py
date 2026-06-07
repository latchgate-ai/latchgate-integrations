"""Tests for result serialization — security-critical output filtering.

The serialize_result function is the single enforcement point that ensures
receipt IDs, trace IDs, and verification metadata never reach the model.
A compromised model could use leaked enforcement internals to:

- Forge downstream evidence using receipt IDs
- Correlate execution traces to map enforcement topology
- Craft targeted social-engineering prompts referencing verification details

Every integration package delegates to this function. A failure here
propagates to all frameworks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from latchgate_common.audit import AuditRecord
from latchgate_common.serialization import serialize_result

# ---------------------------------------------------------------------------
# Stub — mirrors latchgate.ActionResult without requiring the binary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubResult:
    output: Any = None
    receipt_id: str | None = None
    trace_id: str | None = None
    verification: Any = None


# ── Output-only filtering ─────────────────────────────────────────────────


class TestOutputOnlyFiltering:
    """The return value must contain ONLY the action output — nothing else."""

    def test_dict_output(self) -> None:
        result = StubResult(
            output={"status": 200, "body": "ok"},
            receipt_id="rcpt-a1b2c3",
            trace_id="tr-d4e5f6",
            verification={"valid": True, "sig": "0xdeadbeef"},
        )
        serialized = serialize_result(result, action_id="http_fetch")
        parsed = json.loads(serialized)

        assert parsed == {"status": 200, "body": "ok"}

    def test_receipt_id_never_in_output(self) -> None:
        sentinel = "rcpt-SENSITIVE-a1b2c3d4e5f6"
        result = StubResult(output={"ok": True}, receipt_id=sentinel)
        assert sentinel not in serialize_result(result)

    def test_trace_id_never_in_output(self) -> None:
        sentinel = "tr-SENSITIVE-789xyz"
        result = StubResult(output={"ok": True}, trace_id=sentinel)
        assert sentinel not in serialize_result(result)

    def test_verification_object_never_in_output(self) -> None:
        verification = {"hmac": "a9f8e7d6", "policy_id": "pol-secret-42"}
        result = StubResult(output="success", verification=verification)
        serialized = serialize_result(result)
        assert "a9f8e7d6" not in serialized
        assert "pol-secret-42" not in serialized

    def test_all_sensitive_fields_present_only_output_returned(self) -> None:
        """Combined: receipt, trace, and verification all set."""
        result = StubResult(
            output={"data": [1, 2, 3]},
            receipt_id="rcpt-secret",
            trace_id="tr-secret",
            verification={"sig": "secret-sig", "chain": ["a", "b"]},
        )
        serialized = serialize_result(result, action_id="test")
        parsed = json.loads(serialized)

        assert parsed == {"data": [1, 2, 3]}
        for secret in ("rcpt-secret", "tr-secret", "secret-sig"):
            assert secret not in serialized

    def test_none_sensitive_fields(self) -> None:
        result = StubResult(
            output={"value": 42},
            receipt_id=None,
            trace_id=None,
            verification=None,
        )
        assert json.loads(serialize_result(result)) == {"value": 42}


# ── Output type coverage ──────────────────────────────────────────────────


class TestOutputTypes:
    """serialize_result must faithfully serialize all valid output types."""

    def test_none_output(self) -> None:
        result = StubResult(output=None)
        assert json.loads(serialize_result(result)) is None

    def test_string_output(self) -> None:
        result = StubResult(output="hello world")
        assert json.loads(serialize_result(result)) == "hello world"

    def test_integer_output(self) -> None:
        result = StubResult(output=42)
        assert json.loads(serialize_result(result)) == 42

    def test_boolean_output(self) -> None:
        result = StubResult(output=False)
        assert json.loads(serialize_result(result)) is False

    def test_list_output(self) -> None:
        result = StubResult(output=[1, "two", None, True])
        assert json.loads(serialize_result(result)) == [1, "two", None, True]

    def test_nested_output(self) -> None:
        output = {
            "data": {"items": [{"id": 1, "tags": ["a", "b"]}]},
            "pagination": {"next": None, "total": 1},
        }
        result = StubResult(output=output)
        assert json.loads(serialize_result(result)) == output

    def test_unicode_preserved(self) -> None:
        """ensure_ascii=False must preserve non-ASCII characters."""
        result = StubResult(output="日本語テスト 🔒")
        serialized = serialize_result(result)
        assert "日本語テスト" in serialized
        assert "🔒" in serialized

    def test_non_serializable_uses_str_fallback(self) -> None:
        """Objects that aren't JSON-serializable fall back to str()."""
        from datetime import datetime

        ts = datetime(2026, 1, 15, 12, 0, 0)
        result = StubResult(output={"timestamp": ts})
        parsed = json.loads(serialize_result(result))
        assert parsed["timestamp"] == str(ts)


# ── Audit callback ────────────────────────────────────────────────────────


class TestAuditCallback:
    """on_audit receives the full metadata — it's the side-channel, not the model channel."""

    def test_callback_receives_complete_record(self) -> None:
        callback = MagicMock()
        result = StubResult(
            output={"ok": True},
            receipt_id="rcpt-123",
            trace_id="tr-456",
            verification={"valid": True},
        )
        serialize_result(result, action_id="send_email", on_audit=callback)

        callback.assert_called_once()
        record: AuditRecord = callback.call_args[0][0]
        assert record.action_id == "send_email"
        assert record.receipt_id == "rcpt-123"
        assert record.trace_id == "tr-456"
        assert record.verification == {"valid": True}

    def test_callback_none_is_safe(self) -> None:
        result = StubResult(output="ok", receipt_id="rcpt-x")
        serialized = serialize_result(result, action_id="test", on_audit=None)
        assert json.loads(serialized) == "ok"

    def test_callback_does_not_affect_return_value(self) -> None:
        """The callback's behavior must never alter what the model sees."""
        outputs: list[AuditRecord] = []

        def collecting_callback(record: AuditRecord) -> None:
            outputs.append(record)

        result = StubResult(output={"data": 1}, receipt_id="r", trace_id="t")
        serialized = serialize_result(result, action_id="act", on_audit=collecting_callback)

        assert json.loads(serialized) == {"data": 1}
        assert len(outputs) == 1
        assert outputs[0].receipt_id == "r"

    def test_default_action_id_is_empty(self) -> None:
        callback = MagicMock()
        result = StubResult(output="x")
        serialize_result(result, on_audit=callback)

        record: AuditRecord = callback.call_args[0][0]
        assert record.action_id == ""
