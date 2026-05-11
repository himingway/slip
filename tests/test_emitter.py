"""Unit tests for codegen fragment functions and emitter utilities."""

import pytest

from slip.codegen import fragment
from slip.codegen.emitter import _is_relevant_diagnostic
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


class TestModuleHeader:
    def test_no_params_no_ports(self):
        mod = HDLModule(name="empty")
        header = fragment.module_header(mod)
        assert "module empty" in header
        assert "endmodule" not in header  # header only

    def test_with_params(self):
        mod = HDLModule(name="m", params=(HDLParam("W", "8"), HDLParam("N", "16")))
        header = fragment.module_header(mod)
        assert "parameter W = 8," in header
        assert "parameter N = 16" in header
        assert "#(" in header

    def test_with_ports(self):
        mod = HDLModule(
            name="m",
            ports=(HDLPort("a", "input", HDLType()), HDLPort("b", "output", HDLType())),
        )
        header = fragment.module_header(mod)
        assert "input logic a," in header
        assert "output logic b" in header

    def test_with_params_and_ports(self):
        mod = HDLModule(
            name="m",
            params=(HDLParam("W", "8"),),
            ports=(HDLPort("a", "input", HDLType()),),
        )
        header = fragment.module_header(mod)
        assert "parameter W = 8" in header
        assert "input logic a" in header

    def test_single_param_no_comma(self):
        mod = HDLModule(name="m", params=(HDLParam("W", "8"),))
        header = fragment.module_header(mod)
        assert "parameter W = 8" in header
        # Should not have trailing comma
        lines = header.split("\n")
        param_line = [l for l in lines if "parameter" in l][0]
        assert not param_line.rstrip().endswith(",")


class TestLocalparamDecl:
    def test_basic(self):
        p = HDLParam("MAX", "255")
        result = fragment.localparam_decl(p)
        assert "localparam MAX = 255;" in result


class TestSignalDecl:
    def test_basic(self):
        sig = HDLSignal("data", HDLType(width_sv="[7:0]"))
        result = fragment.signal_decl(sig)
        assert "logic [7:0] data;" in result


class TestAssignStmt:
    def test_blocking(self):
        a = HDLAssignment("y", "a & b")
        result = fragment.assign_stmt(a)
        assert "assign y = a & b;" in result

    def test_nonblocking(self):
        a = HDLAssignment("q", "d", is_nonblocking=True)
        result = fragment.assign_stmt(a)
        assert "assign q <= d;" in result


class TestLogicBlock:
    def test_always_ff(self):
        block = LogicBlock(
            sensitivity="posedge clk or negedge rst_n",
            body=(HDLAssignment("q", "d", True),),
        )
        result = fragment.logic_block(block)
        assert "always_ff @(posedge clk or negedge rst_n) begin" in result
        assert "q <= d;" in result
        assert "end" in result

    def test_always_comb(self):
        block = LogicBlock(
            sensitivity="",
            body=(HDLAssignment("y", "a & b"),),
            kind="always_comb",
        )
        result = fragment.logic_block(block)
        assert "always_comb begin" in result
        assert "y = a & b;" in result

    def test_nested_if_in_logic_block(self):
        block = LogicBlock(
            sensitivity="posedge clk",
            body=(
                HDLIfBlock(
                    cond="rst",
                    then_body=(HDLAssignment("q", "0"),),
                    else_body=(HDLAssignment("q", "d"),),
                ),
            ),
        )
        result = fragment.logic_block(block)
        assert "if (rst) begin" in result
        assert "end else begin" in result


class TestInstance:
    def test_no_params_no_ports(self):
        inst = HDLInstance(inst_name="u1", target="child")
        result = fragment.instance(inst)
        assert "child" in result
        assert "u1" in result
        assert ";" in result

    def test_with_params(self):
        inst = HDLInstance(
            inst_name="u1", target="child",
            param_map=(("W", "8"), ("N", "16")),
        )
        result = fragment.instance(inst)
        assert ".W(8)," in result
        assert ".N(16)" in result
        assert "#(" in result

    def test_with_ports(self):
        inst = HDLInstance(
            inst_name="u1", target="child",
            port_map=(("clk", "clk"), ("data_in", "data")),
        )
        result = fragment.instance(inst)
        assert ".clk(clk)," in result
        assert ".data_in(data)" in result

    def test_dangling_port_filtered(self):
        inst = HDLInstance(
            inst_name="u1", target="child",
            port_map=(("clk", "clk"), ("unused", "_")),
        )
        result = fragment.instance(inst)
        assert ".clk(clk)" in result
        assert "unused" not in result

    def test_all_ports_dangling(self):
        inst = HDLInstance(
            inst_name="u1", target="child",
            port_map=(("a", "_"), ("b", "_")),
        )
        result = fragment.instance(inst)
        assert "u1" in result
        # No port connections section
        assert ".a" not in result


class TestModuleFooter:
    def test_footer(self):
        assert fragment.module_footer() == "endmodule"


class TestEmitBlockItem:
    def test_assignment(self):
        a = HDLAssignment("x", "1")
        result = fragment._emit_block_item(a)
        assert len(result) == 1
        assert "x = 1;" in result[0]

    def test_if_with_else(self):
        blk = HDLIfBlock(
            cond="en",
            then_body=(HDLAssignment("q", "1"),),
            else_body=(HDLAssignment("q", "0"),),
        )
        result = fragment._emit_block_item(blk)
        text = "\n".join(result)
        assert "if (en) begin" in text
        assert "end else begin" in text
        assert "q = 1;" in text
        assert "q = 0;" in text

    def test_if_no_else(self):
        blk = HDLIfBlock(
            cond="en",
            then_body=(HDLAssignment("q", "1"),),
        )
        result = fragment._emit_block_item(blk)
        text = "\n".join(result)
        assert "if (en) begin" in text
        assert "end else begin" not in text

    def test_unknown_type_returns_empty(self):
        result = fragment._emit_block_item("not a real item")
        assert result == []


class TestIsRelevantDiagnostic:
    def test_suppressed_unknown_module(self):
        class FakeDiag:
            code = "UnknownModule"
        assert _is_relevant_diagnostic(FakeDiag()) is False

    def test_suppressed_undeclared(self):
        class FakeDiag:
            code = "UndeclaredIdentifier"
        assert _is_relevant_diagnostic(FakeDiag()) is False

    def test_relevant_error(self):
        class FakeDiag:
            code = "SyntaxError"
        assert _is_relevant_diagnostic(FakeDiag()) is True

    def test_no_code_attribute(self):
        class FakeDiag:
            pass
        assert _is_relevant_diagnostic(FakeDiag()) is True
