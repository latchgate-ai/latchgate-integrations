"""Action discovery from the LatchGate REST API.

Fetches the action registry and request schemas via unauthenticated endpoints.
These endpoints expose only structural metadata — never credentials or secrets.

Discovery is a one-time operation at toolkit initialization, not per-call.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

# Identifier format: alphanumeric start, then alphanumeric/hyphens/underscores/dots.
# No path separators, query strings, or URL-special characters.
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _is_safe_identifier(value: str) -> bool:
    """Check whether a string is safe for URL path interpolation.

    Used to validate action_ids received from the gate before embedding
    them in URLs for schema and detail fetches.  The gate is a trusted
    source, but a compromised or buggy gate could return a crafted
    action_id (e.g. ``"../../admin"``) that alters the request path.
    """
    return bool(value) and len(value) <= 256 and _SAFE_IDENTIFIER_RE.match(value) is not None


@dataclass(frozen=True)
class ActionDescriptor:
    """Metadata for a single discovered LatchGate action."""

    action_id: str
    version: str
    risk_level: str
    request_schema: dict[str, Any]
    description: str
    declared_side_effects: list[str] = field(default_factory=list)


async def discover_actions(
    gate_url: str,
    *,
    timeout: float = 15.0,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    allow_schemaless: bool = False,
    expose_security_details: Literal["none", "debug"] = "none",
    _http: httpx.AsyncClient | None = None,
) -> list[ActionDescriptor]:
    """Discover all registered actions from a LatchGate instance.

    Parameters
    ----------
    gate_url:
        Base URL of the running gate (e.g. ``"http://localhost:3000"``).
    timeout:
        HTTP timeout for discovery requests in seconds.
    include:
        If provided, only return actions whose ``action_id`` is in this set.
    exclude:
        If provided, skip actions whose ``action_id`` is in this set.
        ``exclude`` is applied after ``include``.
    allow_schemaless:
        When ``False`` (default), actions without a request schema are
        skipped with a warning. Production LatchGate always serves
        schemas; a missing schema indicates a degraded gate. Set to
        ``True`` only for development against a gate that legitimately
        omits schemas.
    expose_security_details:
        Controls how much enforcement metadata appears in model-visible
        tool descriptions. ``"none"`` (default) omits egress profiles,
        allowed domains, database modes, and statement IDs — a
        compromised model could use these to craft targeted attacks.
        ``"debug"`` includes all available detail.
    _http:
        Optional pre-configured ``httpx.AsyncClient`` — used for testing.
        When provided, the caller owns the client lifecycle.

    Returns
    -------
    List of :class:`ActionDescriptor` for each discovered action.
    """
    base = gate_url.rstrip("/")

    if _http is not None:
        return await _discover_with_client(
            _http,
            base,
            include,
            exclude,
            allow_schemaless,
            expose_security_details,
        )

    async with httpx.AsyncClient(timeout=timeout) as http:
        return await _discover_with_client(
            http,
            base,
            include,
            exclude,
            allow_schemaless,
            expose_security_details,
        )


async def _discover_with_client(
    http: httpx.AsyncClient,
    base: str,
    include: set[str] | None,
    exclude: set[str] | None,
    allow_schemaless: bool,
    security_detail: Literal["none", "debug"],
) -> list[ActionDescriptor]:
    """Core discovery logic using an existing HTTP client."""
    actions_resp = await http.get(f"{base}/v1/actions")
    actions_resp.raise_for_status()
    actions_data = actions_resp.json()

    raw_actions: list[dict[str, Any]] = actions_data.get("actions", [])
    if not raw_actions:
        logger.warning("gate returned zero actions from %s/v1/actions", base)
        return []

    # Filter before fetching schemas to avoid unnecessary network calls.
    filtered = _filter_actions(raw_actions, include, exclude)

    descriptors: list[ActionDescriptor] = []
    for action in filtered:
        action_id = action["action_id"]

        if not _is_safe_identifier(action_id):
            logger.warning(
                "skipping action with unsafe identifier: %r — "
                "action_id must be alphanumeric with hyphens, underscores, "
                "or dots (max 256 chars)",
                action_id,
            )
            continue

        version = action.get("version", "0.0.0")
        risk_level = action.get("risk_level", "unknown")

        schema = await _fetch_schema(http, base, action_id)

        if schema is None:
            if allow_schemaless:
                logger.warning(
                    "no schema for action '%s' — wrapping with permissive "
                    "schema (allow_schemaless=True)",
                    action_id,
                )
                schema = {"type": "object", "additionalProperties": True}
            else:
                logger.warning(
                    "skipping action '%s': gate did not return a request schema. "
                    "This usually means the gate is degraded. Pass "
                    "allow_schemaless=True to wrap anyway (not recommended "
                    "for production).",
                    action_id,
                )
                continue

        detail = await _fetch_detail(http, base, action_id)

        side_effects = detail.get("declared_side_effects", []) if detail else []
        description = build_description(action_id, version, risk_level, detail, security_detail)

        descriptors.append(
            ActionDescriptor(
                action_id=action_id,
                version=version,
                risk_level=risk_level,
                request_schema=schema,
                description=description,
                declared_side_effects=side_effects,
            )
        )

    logger.info("discovered %d LatchGate actions from %s", len(descriptors), base)
    return descriptors


def _filter_actions(
    actions: list[dict[str, Any]],
    include: set[str] | None,
    exclude: set[str] | None,
) -> list[dict[str, Any]]:
    """Apply include/exclude filters to the raw action list."""
    result = actions
    if include is not None:
        result = [a for a in result if a.get("action_id") in include]
    if exclude is not None:
        result = [a for a in result if a.get("action_id") not in exclude]
    return result


async def _fetch_schema(
    http: httpx.AsyncClient,
    base: str,
    action_id: str,
) -> dict[str, Any] | None:
    """Fetch the request JSON Schema for an action. Returns None on failure."""
    try:
        resp = await http.get(f"{base}/v1/actions/{action_id}/schema/request")
        if resp.status_code == 200:
            schema: dict[str, Any] = resp.json()
            return schema
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "failed to fetch schema for action '%s': %s",
            action_id,
            exc,
        )
    return None


async def _fetch_detail(
    http: httpx.AsyncClient,
    base: str,
    action_id: str,
) -> dict[str, Any] | None:
    """Fetch the full action detail. Returns None on failure (best-effort)."""
    try:
        resp = await http.get(f"{base}/v1/actions/{action_id}")
        if resp.status_code == 200:
            detail: dict[str, Any] = resp.json()
            return detail
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("failed to fetch detail for action '%s': %s", action_id, exc)
    return None


def build_description(
    action_id: str,
    version: str,
    risk_level: str,
    detail: dict[str, Any] | None,
    security_detail: Literal["none", "debug"] = "none",
) -> str:
    """Build a human-readable tool description from action metadata.

    The description gives an LLM enough context to decide when to call
    the tool and how to construct valid arguments.

    When ``security_detail`` is ``"none"`` (default), egress profiles,
    allowed domains, database modes, and statement IDs are omitted —
    exposing these to a potentially compromised model leaks enforcement
    topology that could be used for targeted attacks.

    When ``security_detail`` is ``"debug"``, all available metadata is
    included. Use this only in trusted development environments.
    """
    parts: list[str] = [
        f"LatchGate protected action: {action_id} (v{version}, risk={risk_level}).",
    ]

    if detail:
        side_effects = detail.get("declared_side_effects", [])
        if side_effects:
            parts.append(f"Side effects: {', '.join(side_effects)}.")

        if security_detail == "debug":
            egress = detail.get("egress")
            if isinstance(egress, dict):
                profile = egress.get("profile", "")
                domains = egress.get("allowed_domains", [])
                if profile:
                    parts.append(f"Egress profile: {profile}.")
                if domains:
                    parts.append(f"Allowed domains: {', '.join(domains)}.")

            db = detail.get("database")
            if isinstance(db, dict):
                mode = db.get("mode", "unknown")
                parts.append(f"Database mode: {mode}.")
                stmts = db.get("statements", [])
                if stmts:
                    ids = [s.get("id", "?") for s in stmts]
                    parts.append(f"Available statements: {', '.join(ids)}.")
                if db.get("allows_parameterized_queries"):
                    ops = db.get("parameterized_operations", [])
                    parts.append(f"Parameterized queries allowed for: {', '.join(ops)}.")

    parts.append(
        "All calls are authenticated, policy-evaluated, sandboxed, "
        "and produce signed audit receipts."
    )
    return " ".join(parts)
