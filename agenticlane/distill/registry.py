"""Extractor registry for the distillation layer.

Provides a protocol-based registration system for metric and evidence
extractors.  Each extractor implements the ``Extractor`` protocol and is
registered by name so the evidence-assembly pipeline can discover and
invoke all registered extractors automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Extractor(Protocol):
    """Protocol that all distillation extractors must satisfy."""

    name: str

    def extract(self, attempt_dir: Path, stage_name: str) -> dict[str, Any]:
        """Extract data from *attempt_dir* for the given *stage_name*.

        Returns a dict whose keys depend on the extractor type (e.g.
        ``timing``, ``area``, ``crash_info``).  The dict is later merged
        into ``MetricsPayload`` / ``EvidencePack`` by the assembly layer.
        """
        ...  # pragma: no cover


_REGISTRY: dict[str, Extractor] = {}


def register(extractor: Extractor) -> Extractor:
    """Register an extractor instance by its ``name`` attribute."""
    _REGISTRY[extractor.name] = extractor
    return extractor


def get_extractor(name: str) -> Extractor:
    """Return the extractor registered under *name*.

    Raises
    ------
    KeyError
        If no extractor with that name has been registered.
    """
    if name not in _REGISTRY:
        raise KeyError(f"No extractor registered with name {name!r}")
    return _REGISTRY[name]


def get_all_extractors() -> dict[str, Extractor]:
    """Return a shallow copy of the full extractor registry."""
    return dict(_REGISTRY)


def list_extractor_names() -> list[str]:
    """Return a sorted list of all registered extractor names."""
    return sorted(_REGISTRY.keys())


def clear_registry() -> None:
    """Remove all registered extractors (useful in tests)."""
    _REGISTRY.clear()
