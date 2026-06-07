"""
Wire codec for the APL protocol types.

The protocol types in :mod:`apl.types` are pydantic models, so serialization is
``model_dump`` and deserialization is ``model_validate`` — there are no
hand-written, per-field serializers left to drift out of sync (which is what
caused the round-trip bugs this module replaces). This is the single place that
owns the *wire policy* layered on top of pydantic:

- :func:`to_wire` omits ``None`` fields but preserves explicit empty
  collections, so an empty list never collapses to absent/``None`` on the wire
  (an explicit ``llm_prompt=[]`` stays ``[]``).
- :func:`verdict_from_wire` requires ``confidence`` and validates the payload; an
  under-specified or malformed verdict is rejected (fail-closed) rather than
  silently defaulted to full confidence, which would skew weighted composition.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from apl.types import (
    PolicyEvent,
    PolicyManifest,
    PolicyUnavailableError,
    Verdict,
)


def to_wire(model: BaseModel) -> dict[str, Any]:
    """
    Serialize a protocol model to a JSON-ready dict.

    ``None``-valued fields are dropped; explicit empty collections are kept, so an empty
    list never round-trips to ``None``.
    """
    return model.model_dump(mode="json", exclude_none=True)


def event_from_wire(data: dict[str, Any]) -> PolicyEvent:
    """Decode a :class:`~apl.types.PolicyEvent`, validating its shape."""
    return PolicyEvent.model_validate(data or {})


def manifest_from_wire(data: dict[str, Any]) -> PolicyManifest:
    """Decode a :class:`~apl.types.PolicyManifest`, validating its shape."""
    return PolicyManifest.model_validate(data)


def verdict_from_wire(data: dict[str, Any]) -> Verdict:
    """
    Decode a :class:`~apl.types.Verdict` received from a policy server.

    ``confidence`` is required on the wire: a verdict that omits it is rejected rather
    than treated as fully confident (1.0). Defaulting to 1.0 would bias weighted
    composition toward whatever the verdict decided — the wrong direction for a safety
    system. Any invalid payload (missing confidence, out of range, broken invariant)
    raises :class:`~apl.types.PolicyUnavailableError` so the caller fails closed.
    """
    if not isinstance(data, dict) or "confidence" not in data:
        raise PolicyUnavailableError(
            "verdict payload is missing the required 'confidence' field"
        )
    try:
        return Verdict.model_validate(data)
    except ValidationError as exc:
        raise PolicyUnavailableError(f"invalid verdict payload: {exc}") from exc


__all__ = [
    "to_wire",
    "event_from_wire",
    "manifest_from_wire",
    "verdict_from_wire",
]
