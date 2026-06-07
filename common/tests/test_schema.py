"""Tests for JSON Schema to Pydantic model conversion.

The generated models serve two purposes:
1. Provide the framework with a schema for function-call descriptions
2. Give basic client-side type hints

The gate is the authoritative validator — these models are structural,
not exhaustive.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from latchgate_common.schema import JSON_TYPE_MAP, resolve_type, schema_to_pydantic

# ── resolve_type ──────────────────────────────────────────────────────────


class TestResolveType:
    @pytest.mark.parametrize(
        "json_type,python_type",
        [
            ("string", str),
            ("integer", int),
            ("number", float),
            ("boolean", bool),
            ("array", list),
            ("object", dict),
        ],
    )
    def test_standard_types(self, json_type: str, python_type: type) -> None:
        assert resolve_type({"type": json_type}) is python_type

    def test_unknown_type_defaults_to_str(self) -> None:
        assert resolve_type({"type": "binary"}) is str

    def test_missing_type_defaults_to_str(self) -> None:
        assert resolve_type({}) is str

    def test_union_with_null_takes_first_non_null(self) -> None:
        assert resolve_type({"type": ["integer", "null"]}) is int

    def test_union_without_null(self) -> None:
        assert resolve_type({"type": ["string", "integer"]}) is str

    def test_union_only_null_defaults_to_str(self) -> None:
        assert resolve_type({"type": ["null"]}) is str

    def test_json_type_map_completeness(self) -> None:
        """Every standard JSON Schema type must be in the map."""
        for t in ("string", "integer", "number", "boolean", "array", "object"):
            assert t in JSON_TYPE_MAP


# ── schema_to_pydantic ───────────────────────────────────────────────────


class TestSchemaToPydantic:
    def test_required_field(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["url"],
            "properties": {"url": {"type": "string", "description": "Target URL"}},
        }
        model = schema_to_pydantic("http-fetch", schema)
        assert issubclass(model, BaseModel)

        # Required field must not accept None as default
        field = model.model_fields["url"]
        assert field.is_required()

    def test_optional_field_defaults_to_none(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"method": {"type": "string"}},
        }
        model = schema_to_pydantic("act", schema)
        field = model.model_fields["method"]
        assert not field.is_required()
        assert field.default is None

    def test_optional_field_with_explicit_default(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"method": {"type": "string", "default": "GET"}},
        }
        model = schema_to_pydantic("act", schema)
        assert model.model_fields["method"].default == "GET"

    def test_model_naming_from_action_id(self) -> None:
        model = schema_to_pydantic("http-fetch", {"type": "object", "properties": {}})
        assert model.__name__ == "HttpFetchInput"

    def test_model_naming_with_underscores(self) -> None:
        model = schema_to_pydantic("db_query_select", {"type": "object", "properties": {}})
        assert model.__name__ == "DbQuerySelectInput"

    def test_model_naming_with_dots(self) -> None:
        model = schema_to_pydantic("v1.query", {"type": "object", "properties": {}})
        # Dots are not split — only hyphens and underscores are
        assert "Input" in model.__name__

    def test_empty_properties(self) -> None:
        model = schema_to_pydantic("empty", {"type": "object", "properties": {}})
        assert issubclass(model, BaseModel)
        assert len(model.model_fields) == 0

    def test_no_properties_key(self) -> None:
        model = schema_to_pydantic("bare", {"type": "object"})
        assert len(model.model_fields) == 0

    def test_mixed_required_optional(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["to"],
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
        }
        model = schema_to_pydantic("send-email", schema)
        assert model.model_fields["to"].is_required()
        assert not model.model_fields["subject"].is_required()
        assert not model.model_fields["body"].is_required()

    def test_nested_object_becomes_dict(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "headers": {"type": "object", "description": "HTTP headers"},
            },
        }
        model = schema_to_pydantic("act", schema)
        # Nested objects map to dict — gate validates server-side
        instance = model(headers={"Authorization": "Bearer x"})
        assert instance.headers == {"Authorization": "Bearer x"}

    def test_array_becomes_list(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "description": "Labels"},
            },
        }
        model = schema_to_pydantic("act", schema)
        instance = model(tags=["a", "b"])
        assert instance.tags == ["a", "b"]

    def test_field_descriptions_preserved(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The target URL to fetch"},
            },
        }
        model = schema_to_pydantic("act", schema)
        assert model.model_fields["url"].description == "The target URL to fetch"

    def test_instantiation_roundtrip(self) -> None:
        """A model built from schema must accept valid data and serialize back."""
        schema: dict[str, Any] = {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        }
        model = schema_to_pydantic("search", schema)
        instance = model(query="test")
        dumped = instance.model_dump()
        assert dumped["query"] == "test"
        assert dumped["limit"] == 10
