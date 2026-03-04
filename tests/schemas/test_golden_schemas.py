"""Golden file roundtrip tests for all canonical schemas.

Each test loads a known-good JSON file, parses it into the Pydantic model,
serializes it back to JSON, and verifies the roundtrip produces equivalent data.
"""

from __future__ import annotations

import json
from pathlib import Path

from agenticlane.schemas.evidence import EvidencePack
from agenticlane.schemas.execution import ExecutionResult
from agenticlane.schemas.llm import LLMCallRecord
from agenticlane.schemas.metrics import MetricsPayload
from agenticlane.schemas.patch import Patch, PatchRejected

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "schemas"


def _load_golden(filename: str) -> dict:
    path = GOLDEN_DIR / filename
    return json.loads(path.read_text())


class TestGoldenPatch:
    """Patch v5 golden file roundtrip."""

    def test_patch_v5_loads(self) -> None:
        data = _load_golden("patch_v5.json")
        patch = Patch(**data)
        assert patch.schema_version == 5
        assert patch.patch_id == "golden-patch-001"
        assert patch.stage == "FLOORPLAN"

    def test_patch_v5_roundtrip(self) -> None:
        data = _load_golden("patch_v5.json")
        patch = Patch(**data)
        roundtrip = json.loads(patch.model_dump_json())
        assert roundtrip["schema_version"] == data["schema_version"]
        assert roundtrip["patch_id"] == data["patch_id"]
        assert roundtrip["config_vars"] == data["config_vars"]
        assert len(roundtrip["macro_placements"]) == len(data["macro_placements"])

    def test_patch_v5_has_required_fields(self) -> None:
        data = _load_golden("patch_v5.json")
        patch = Patch(**data)
        assert hasattr(patch, "schema_version")
        assert hasattr(patch, "config_vars")
        assert hasattr(patch, "sdc_edits")
        assert hasattr(patch, "tcl_edits")
        assert hasattr(patch, "rationale")


class TestGoldenPatchRejected:
    """PatchRejected v1 golden file roundtrip."""

    def test_patch_rejected_loads(self) -> None:
        data = _load_golden("patch_rejected_v1.json")
        rejected = PatchRejected(**data)
        assert rejected.schema_version == 1
        assert rejected.reason_code == "locked_constraint"
        assert rejected.offending_channel == "config_vars"

    def test_patch_rejected_roundtrip(self) -> None:
        data = _load_golden("patch_rejected_v1.json")
        rejected = PatchRejected(**data)
        roundtrip = json.loads(rejected.model_dump_json())
        assert roundtrip["reason_code"] == data["reason_code"]
        assert roundtrip["offending_commands"] == data["offending_commands"]
        assert roundtrip["remediation_hint"] == data["remediation_hint"]


class TestGoldenMetricsPayload:
    """MetricsPayload v3 golden file roundtrip."""

    def test_metrics_payload_loads(self) -> None:
        data = _load_golden("metrics_payload_v3.json")
        metrics = MetricsPayload(**data)
        assert metrics.schema_version == 3
        assert metrics.run_id == "run_golden_001"
        assert metrics.execution_status == "success"

    def test_metrics_payload_roundtrip(self) -> None:
        data = _load_golden("metrics_payload_v3.json")
        metrics = MetricsPayload(**data)
        roundtrip = json.loads(metrics.model_dump_json())
        assert roundtrip["run_id"] == data["run_id"]
        assert roundtrip["stage"] == data["stage"]

    def test_metrics_payload_has_timing(self) -> None:
        data = _load_golden("metrics_payload_v3.json")
        metrics = MetricsPayload(**data)
        assert metrics.timing is not None
        assert metrics.timing.setup_wns_ns is not None

    def test_metrics_payload_has_physical(self) -> None:
        data = _load_golden("metrics_payload_v3.json")
        metrics = MetricsPayload(**data)
        assert metrics.physical is not None
        assert metrics.physical.utilization_pct == 68.5

    def test_metrics_payload_has_signoff(self) -> None:
        data = _load_golden("metrics_payload_v3.json")
        metrics = MetricsPayload(**data)
        assert metrics.signoff is not None
        assert metrics.signoff.drc_count == 0
        assert metrics.signoff.lvs_pass is True


class TestGoldenEvidencePack:
    """EvidencePack v1 golden file roundtrip."""

    def test_evidence_pack_loads(self) -> None:
        data = _load_golden("evidence_pack_v1.json")
        evidence = EvidencePack(**data)
        assert evidence.schema_version == 1
        assert evidence.stage == "CTS"
        assert evidence.execution_status == "success"

    def test_evidence_pack_roundtrip(self) -> None:
        data = _load_golden("evidence_pack_v1.json")
        evidence = EvidencePack(**data)
        roundtrip = json.loads(evidence.model_dump_json())
        assert roundtrip["stage"] == data["stage"]
        assert len(roundtrip["errors"]) == len(data["errors"])

    def test_evidence_pack_has_hotspots(self) -> None:
        data = _load_golden("evidence_pack_v1.json")
        evidence = EvidencePack(**data)
        assert len(evidence.spatial_hotspots) == 1
        assert evidence.spatial_hotspots[0].severity == 0.82


class TestGoldenExecutionResult:
    """ExecutionResult golden file roundtrip."""

    def test_execution_result_loads(self) -> None:
        data = _load_golden("execution_result.json")
        result = ExecutionResult(**data)
        assert result.execution_status == "success"
        assert result.exit_code == 0

    def test_execution_result_roundtrip(self) -> None:
        data = _load_golden("execution_result.json")
        result = ExecutionResult(**data)
        roundtrip = json.loads(result.model_dump_json())
        assert roundtrip["execution_status"] == data["execution_status"]
        assert roundtrip["runtime_seconds"] == data["runtime_seconds"]


class TestGoldenLLMCallRecord:
    """LLMCallRecord golden file roundtrip."""

    def test_llm_call_record_loads(self) -> None:
        data = _load_golden("llm_call_record.json")
        record = LLMCallRecord(**data)
        assert record.model == "gemini/gemini-2.5-pro"
        assert record.role == "worker"
        assert record.tokens_in == 1840

    def test_llm_call_record_roundtrip(self) -> None:
        data = _load_golden("llm_call_record.json")
        record = LLMCallRecord(**data)
        roundtrip = json.loads(record.model_dump_json())
        assert roundtrip["model"] == data["model"]
        assert roundtrip["latency_ms"] == data["latency_ms"]
        assert roundtrip["tokens_out"] == data["tokens_out"]
