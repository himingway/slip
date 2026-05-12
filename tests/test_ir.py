"""Unit tests for IR dataclass methods."""

import pytest

from slip.ir import (
    HDLAssignment,
    HDLIfBlock,
    HDLInstance,
    HDLModule,
    HDLParam,
    HDLPort,
    HDLSignal,
    HDLType,
    LogicBlock,
)


class TestHDLType:
    def test_width_str_with_width(self):
        t = HDLType(width_sv="[7:0]")
        assert t.width_str() == "[7:0]"

    def test_width_str_no_width(self):
        t = HDLType()
        assert t.width_str() == ""

    def test_width_str_none(self):
        t = HDLType(width_sv=None)
        assert t.width_str() == ""

    def test_frozen(self):
        t = HDLType()
        with pytest.raises(AttributeError):
            t.base = "wire"


class TestHDLPort:
    def test_decl_sv_with_width(self):
        p = HDLPort("data", "input", HDLType(width_sv="[7:0]"))
        assert p.decl_sv() == "input logic [7:0] data"

    def test_decl_sv_signed(self):
        p = HDLPort("val", "output", HDLType(is_signed=True))
        assert p.decl_sv() == "output logic signed val"

    def test_decl_sv_plain(self):
        p = HDLPort("clk", "input", HDLType())
        assert p.decl_sv() == "input logic clk"

    def test_decl_sv_inout(self):
        p = HDLPort("bus", "inout", HDLType())
        assert p.decl_sv() == "inout logic bus"

    def test_decl_sv_no_type(self):
        p = HDLPort("sig", "input", None)
        assert p.decl_sv() == "input logic sig"

    def test_decl_sv_width_signed(self):
        p = HDLPort("val", "output", HDLType(width_sv="[15:0]", is_signed=True))
        assert p.decl_sv() == "output logic [15:0] val"


class TestHDLSignal:
    def test_decl_sv_with_width(self):
        s = HDLSignal("data", HDLType(width_sv="[7:0]"))
        assert s.decl_sv() == "logic [7:0] data;"

    def test_decl_sv_signed(self):
        s = HDLSignal("val", HDLType(is_signed=True))
        assert "logic signed val;" in s.decl_sv()

    def test_decl_sv_array(self):
        s = HDLSignal("mem", HDLType(), array_dim="[0:15]")
        assert "logic mem [0:15];" in s.decl_sv()

    def test_decl_sv_width_signed(self):
        s = HDLSignal("val", HDLType(width_sv="[7:0]", is_signed=True))
        assert s.decl_sv() == "logic signed [7:0] val;"

    def test_decl_sv_no_type(self):
        s = HDLSignal("sig", None)
        assert "logic sig;" in s.decl_sv()


class TestHDLAssignment:
    def test_to_sv_blocking(self):
        a = HDLAssignment("y", "a & b", is_nonblocking=False)
        assert a.to_sv() == "y = a & b;"

    def test_to_sv_nonblocking(self):
        a = HDLAssignment("q", "d", is_nonblocking=True)
        assert a.to_sv() == "q <= d;"

    def test_to_sv_default_is_blocking(self):
        a = HDLAssignment("x", "1")
        assert "=" in a.to_sv()
        assert "<=" not in a.to_sv()


class TestHDLIfBlock:
    def test_construction_with_else(self):
        blk = HDLIfBlock(
            cond="rst",
            then_body=(HDLAssignment("q", "0"),),
            else_body=(HDLAssignment("q", "d"),),
        )
        assert blk.cond == "rst"
        assert len(blk.then_body) == 1
        assert len(blk.else_body) == 1

    def test_construction_no_else(self):
        blk = HDLIfBlock(cond="en", then_body=(HDLAssignment("q", "d"),))
        assert blk.else_body is None


class TestLogicBlock:
    def test_always_ff(self):
        lb = LogicBlock(
            sensitivity="posedge clk or negedge rst_n",
            body=(HDLAssignment("q", "d", True),),
            kind="always_ff",
        )
        assert lb.kind == "always_ff"
        assert "posedge" in lb.sensitivity

    def test_always_comb(self):
        lb = LogicBlock(sensitivity="", body=(), kind="always_comb")
        assert lb.kind == "always_comb"


class TestHDLInstance:
    def test_construction(self):
        inst = HDLInstance(
            inst_name="u1",
            target="child",
            param_map=(("W", "8"),),
            port_map=(("clk", "clk"),),
            regex_rules=(),
        )
        assert inst.inst_name == "u1"
        assert inst.target == "child"
        assert inst.param_map == (("W", "8"),)

    def test_defaults(self):
        inst = HDLInstance(inst_name="u1", target="child")
        assert inst.param_map == ()
        assert inst.port_map == ()
        assert inst.regex_rules == ()


class TestHDLParam:
    def test_construction(self):
        p = HDLParam("W", "8")
        assert p.name == "W"
        assert p.default == "8"


class TestHDLModule:
    def test_defaults(self):
        m = HDLModule(name="top")
        assert m.params == ()
        assert m.localparams == ()
        assert m.ports == ()
        assert m.signals == ()
        assert m.assigns == ()
        assert m.logic_blocks == ()
        assert m.instances == ()

    def test_construction(self):
        m = HDLModule(
            name="top",
            ports=(HDLPort("a", "input", HDLType()),),
            signals=(HDLSignal("w", HDLType()),),
        )
        assert m.name == "top"
        assert len(m.ports) == 1
        assert len(m.signals) == 1
