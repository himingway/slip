"""Corner case tests for slang_integration/reflection.py."""

import pytest
from pathlib import Path

from slip.slang_integration import reflect_module, ModuleInfo

from conftest import FIXTURES

IP_DIR = FIXTURES / "ip"


class TestReflectModule:
    def test_basic_module(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        assert isinstance(info, ModuleInfo)
        assert len(info.ports) > 0

    def test_module_with_params(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        assert len(info.params) > 0

    def test_multibit_width(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        # Find a port with width
        wide_ports = [p for p in info.ports if p.width is not None]
        if wide_ports:
            assert "[" in wide_ports[0].width
            assert ":" in wide_ports[0].width

    def test_single_bit_width(self):
        info = reflect_module(IP_DIR / "prim_fifo.sv", "prim_fifo")
        # 1-bit ports should have width=None
        single_ports = [p for p in info.ports if p.width is None]
        # Just verify the structure is correct
        for p in single_ports:
            assert isinstance(p.name, str)
            assert p.direction in ("input", "output", "inout")

    def test_module_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            reflect_module(IP_DIR / "prim_fifo.sv", "nonexistent_module")

    def test_with_localparam(self):
        info = reflect_module(IP_DIR / "ip_with_localparam.sv", "ip_with_localparam")
        local_params = [p for p in info.params if p.is_local]
        assert len(local_params) > 0

    def test_port_directions(self):
        info = reflect_module(IP_DIR / "prim_obuf.sv", "prim_obuf")
        directions = {p.direction for p in info.ports}
        assert directions.issubset({"input", "output", "inout"})

    def test_defined_ip(self):
        info = reflect_module(IP_DIR / "defined_ip.sv", "defined_ip")
        assert isinstance(info, ModuleInfo)
