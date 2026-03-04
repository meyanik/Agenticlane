"""Tests for real EDA tool report parsing.

Verifies that each extractor can parse actual OpenROAD, Magic, Netgen,
and KLayout report output in addition to the mock format.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenticlane.distill.extractors.area import AreaExtractor
from agenticlane.distill.extractors.drc import DRCExtractor
from agenticlane.distill.extractors.lvs import LVSExtractor
from agenticlane.distill.extractors.power import PowerExtractor
from agenticlane.distill.extractors.route import RouteExtractor
from agenticlane.distill.extractors.timing import TimingExtractor

# ---------------------------------------------------------------------------
# Sample real report snippets
# ---------------------------------------------------------------------------

OPENSTA_TIMING_REPORT = """\
Startpoint: counter_reg[0] (rising edge-triggered flip-flop clocked by clk)
Endpoint: counter_reg[7] (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   0.00    0.00   clock source latency
   0.05    0.05 ^ clk (in)
   0.21    0.26 ^ counter_reg[0]/CLK (sky130_fd_sc_hd__dfxtp_1)
   3.84    4.10 ^ counter_reg[7]/D (sky130_fd_sc_hd__dfxtp_1)
           4.10   data arrival time

  10.00   10.00   clock clk (rise edge)
   0.00   10.00   clock source latency
   0.05   10.05 ^ clk (in)
   0.21   10.26 ^ counter_reg[7]/CLK (sky130_fd_sc_hd__dfxtp_1)
  -0.10   10.16   library setup time
           10.16   data required time
---------------------------------------------------------
           10.16   data required time
           -4.10   data arrival time
---------------------------------------------------------
            6.06   slack (MET)

worst slack 6.06
tns 0.00
Clock clk Period: 10.000
"""

OPENSTA_TIMING_VIOLATED = """\
worst slack -0.32
tns -4.56
Clock clk Period: 10.000
"""

OPENROAD_AREA_REPORT = """\
[INFO]: Design area 1523.456 u^2 45% utilization
"""

OPENROAD_AREA_REPORT_2 = """\
Design area 2345.678 µm²
Utilization: 38.5%
"""

OPENROAD_ROUTING_METRICS = """\
[INFO GRT-0096] Final congestion report:
Layer  Resource  Demand  Usage (%)  Max H / Max V / Total Overflow
metal1     1000     850      85.0%    2 / 3 / 12
metal2     1200     600      50.0%    0 / 0 / 0
Total overflow: 12
Number of overflow: 5
"""

MAGIC_DRC_REPORT_CLEAN = """\
[INFO]: TOTAL ERRORS: 0
"""

MAGIC_DRC_REPORT_VIOLATIONS = """\
Metal1.MinWidth
   1. counter_reg[0]/Q (0.500 um x 0.200 um)
   2. counter_reg[1]/Q (0.500 um x 0.200 um)
Metal2.Spacing
   3. net_clk to net_rst (spacing = 0.120 um, min = 0.140 um)
[INFO]: TOTAL ERRORS: 3
"""

KLAYOUT_DRC_REPORT = """\
Total DRC errors: 5
Metal1.MinWidth: 2
Via1.Enclosure: 3
"""

NETGEN_LVS_MATCH = """\
Subcircuit summary:
Circuit 1: counter                         |Circuit 2: counter
-------------------------------------------+-------------------------------------------
Number of devices: 42                      |Number of devices: 42
Number of nets: 55                         |Number of nets: 55

Circuits match uniquely.
Netlists match uniquely.
"""

NETGEN_LVS_MISMATCH = """\
Subcircuit summary:
Circuit 1: counter                         |Circuit 2: counter
-------------------------------------------+-------------------------------------------
Number of devices: 42                      |Number of devices: 40
Number of nets: 55                         |Number of nets: 53

Netlists do not match.
"""

NETGEN_LVS_RESULT_PASS = """\
Result: PASS
"""

NETGEN_LVS_RESULT_FAIL = """\
Result: FAIL
Property errors were found.
"""

OPENROAD_POWER_REPORT = """\
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power
----------------------------------------------------------------
Sequential             1.23e-04  5.67e-05  8.90e-06  1.89e-04
Combinational          4.56e-04  2.34e-04  3.21e-05  7.22e-04
Macro                  0.00e+00  0.00e+00  0.00e+00  0.00e+00
Pad                    0.00e+00  0.00e+00  0.00e+00  0.00e+00
----------------------------------------------------------------
Total                  5.79e-04  2.91e-04  4.10e-05  9.11e-04
"""

POWER_REPORT_SUMMARY = """\
Total Power = 1.234 mW
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_report(tmp_path: Path, filename: str, content: str, subdir: str = "artifacts") -> Path:
    """Write a report file in the standard attempt_dir/artifacts/ structure."""
    attempt_dir = tmp_path / "attempt_001"
    artifacts_dir = attempt_dir / subdir
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifacts_dir / filename
    report_path.write_text(content)
    return attempt_dir


# ---------------------------------------------------------------------------
# Tests: TimingExtractor with real formats
# ---------------------------------------------------------------------------


class TestTimingExtractorReal:
    def test_opensta_report_wns_met(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "timing.rpt", OPENSTA_TIMING_REPORT)
        extractor = TimingExtractor()
        result = extractor.extract(attempt_dir, "SYNTH")
        assert result["setup_wns_ns"]["default"] == pytest.approx(6.06)

    def test_opensta_report_wns_violated(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "timing.rpt", OPENSTA_TIMING_VIOLATED)
        extractor = TimingExtractor()
        result = extractor.extract(attempt_dir, "SYNTH")
        assert result["setup_wns_ns"]["default"] == pytest.approx(-0.32)

    def test_opensta_tns(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "timing.rpt", OPENSTA_TIMING_VIOLATED)
        extractor = TimingExtractor()
        result = extractor.extract(attempt_dir, "SYNTH")
        assert result["tns_ns"] == pytest.approx(-4.56)

    def test_opensta_clock_period(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "timing.rpt", OPENSTA_TIMING_REPORT)
        extractor = TimingExtractor()
        result = extractor.extract(attempt_dir, "SYNTH")
        assert result["clock_period_ns"] == pytest.approx(10.0)

    def test_mock_format_still_works(self, tmp_path):
        """Ensure the mock format is still parsed correctly."""
        mock_content = """\
# Synthetic timing report
wns -0.1500
tns -1.5000
Clock clk Period: 10.000
  Setup WNS: -0.1500 ns
  Setup TNS: -1.5000 ns
"""
        attempt_dir = _write_report(tmp_path, "timing.rpt", mock_content)
        extractor = TimingExtractor()
        result = extractor.extract(attempt_dir, "SYNTH")
        assert result["setup_wns_ns"]["default"] is not None


# ---------------------------------------------------------------------------
# Tests: AreaExtractor with real formats
# ---------------------------------------------------------------------------


class TestAreaExtractorReal:
    def test_openroad_area_with_utilization(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "area.rpt", OPENROAD_AREA_REPORT)
        extractor = AreaExtractor()
        result = extractor.extract(attempt_dir, "FLOORPLAN")
        assert result["core_area_um2"] == pytest.approx(1523.456)
        assert result["utilization_pct"] == pytest.approx(45.0)

    def test_openroad_area_unicode(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "area.rpt", OPENROAD_AREA_REPORT_2)
        extractor = AreaExtractor()
        result = extractor.extract(attempt_dir, "FLOORPLAN")
        assert result["core_area_um2"] == pytest.approx(2345.678)
        assert result["utilization_pct"] == pytest.approx(38.5)

    def test_mock_format_still_works(self, tmp_path):
        mock_content = """\
# Synthetic area report
Design area 500000.00 u^2
  Core area: 500000.00 um^2
  Utilization: 45.00%
"""
        attempt_dir = _write_report(tmp_path, "area.rpt", mock_content)
        extractor = AreaExtractor()
        result = extractor.extract(attempt_dir, "FLOORPLAN")
        assert result["core_area_um2"] == pytest.approx(500000.00)
        assert result["utilization_pct"] == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Tests: RouteExtractor with real formats
# ---------------------------------------------------------------------------


class TestRouteExtractorReal:
    def test_openroad_total_overflow(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "congestion.rpt", OPENROAD_ROUTING_METRICS)
        extractor = RouteExtractor()
        result = extractor.extract(attempt_dir, "ROUTE_GLOBAL")
        assert result["congestion_overflow_pct"] == pytest.approx(12.0)

    def test_mock_format_still_works(self, tmp_path):
        mock_content = "Overflow: 2.5000%\n"
        attempt_dir = _write_report(tmp_path, "congestion.rpt", mock_content)
        extractor = RouteExtractor()
        result = extractor.extract(attempt_dir, "ROUTE_GLOBAL")
        assert result["congestion_overflow_pct"] == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Tests: DRCExtractor with real formats
# ---------------------------------------------------------------------------


class TestDRCExtractorReal:
    def test_magic_drc_clean(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "drc.rpt", MAGIC_DRC_REPORT_CLEAN)
        extractor = DRCExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["drc_count"] == 0

    def test_magic_drc_violations(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "drc.rpt", MAGIC_DRC_REPORT_VIOLATIONS)
        extractor = DRCExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["drc_count"] == 3
        assert "Metal1.MinWidth" in result["drc_types"]
        assert "Metal2.Spacing" in result["drc_types"]

    def test_klayout_drc(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "drc.rpt", KLAYOUT_DRC_REPORT)
        extractor = DRCExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["drc_count"] == 5

    def test_mock_format_still_works(self, tmp_path):
        mock_content = "DRC violations: 2\nType: metal_spacing\n"
        attempt_dir = _write_report(tmp_path, "drc.rpt", mock_content)
        extractor = DRCExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["drc_count"] == 2


# ---------------------------------------------------------------------------
# Tests: LVSExtractor with real formats
# ---------------------------------------------------------------------------


class TestLVSExtractorReal:
    def test_netgen_match(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "lvs.rpt", NETGEN_LVS_MATCH)
        extractor = LVSExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["lvs_pass"] is True

    def test_netgen_mismatch(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "lvs.rpt", NETGEN_LVS_MISMATCH)
        extractor = LVSExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["lvs_pass"] is False

    def test_netgen_result_pass(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "lvs.rpt", NETGEN_LVS_RESULT_PASS)
        extractor = LVSExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["lvs_pass"] is True

    def test_netgen_result_fail(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "lvs.rpt", NETGEN_LVS_RESULT_FAIL)
        extractor = LVSExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["lvs_pass"] is False

    def test_mock_format_still_works(self, tmp_path):
        mock_content = "LVS clean\n"
        attempt_dir = _write_report(tmp_path, "lvs.rpt", mock_content)
        extractor = LVSExtractor()
        result = extractor.extract(attempt_dir, "SIGNOFF")
        assert result["lvs_pass"] is True


# ---------------------------------------------------------------------------
# Tests: PowerExtractor with real formats
# ---------------------------------------------------------------------------


class TestPowerExtractorReal:
    def test_openroad_tabular_power(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "power.rpt", OPENROAD_POWER_REPORT)
        extractor = PowerExtractor()
        result = extractor.extract(attempt_dir, "FINISH")
        # Total = 9.11e-04 W → 0.911 mW
        assert result["total_power_mw"] == pytest.approx(0.911, rel=0.01)

    def test_power_summary_format(self, tmp_path):
        attempt_dir = _write_report(tmp_path, "power.rpt", POWER_REPORT_SUMMARY)
        extractor = PowerExtractor()
        result = extractor.extract(attempt_dir, "FINISH")
        assert result["total_power_mw"] == pytest.approx(1.234)

    def test_mock_format_still_works(self, tmp_path):
        mock_content = "Total Power: 2.500 mW\nLeakage: 12.5%\n"
        attempt_dir = _write_report(tmp_path, "power.rpt", mock_content)
        extractor = PowerExtractor()
        result = extractor.extract(attempt_dir, "FINISH")
        assert result["total_power_mw"] == pytest.approx(2.5)
        assert result["leakage_pct"] == pytest.approx(12.5)
