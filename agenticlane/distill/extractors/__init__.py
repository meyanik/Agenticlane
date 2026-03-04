"""Extractor sub-package.

Importing this module registers all built-in extractors with the
distillation registry.
"""

from __future__ import annotations

from agenticlane.distill.extractors.area import AreaExtractor
from agenticlane.distill.extractors.constraints import ConstraintExtractor
from agenticlane.distill.extractors.crash import CrashExtractor
from agenticlane.distill.extractors.drc import DRCExtractor
from agenticlane.distill.extractors.lvs import LVSExtractor
from agenticlane.distill.extractors.power import PowerExtractor
from agenticlane.distill.extractors.route import RouteExtractor
from agenticlane.distill.extractors.runtime import RuntimeExtractor
from agenticlane.distill.extractors.spatial import SpatialExtractor
from agenticlane.distill.extractors.synth import SynthExtractor
from agenticlane.distill.extractors.timing import TimingExtractor
from agenticlane.distill.registry import register

# Register all built-in extractors
register(TimingExtractor())
register(AreaExtractor())
register(RouteExtractor())
register(DRCExtractor())
register(LVSExtractor())
register(PowerExtractor())
register(RuntimeExtractor())
register(CrashExtractor())
register(SpatialExtractor())
register(ConstraintExtractor())
register(SynthExtractor())

__all__ = [
    "AreaExtractor",
    "ConstraintExtractor",
    "CrashExtractor",
    "DRCExtractor",
    "LVSExtractor",
    "PowerExtractor",
    "RouteExtractor",
    "RuntimeExtractor",
    "SpatialExtractor",
    "SynthExtractor",
    "TimingExtractor",
]
