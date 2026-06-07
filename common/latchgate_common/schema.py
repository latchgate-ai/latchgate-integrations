"""JSON Schema to Pydantic model conversion for LatchGate action parameters.

Used by framework integrations that require a Pydantic model for tool
argument validation (LangChain, CrewAI). Frameworks with native JSON Schema
support (OpenAI Agents, Pydantic AI) bypass this module.

We deliberately do NOT attempt to support the full JSON Schema spec.
Over-engineering the conversion creates fragile code that breaks on
edge cases. The gate is the authoritative validator; the Pydantic model
here serves two purposes:

1. Give the framework a schema to emit in function-call descriptions.
2. Provide basic client-side type hints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

# JSON Schema type => Python type mapping for dynamic Pydantic model generation.
JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def schema_to_pydantic(action_id: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Convert a JSON Schema ``{"type": "object", "properties": ...}`` to a Pydantic model.

    Handles the common patterns emitted by LatchGate manifests:
    flat objects with typed properties, required fields, and descriptions.
    Nested objects and arrays are mapped to ``dict`` / ``list`` respectively —
    the framework passes them as raw JSON and the gate validates server-side.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required_fields: set[str] = set(schema.get("required", []))

    field_definitions: dict[str, Any] = {}

    for prop_name, prop_schema in properties.items():
        python_type = resolve_type(prop_schema)
        description = prop_schema.get("description", "")
        default = prop_schema.get("default")

        if prop_name in required_fields:
            field_definitions[prop_name] = (
                python_type,
                FieldInfo(description=description),
            )
        else:
            # Optional field — default to None if no default specified.
            effective_default = default if default is not None else None
            field_definitions[prop_name] = (
                python_type | None,
                FieldInfo(default=effective_default, description=description),
            )

    # Sanitize the action_id into a valid Python class name.
    model_name = (
        "".join(part.capitalize() for part in action_id.replace("-", "_").split("_")) + "Input"
    )

    model: type[BaseModel] = create_model(model_name, **field_definitions)
    return model


def resolve_type(prop_schema: dict[str, Any]) -> type:
    """Map a JSON Schema property to a Python type."""
    json_type = prop_schema.get("type", "string")

    # Handle union types like ["string", "null"] — take the first non-null.
    if isinstance(json_type, list):
        for t in json_type:
            if t != "null" and t in JSON_TYPE_MAP:
                return JSON_TYPE_MAP[t]
        return str

    return JSON_TYPE_MAP.get(json_type, str)
