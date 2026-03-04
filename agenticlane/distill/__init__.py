"""Distillation layer for AgenticLane.

Extracts metrics, evidence, and constraint digests from stage execution
output files.  The main public API is :func:`assemble_evidence` which
runs all registered extractors and returns canonical
``MetricsPayload`` + ``EvidencePack`` objects.

Usage::

    from agenticlane.distill import assemble_evidence
    metrics, evidence = await assemble_evidence(
        attempt_dir, stage_name, attempt_num, execution_result, config
    )
"""

from __future__ import annotations

import agenticlane.distill.extractors  # noqa: F401
from agenticlane.distill.evidence import assemble_evidence, build_constraint_digest
from agenticlane.distill.registry import (
    Extractor,
    clear_registry,
    get_all_extractors,
    get_extractor,
    list_extractor_names,
    register,
)

__all__ = [
    "Extractor",
    "assemble_evidence",
    "build_constraint_digest",
    "clear_registry",
    "get_all_extractors",
    "get_extractor",
    "list_extractor_names",
    "register",
]
