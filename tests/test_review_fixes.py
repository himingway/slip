"""End-to-end regression tests for the issues found in the 2026-09 review.

Each test exercises a user-visible guarantee through the full compiler
pipeline (parse → semantic → codegen), so a regression in any layer is
caught here rather than only in a unit test of that layer.
"""

import warnings

import pytest
from pyslang import Compilation, SyntaxTree

from slip.errors.semantic import SlipSemanticError
from slip.errors.syntax import SlipSyntaxError
from conftest import compile_source


def _sv(source, key=None):
    sv = compile_source(source)
    return sv[key] if key else sv


class TestPortDeclarations:
    """Port qualifiers and array dimensions survive into the header."""

    def test_signed_port_keeps_qualifier(self):
        sv = _sv(
            "module m (clk, s, o) { signed logic [7:0] s; logic [7:0] o; "
            "assign o = s; }", "m")
        assert "input logic signed [7:0] s" in sv

    def test_array_port_keeps_dimension(self):
        sv = _sv(
            "module m (clk, arr, o) { logic [7:0] arr [0:3]; "
            "logic [7:0] o; assign o = arr[0]; }", "m")
        assert "input logic [7:0] arr [0:3]" in sv

    def test_signed_signal_keeps_qualifier(self):
        sv = _sv(
            "module m (i, o) { signed logic [7:0] i; logic [7:0] o; "
            "signed logic [7:0] tmp; assign tmp = i; assign o = tmp; }",
            "m")
        assert "logic signed [7:0] tmp;" in sv


class TestIllegalSvPrevention:
    """Constructs that used to emit invalid SystemVerilog now fail early."""

    def test_module_level_nonblocking_rejected(self):
        with pytest.raises(SlipSemanticError, match="not allowed at module level"):
            compile_source("module m (clk, d, q) { logic clk; logic [7:0] d; "
                           "logic [7:0] q; q <= d; }")

    def test_empty_instance_emits_parens(self):
        sv = _sv("module leaf (y) { logic y; assign y = 1'b0; } "
                 "module m (y) { logic y; leaf u1 { }; }", "m")
        assert "leaf u1 ()" in sv

    def test_empty_instance_sv_is_valid(self):
        child = "module leaf (y) { logic y; assign y = 1'b0; }"
        parent = "module m (y) { logic y; leaf u1 { }; }"
        sv = compile_source(child + " " + parent)
        comp = Compilation()
        comp.addSyntaxTree(SyntaxTree.fromText(sv["leaf"] + "\n" + sv["m"], "both.sv"))
        assert [d for d in comp.getAllDiagnostics() if d.isError()] == []

    def test_empty_concatenation_rejected_at_source(self):
        with pytest.raises(SlipSyntaxError, match="empty concatenation") as e:
            compile_source("module m (y) { logic y; assign y = {}; }")
        assert e.value.line == 1 and e.value.col > 0

    def test_instance_output_drives_port_direction(self):
        sv = _sv(
            "module child (a, y) { logic [7:0] a; logic [7:0] y; comb { y = a; } } "
            "module top (a, y) { logic [7:0] a; logic [7:0] y; "
            "child u1 { .a(a), .y(y) }; }", "top")
        assert "output logic [7:0] y" in sv


class TestModuleLevelStatements:
    """Statements the parser accepts at module level are handled, not dropped."""

    @pytest.mark.parametrize("stmt", [
        "if (a) { x = b; }",
        "for (i = 0; i < 4; i++) { x = a; }",
        "case (a) { 1'b0: x = b; default: x = a; }",
    ])
    def test_rejected_with_guidance(self, stmt):
        with pytest.raises(SlipSemanticError, match="not supported at module level"):
            compile_source(f"module m (a, b, x) {{ logic a; logic b; logic x; {stmt} }}")

    def test_block_nested_declaration_keeps_width(self):
        sv = _sv("module m (a, o) { logic [7:0] a; logic [7:0] o; "
                 "comb { logic [7:0] t; t = a; o = t; } }", "m")
        assert "logic [7:0] t;" in sv

    def test_block_nested_localparam_emitted(self):
        sv = _sv("module m (a, o) { logic [7:0] a; logic [7:0] o; "
                 "comb { localparam LP = 3; o = a + LP; } }", "m")
        assert "localparam LP = 3;" in sv


class TestDriverAnalysis:
    """Loop and multi-driver detection across blocks and bit ranges."""

    def test_init_then_accumulate_allowed(self):
        sv = _sv("module m (b, y) { logic [7:0] b; logic [7:0] y; "
                 "comb { y = 0; y = y + b; } }", "m")
        assert "always_comb" in sv

    def test_self_feedback_detected(self):
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source("module m (a, y) { logic [7:0] a; logic [7:0] y; "
                           "comb { y = y & a; } }")

    def test_cross_block_loop_detected(self):
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source("module m (a, t1, t2) { logic a; logic t1; logic t2; "
                           "comb { t1 = t2; } assign t2 = t1 + a; }")

    def test_continuous_plus_procedural_driver_detected(self):
        with pytest.raises(SlipSemanticError, match="multiple drivers"):
            compile_source("module m (clk, a, x) { logic clk; logic a; logic x; "
                           "assign x = a; comb { x = a; } }")

    def test_disjoint_bit_drivers_allowed(self):
        sv = _sv("module m (a, o) { logic [3:0] a; logic [3:0] o; "
                 "assign o[0] = a[0]; assign o[1] = a[1]; }", "m")
        assert "assign o[0] = a[0];" in sv


class TestSafety:
    """Compiling an untrusted .slip file must not execute arbitrary code."""

    def test_defun_cannot_import(self):
        with pytest.raises(SlipSemanticError, match="not allowed|not defined"):
            compile_source(
                'defun pwn(x):\n    return __import__("os").system("true")\n'
                "module c (clk, d_in) { logic clk; logic d_in; }\n"
                'module m (clk, d_x) { logic clk; logic d_x;\n'
                '  c u1 { .clk, "d_(.*)" => "$pwn(\\1)" }; }'
            )

    def test_defun_cannot_open_files(self):
        with pytest.raises(SlipSemanticError, match="not allowed|not defined"):
            compile_source(
                'defun pwn(x):\n    return open("/etc/passwd").read()\n'
                "module c (clk, d_in) { logic clk; logic d_in; }\n"
                'module m (clk, d_x) { logic clk; logic d_x;\n'
                '  c u1 { .clk, "d_(.*)" => "$pwn(\\1)" }; }'
            )

    def test_documented_defun_features_work(self):
        sv = _sv(
            'defun label(s):\n    return "bus_" + s.upper()\n'
            "module c (clk, data_x) { logic clk; logic data_x; }\n"
            "module m (clk, bus_X) { logic clk; logic bus_X;\n"
            '  c u1 { .clk, "data_(.*)" => "$label(\\1)" }; }', "m")
        assert ".data_x(bus_X)" in sv


class TestRegexMapping:
    def test_no_double_substitution(self):
        sv = _sv(
            "module child (clk, other) { logic clk; logic other; }\n"
            'module m (clk, ob) { logic clk; logic ob;\n'
            '  child u1 { .clk, "(.*)" => "ob" }; }', "m")
        assert "obob" not in sv

    def test_template_variable_in_seq_clock(self):
        sv = _sv(
            "module m (clk_0, clk_1, r_0, r_1) { "
            "logic clk_0; logic clk_1; logic [7:0] r_0; logic [7:0] r_1;\n"
            "  `for (`i = 0; `i < 2; `i = `i + 1) { "
            "seq (clk_`i) { r_`i = r_`i + 1; } } }", "m")
        assert "posedge clk_0" in sv and "posedge clk_1" in sv
        assert "clk_`i" not in sv


class TestDiagnostics:
    def test_unknown_instance_target_is_an_error(self):
        with pytest.raises(SlipSemanticError, match="cannot resolve target module 'childe'"):
            compile_source("module m (clk) { logic clk; childe u1 { .clk(clk) }; }")

    def test_duplicate_module_is_an_error(self):
        with pytest.raises(SlipSemanticError, match="duplicate module"):
            compile_source("module dup (a) { logic a; } module dup (b) { logic b; }")

    def test_overflowing_literal_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compile_source("module m (y) { logic [7:0] y; assign y = 300; }")
        assert any("does not fit" in str(x.message) for x in w)

    def test_fitting_literal_is_silent(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compile_source("module m (y) { logic [7:0] y; assign y = 42; }")
        assert not any("fit" in str(x.message) or "mismatch" in str(x.message) for x in w)


class TestParserGapsClosed:
    def test_assign_keyword_accepts_compound(self):
        sv = _sv("module m (clk, x, a) { logic [7:0] x; logic [7:0] a; "
                 "seq (clk) { assign x += a; } }", "m")
        assert "x <= x + a" in sv


class TestElementLevelLoopDetection:
    """Loop detection distinguishes storage, not just signal names."""

    def test_indexed_chain_is_not_a_loop(self):
        sv = _sv(
            "module m (din, dout) { logic [7:0] din; logic [7:0] dout; "
            "logic [7:0] st [0:2]; "
            "assign st[0] = din; assign st[1] = st[0]; assign st[2] = st[1]; "
            "assign dout = st[2]; }", "m")
        assert "assign st[1] = st[0];" in sv

    def test_metaprogrammed_chain_is_not_a_loop(self):
        sv = _sv(
            "module m (din, dout) { logic [7:0] din; logic [7:0] dout; "
            "logic [7:0] st [0:2]; assign st[0] = din; "
            "`for (`i = 1; `i < 3; `i = `i + 1) { assign st[`i] = st[`i - 1]; } "
            "assign dout = st[2]; }", "m")
        assert "assign st[2] = st[1];" in sv

    def test_indexed_cycle_detected(self):
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source(
                "module m (din, dout) { logic [7:0] din; logic [7:0] dout; "
                "logic [7:0] st [0:2]; "
                "assign st[0] = st[2]; assign st[1] = st[0]; assign st[2] = st[1]; "
                "assign dout = st[2]; }"
            )

    def test_bit_self_feedback_detected(self):
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source(
                "module m (a, y) { logic [7:0] a; logic [7:0] y; "
                "assign y[2] = y[2] & a[2]; }"
            )

    def test_loop_message_names_the_indexed_storage(self):
        with pytest.raises(SlipSemanticError) as e:
            compile_source(
                "module m (a, y) { logic [7:0] a; logic [7:0] y; "
                "assign y[2] = y[2] & a[2]; }"
            )
        assert "y[2]" in str(e.value)
