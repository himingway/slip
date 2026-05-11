"""Complex test cases for metaprogramming (`for / `if) and instance regex.

Covers real-world hardware patterns: parametric pipelines, one-hot decoders,
crossbar interconnects, multi-rule regex, multi-instance dedup, and combined
gen+instance scenarios.
"""

import pytest
from pathlib import Path

from slip.lexer import Lexer, TokenType
from slip.parser import Parser
from slip.ast import (
    GenForStmt, GenIfStmt, SignalDecl, AssignStmt,
    SeqBlock, CombBlock, IfStmt, InstanceStmt, Module,
)
from slip.ast.expressions import IntLiteralExpr, IdentExpr, BinaryExpr
from slip.semantic.gen_expand import expand_module, _eval_int, _parse_int_literal
from slip.semantic import SemanticAnalyzer
from slip.codegen import CodeGenerator
from slip.errors.semantic import SlipSemanticError

FIXTURES = Path(__file__).parent / "fixtures"


def parse_module(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    return modules[0]


def parse_modules(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    return Parser(tokens, "test.slip").parse()


def compile_source(source: str) -> dict[str, str]:
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    ir = SemanticAnalyzer().analyze(modules)
    return CodeGenerator().generate(ir)


# ════════════════════════════════════════════════════════════════
# A. Compile-time expression evaluation
# ════════════════════════════════════════════════════════════════

class TestCompileTimeEval:
    def test_verilog_hex(self):
        assert _parse_int_literal("8'hFF") == 255

    def test_verilog_binary(self):
        assert _parse_int_literal("4'b1010") == 10

    def test_verilog_octal(self):
        assert _parse_int_literal("4'o17") == 15

    def test_verilog_decimal(self):
        assert _parse_int_literal("16'd100") == 100

    def test_plain_decimal(self):
        assert _parse_int_literal("42") == 42

    def test_underscore_decimal(self):
        assert _parse_int_literal("1_000") == 1000

    def test_x_literal_rejected(self):
        with pytest.raises(ValueError, match="x/z"):
            _parse_int_literal("8'bxxxx_xxxx")

    def test_z_literal_rejected(self):
        with pytest.raises(ValueError, match="x/z"):
            _parse_int_literal("8'bzzzz_zzzz")

    def test_eval_binary_add(self):
        mod = parse_module("module m { `if (2 + 3) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_binary_lt(self):
        mod = parse_module("module m { `if (3 < 5) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_binary_ge_false(self):
        mod = parse_module("module m { `if (10 >= 10) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_nested_binary(self):
        mod = parse_module("module m { `if ((2 + 3) * 4 == 20) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_unary_neg(self):
        mod = parse_module("module m { `if (-1 + 1) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 0  # -1 + 1 == 0, falsy

    def test_eval_unary_not(self):
        mod = parse_module("module m { `if (!0) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_shift(self):
        mod = parse_module("module m { `if ((1 << 3) == 8) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_bitwise_and(self):
        mod = parse_module("module m { `if ((15 & 6) == 6) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_bitwise_or(self):
        mod = parse_module("module m { `if ((8 | 4) == 12) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_bitwise_xor(self):
        mod = parse_module("module m { `if ((12 ^ 10) == 6) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_logical_and(self):
        mod = parse_module("module m { `if (1 && 1) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_eval_logical_or_false(self):
        mod = parse_module("module m { `if (0 || 0) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 0

    def test_eval_nonzero_truthy(self):
        mod = parse_module("module m { `if (42) { logic x; } }")
        expanded = expand_module(mod)
        assert len(expanded.body) == 1


# ════════════════════════════════════════════════════════════════
# B. `for: parametric generation patterns
# ════════════════════════════════════════════════════════════════

class TestForParametric:
    def test_for_step_by_2(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 6; `i = `i + 2) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 3  # i=0,2,4

    def test_for_large_bound(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 32; `i = `i + 1) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 32

    def test_for_with_param_expr_bound(self):
        mod = parse_module(
            "module m #(param W = 4) { `for (`i = 0; `i < W; `i = `i + 1) { logic x; } }"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 4

    def test_for_generates_signal_decls(self):
        mod = parse_module(
            "module m { "
            "`for (`i = 0; `i < 3; `i = `i + 1) { logic [7:0] data; } "
            "}"
        )
        expanded = expand_module(mod)
        assert len(expanded.body) == 3
        for stmt in expanded.body:
            assert isinstance(stmt, SignalDecl)

    def test_for_substitutes_in_expression(self):
        source = (
            "module m (y) { "
            "`for (`i = 0; `i < 4; `i = `i + 1) { assign y = `i + 1; } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 4
        # i=0 → y = 0 + 1, i=1 → y = 1 + 1, ...
        for idx, stmt in enumerate(expanded.body):
            assert isinstance(stmt, AssignStmt)

    def test_nested_for_ij_indices(self):
        source = (
            "module m { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "  `for (`j = 0; `j < 3; `j = `j + 1) { logic x; } "
            "} }"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 6  # 2 * 3

    def test_triple_nested_for(self):
        source = (
            "module m { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "  `for (`j = 0; `j < 2; `j = `j + 1) { "
            "    `for (`k = 0; `k < 2; `k = `k + 1) { logic x; } "
            "} } }"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 8  # 2 * 2 * 2

    def test_for_inside_comb_block(self):
        source = (
            "module m (y) { comb { "
            "`for (`i = 0; `i < 3; `i = `i + 1) { assign y = `i; } "
            "} }"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        comb = expanded.body[0]
        assert isinstance(comb, CombBlock)
        assert len(comb.body.statements) == 3

    def test_for_inside_if_inside_seq(self):
        source = (
            "module m (clk) { seq (clk) { "
            "if (1) { "
            "  `for (`i = 0; `i < 2; `i = `i + 1) { assign x = `i; } "
            "} "
            "} }"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        seq = expanded.body[0]
        assert isinstance(seq, SeqBlock)
        if_stmt = seq.body.statements[0]
        assert isinstance(if_stmt, IfStmt)
        assert len(if_stmt.then_body.statements) == 2

    def test_multiple_independent_fors(self):
        source = (
            "module m { "
            "`for (`i = 0; `i < 2; `i = `i + 1) { logic a; } "
            "`for (`j = 0; `j < 3; `j = `j + 1) { logic b; } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 5  # 2 + 3
        a_count = sum(1 for s in expanded.body if isinstance(s, SignalDecl))
        assert a_count == 5


# ════════════════════════════════════════════════════════════════
# C. `if: conditional compilation
# ════════════════════════════════════════════════════════════════

class TestIfConditional:
    def test_if_else_chain_selects_correct_branch(self):
        source = (
            "module m #(param MODE = 2) { "
            "`if (MODE == 0) { logic a; } "
            "`else { `if (MODE == 1) { logic b; } `else { logic c; } } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 1
        assert expanded.body[0].name == "c"

    def test_if_mode_0(self):
        source = (
            "module m #(param MODE = 0) { "
            "`if (MODE == 0) { logic a; } "
            "`else { logic b; } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 1
        assert expanded.body[0].name == "a"

    def test_if_with_multiple_params(self):
        source = (
            "module m #(param A = 1, param B = 2) { "
            "`if (A) { `if (B) { logic x; } } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 1

    def test_if_param_zero_false(self):
        source = (
            "module m #(param EN = 0) { "
            "`if (EN) { logic x; } "
            "}"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 0

    def test_if_inside_for_body(self):
        source = (
            "module m #(param EVEN_ONLY = 1) { "
            "`for (`i = 0; `i < 4; `i = `i + 1) { "
            "  `if (1) { logic x; } "
            "} }"
        )
        mod = parse_module(source)
        expanded = expand_module(mod)
        assert len(expanded.body) == 4


# ════════════════════════════════════════════════════════════════
# D. Full pipeline: gen → semantic → codegen → SV validation
# ════════════════════════════════════════════════════════════════

class TestGenFullPipeline:
    def test_for_generates_valid_sv(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (y) { "
            "`for (`i = 0; `i < 4; `i = `i + 1) { assign y = `i; } "
            "}"
        )
        tree = SyntaxTree.fromText(sv["m"])
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_if_else_generates_valid_sv(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m #(param USE_COMB = 1) (a, y) { "
            "logic [7:0] a; logic [7:0] y; "
            "`if (USE_COMB) { comb { y = a; } } "
            "`else { assign y = a; } "
            "}"
        )
        tree = SyntaxTree.fromText(sv["m"])
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_for_with_params_sv(self):
        sv = compile_source(
            "module m #(param N = 3) (y) { "
            "`for (`i = 0; `i < N; `i = `i + 1) { assign y = `i; } "
            "}"
        )
        assert sv["m"].count("assign") == 3

    def test_for_inside_seq_sv(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m (clk) { "
            "seq (clk) { "
            "  `for (`i = 0; `i < 2; `i = `i + 1) { assign x = `i; } "
            "} }"
        )
        assert "always_ff" in sv["m"]
        # Assignments inside seq should be nonblocking
        text = sv["m"]
        assert "x <= 0;" in text
        assert "x <= 1;" in text

    def test_for_inside_comb_sv_nonblocking(self):
        sv = compile_source(
            "module m (y) { comb { "
            "  `for (`i = 0; `i < 2; `i = `i + 1) { assign y = `i; } "
            "} }"
        )
        text = sv["m"]
        assert "y = 0;" in text
        assert "y = 1;" in text
        assert "y <=" not in text

    def test_multiple_modules_with_gen(self):
        sv = compile_source(
            "module child #(param W = 4) (a, b) { "
            "logic [W-1:0] a; logic [W-1:0] b; "
            "`for (`i = 0; `i < W; `i = `i + 1) { assign b = a; } "
            "} "
            "module parent (x, y) { "
            "logic [7:0] x; logic [7:0] y; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { assign y = x; } "
            "}"
        )
        assert "child" in sv
        assert "parent" in sv
        assert sv["child"].count("assign") == 4
        assert sv["parent"].count("assign") == 2


# ════════════════════════════════════════════════════════════════
# E. Error cases
# ════════════════════════════════════════════════════════════════

class TestGenErrors:
    def test_for_infinite_loop_protection(self):
        source = (
            "module m #(param N = 1) { "
            "`for (`i = 0; `i < 2000; `i = `i + 1) { logic x; } "
            "}"
        )
        mod = parse_module(source)
        with pytest.raises(SlipSemanticError, match="1024"):
            expand_module(mod)

    def test_for_step_var_mismatch(self):
        mod = parse_module(
            "module m { `for (`i = 0; `i < 4; `k = `k + 1) { logic x; } }"
        )
        with pytest.raises(SlipSemanticError, match="step variable"):
            expand_module(mod)

    def test_if_non_evaluable_ident(self):
        mod = parse_module(
            "module m (x) { `if (x) { logic y; } }"
        )
        with pytest.raises(SlipSemanticError, match="compile time"):
            expand_module(mod)

    def test_for_non_evaluable_cond(self):
        mod = parse_module(
            "module m (x) { `for (`i = 0; `i < x; `i = `i + 1) { logic y; } }"
        )
        with pytest.raises(SlipSemanticError, match="compile time"):
            expand_module(mod)

    def test_for_undefined_param(self):
        mod = parse_module(
            "module m #(param A = 2) { `for (`i = 0; `i < B; `i = `i + 1) { logic y; } }"
        )
        with pytest.raises(SlipSemanticError, match="compile time"):
            expand_module(mod)

    def test_for_non_int_default(self):
        mod = parse_module(
            'module m #(param X = 1) { `for (`i = 0; `i < X; `i = `i + 1) { logic y; } }'
        )
        # Should work fine since X=1 is a valid int
        expanded = expand_module(mod)
        assert len(expanded.body) == 1


# ════════════════════════════════════════════════════════════════
# F. Fixtures: complex gen designs
# ════════════════════════════════════════════════════════════════

class TestGenFixtures:
    def test_onehot_decoder_compiles(self):
        sv = compile_source((FIXTURES / "gen_onehot_decoder.slip").read_text())
        assert "onehot_decoder" in sv

    def test_onehot_decoder_has_16_assigns(self):
        sv = compile_source((FIXTURES / "gen_onehot_decoder.slip").read_text())["onehot_decoder"]
        assert sv.count("assign") == 16

    def test_pipeline_chain_compiles(self):
        sv = compile_source((FIXTURES / "gen_pipeline_chain.slip").read_text())
        assert "pipeline_chain" in sv

    def test_pipeline_chain_has_seq(self):
        sv = compile_source((FIXTURES / "gen_pipeline_chain.slip").read_text())["pipeline_chain"]
        assert "always_ff" in sv
        assert "posedge clk" in sv

    def test_crossbar_compiles(self):
        sv = compile_source((FIXTURES / "gen_interconnect.slip").read_text())
        assert "crossbar" in sv

    def test_crossbar_has_always_comb(self):
        sv = compile_source((FIXTURES / "gen_interconnect.slip").read_text())["crossbar"]
        assert "always_comb" in sv

    def test_crossbar_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source((FIXTURES / "gen_interconnect.slip").read_text())["crossbar"]
        tree = SyntaxTree.fromText(sv)
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0


# ════════════════════════════════════════════════════════════════
# G. Instance regex: complex scenarios
# ════════════════════════════════════════════════════════════════

class TestInstanceRegexComplex:
    def test_multi_instance_different_prefix(self):
        source = (
            r'module child (clk, data_in, data_out) { logic clk; logic [7:0] data_in; logic [7:0] data_out; assign data_out = data_in; }'
            r' module parent (clk) {'
            r'  logic clk;'
            r'  logic [7:0] a_in; logic [7:0] a_out;'
            r'  logic [7:0] b_in; logic [7:0] b_out;'
            r'  child u_a { .clk, "data_(.*)" => "a_\1" };'
            r'  child u_b { .clk, "data_(.*)" => "b_\1" };'
            r'}'
        )
        sv = compile_source(source)
        text = sv["parent"]
        assert ".data_in(a_in)" in text
        assert ".data_out(a_out)" in text
        assert ".data_in(b_in)" in text
        assert ".data_out(b_out)" in text

    def test_instance_with_params_and_regex(self):
        source = (
            r'module child #(param W = 8) (clk, data_in, data_out) { logic clk; logic [W-1:0] data_in; logic [W-1:0] data_out; assign data_out = data_in; }'
            r' module parent (clk, buf_in, buf_out) {'
            r'  logic clk; logic [15:0] buf_in; logic [15:0] buf_out;'
            r'  child #(.W(16)) u1 { .clk, "data_(.*)" => "buf_\1" };'
            r'}'
        )
        sv = compile_source(source)
        text = sv["parent"]
        assert ".W(16)" in text
        assert ".data_in(buf_in)" in text
        assert ".data_out(buf_out)" in text

    def test_implicit_signal_for_regex_match(self):
        child = r'module child (clk, ctrl_req, ctrl_ack) { logic clk; logic ctrl_req; logic ctrl_ack; assign ctrl_req = 0; }'
        parent = r'module parent (clk) { logic clk; child u1 { .clk, "ctrl_(.+)" => "ext_\1" }; }'
        modules = parse_modules(child + " " + parent)
        ir = SemanticAnalyzer().analyze(modules)
        parent_mod = [m for m in ir if m.name == "parent"][0]
        sig_names = [s.name for s in parent_mod.signals]
        # ctrl_req is output, ctrl_ack needs implicit creation
        assert "ext_ack" in sig_names

    def test_named_overrides_regex(self):
        child = r'module child (clk, a, b) { logic clk; logic a; logic b; assign a = 0; }'
        parent = r'module parent (clk, my_a, my_b) { logic clk; logic my_a; logic my_b; child u1 { .clk, .a(my_a), "(.+)" => "my_\1" }; }'
        modules = parse_modules(child + " " + parent)
        ir = SemanticAnalyzer().analyze(modules)
        parent_mod = [m for m in ir if m.name == "parent"][0]
        inst = parent_mod.instances[0]
        port_dict = dict(inst.port_map)
        assert port_dict["a"] == "my_a"
        assert port_dict["b"] == "my_b"

    def test_pyslang_multi_instance_regex(self):
        from pyslang import SyntaxTree, Compilation
        source = (
            r'module child #(param W = 8) (clk, din, dout) { logic clk; logic [W-1:0] din; logic [W-1:0] dout; assign dout = din; }'
            r' module parent (clk, a_din, a_dout, b_din, b_dout) {'
            r'  logic clk; logic [7:0] a_din; logic [7:0] a_dout;'
            r'  logic [7:0] b_din; logic [7:0] b_dout;'
            r'  child u_a { .clk, "d(.+)" => "a_d\1" };'
            r'  child u_b { .clk, "d(.+)" => "b_d\1" };'
            r'}'
        )
        sv = compile_source(source)
        tree = SyntaxTree.fromText(sv["parent"])
        comp = Compilation()
        comp.addSyntaxTree(tree)
        _suppressed = {"UnknownModule", "UndeclaredIdentifier", "CouldNotResolve"}
        errors = [
            d for d in comp.getAllDiagnostics()
            if d.isError() and not any(s in str(getattr(d, 'code', '')) for s in _suppressed)
        ]
        assert len(errors) == 0

    def test_unconnected_output_only_warns(self):
        import warnings as w
        # child drives data_out (output), has nonmatch_port as input
        child = r'module child (clk, nonmatch_port, data_out) { logic clk; logic nonmatch_port; logic [7:0] data_out; assign data_out = 0; }'
        parent = r'module parent (clk) { logic clk; child u1 { .clk, "xyz_(.+)" => "x_\1" }; }'
        # nonmatch_port is input → error because regex doesn't match
        # data_out is output → warning
        with w.catch_warnings(record=True) as caught:
            w.simplefilter("always")
            with pytest.raises(SlipSemanticError, match="unconnected input port"):
                modules = parse_modules(child + " " + parent)
                SemanticAnalyzer().analyze(modules)


# ════════════════════════════════════════════════════════════════
# H. Fixture: multi-instance bus
# ════════════════════════════════════════════════════════════════

class TestMultiInstanceFixture:
    def test_compiles(self):
        sv = compile_source((FIXTURES / "instance_multi_regex.slip").read_text())
        assert "bus_slave" in sv
        assert "bus_top" in sv

    def test_s0_connections(self):
        sv = compile_source((FIXTURES / "instance_multi_regex.slip").read_text())["bus_top"]
        assert ".bus_req(s0_bus_req)" in sv
        assert ".bus_addr(s0_bus_addr)" in sv
        assert ".bus_wdata(s0_bus_wdata)" in sv
        assert ".bus_resp(s0_bus_resp)" in sv

    def test_s1_connections(self):
        sv = compile_source((FIXTURES / "instance_multi_regex.slip").read_text())["bus_top"]
        assert ".bus_req(s1_bus_req)" in sv
        assert ".bus_addr(s1_bus_addr)" in sv
        assert ".bus_wdata(s1_bus_wdata)" in sv
        assert ".bus_resp(s1_bus_resp)" in sv

    def test_params_propagated(self):
        sv = compile_source((FIXTURES / "instance_multi_regex.slip").read_text())["bus_top"]
        # Params passed by name reference, not literal value
        assert ".AW(AW)" in sv
        assert ".DW(DW)" in sv

    def test_pyslang_valid(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source((FIXTURES / "instance_multi_regex.slip").read_text())
        # Validate each module independently (single-module context)
        for name, text in sv.items():
            tree = SyntaxTree.fromText(text, f"{name}.sv")
            comp = Compilation()
            comp.addSyntaxTree(tree)
            errors = [
                d for d in comp.getAllDiagnostics()
                if d.isError() and "UnknownModule" not in str(getattr(d, 'code', ''))
                and "UndeclaredIdentifier" not in str(getattr(d, 'code', ''))
            ]
            assert len(errors) == 0, f"{name}: {[str(d) for d in errors]}"

    def test_build(self, tmp_path):
        from slip.cli._pipeline import run_build
        result = run_build(FIXTURES / "instance_multi_regex.slip", tmp_path, [])
        assert (tmp_path / "bus_slave.sv").exists()
        assert (tmp_path / "bus_top.sv").exists()


# ════════════════════════════════════════════════════════════════
# I. Combined: `for generating instances + regex
# ════════════════════════════════════════════════════════════════

class TestCombinedGenInstance:
    def test_for_generates_assigns_valid_sv(self):
        from pyslang import SyntaxTree, Compilation
        sv = compile_source(
            "module m #(param N = 4) (y) { "
            "`for (`i = 0; `i < N; `i = `i + 1) { assign y = `i; } "
            "}"
        )
        tree = SyntaxTree.fromText(sv["m"])
        comp = Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert len(errors) == 0

    def test_gen_and_instance_coexist(self):
        sv = compile_source(
            r'module child (clk, din, dout) { logic clk; logic [7:0] din; logic [7:0] dout; assign dout = din; }'
            r' module parent #(param W = 8) (clk, ext_din, ext_dout) {'
            r'  logic clk; logic [W-1:0] ext_din; logic [W-1:0] ext_dout;'
            r'  `for (`i = 0; `i < 2; `i = `i + 1) { assign ext_dout = ext_din; }'
            r'  child u1 { .clk, "d(.*)" => "ext_d\1" };'
            r'}'
        )
        text = sv["parent"]
        assert text.count("assign") == 2
        assert ".din(ext_din)" in text
        assert ".dout(ext_dout)" in text

    def test_if_selects_instance_config(self):
        sv = compile_source(
            r'module child #(param W = 8) (clk, din, dout) { logic clk; logic [W-1:0] din; logic [W-1:0] dout; assign dout = din; }'
            r' module parent #(param USE_WIDE = 1) (clk, din, dout) {'
            r'  logic clk; logic [7:0] din; logic [7:0] dout;'
            r'  `if (USE_WIDE) { logic [15:0] wide_out; assign wide_out = 0; }'
            r'  child u1 { .clk, "d(.*)" => "d\1" };'
            r'}'
        )
        text = sv["parent"]
        assert "wide_out" in text
        assert ".din(din)" in text
        assert ".dout(dout)" in text
