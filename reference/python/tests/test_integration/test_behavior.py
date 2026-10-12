"""Compare generated hardware against independently written SV reference RTL."""

import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import compile_source


@pytest.mark.skipif(shutil.which("verilator") is None, reason="Verilator is required for behavior simulation")
def test_pipeline_and_metaprogram_arithmetic_match_reference(tmp_path):
    fixtures = Path(__file__).resolve().parents[4] / "tests/behavior"
    modules = compile_source((fixtures / "design.slip").read_text())
    sources = []
    for name, text in modules.items():
        path = tmp_path / f"{name}.sv"
        path.write_text(text)
        sources.append(str(path))
    testbench = tmp_path / "tb.sv"
    testbench.write_text((fixtures / "tb.sv").read_text())
    build_dir = tmp_path / "obj"
    result = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wno-fatal", "--top-module", "tb",
         "--Mdir", str(build_dir), *sources, str(testbench)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    simulation = subprocess.run(
        [str(build_dir / "Vtb")], capture_output=True, text=True, timeout=15,
    )
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "PASS: 128 cycles" in simulation.stdout
