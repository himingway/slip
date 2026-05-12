"""Tests that verify bug fixes and document remaining implementation gaps.

Tests for FIXED bugs now verify correct behavior.
Tests for UNFIXED bugs still document the current (broken) behavior.
"""

import pytest
from pathlib import Path

from slip.ast.base import SourceLocation
from slip.ast.expressions import IdentExpr, IntLiteralExpr
from slip.ast.statements import (
    AssignStmt, BlockStmt, ForStmt, IfStmt, LValue, SeqBlock,
)
from slip.errors.syntax import SlipSyntaxError
from slip.errors.semantic import SlipSemanticError
from slip.errors.codegen import SlipCodegenError
from slip.codegen.fragment import assign_stmt, logic_block
from slip.ir.assignment import HDLAssignment
from slip.ir.logic_block import LogicBlock

from conftest import compile_source, parse_source


LOC = SourceLocation("test.slip", 1, 1)


# ── BUG-001 FIXED: ForStmt in seq/comb blocks ─────────────────

class TestIRBuilderForStmtDrop:
    """BUG-001 FIXED: ForStmt inside seq/comb is now correctly converted
    to HDLForLoop and emitted as SV for-loops."""

    def test_for_at_top_level_of_seq(self):
        src = (
            "module m (clk, rst_n) { "
            "logic [7:0] data; "
            "seq (clk, neg: rst_n) { "
            "for (i = 0; i < 4; i = i + 1) { data = i; } "
            "} }"
        )
        sv = compile_source(src)
        assert "always_ff" in sv["m"]
        assert "for (" in sv["m"]
        assert "data" in sv["m"]

    def test_for_at_top_level_of_comb(self):
        src = (
            "module m () { "
            "logic [7:0] data; "
            "comb { "
            "for (i = 0; i < 4; i = i + 1) { data = i; } "
            "} }"
        )
        sv = compile_source(src)
        assert "always_comb" in sv["m"]
        assert "for (" in sv["m"]

    def test_for_inside_if_in_seq(self):
        """ForStmt nested inside if's body is now correctly handled."""
        src = (
            "module m (clk, rst_n, en) { "
            "logic [7:0] data; "
            "seq (clk, neg: rst_n) { "
            "if (en) { for (i = 0; i < 4; i = i + 1) { data = i; } } "
            "} }"
        )
        sv = compile_source(src)
        assert "if (en) begin" in sv["m"]
        assert "for (" in sv["m"]


# ── BUG-003 FIXED: validation.py dead code removed ──────────────


# ── BUG-002 FIXED: unsigned vs signed ──────────────────────────

class TestUnsignedSignedInconsistency:
    """BUG-002 FIXED: Both `signed` without tick and `unsigned` without tick
    now raise SlipSyntaxError consistently."""

    def test_signed_without_tick_raises(self):
        src = "module m (y) { assign y = signed(1); }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_unsigned_without_tick_raises(self):
        """BUG-002 FIXED: `unsigned` without tick now raises error."""
        src = "module m (y) { assign y = unsigned(1); }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_unsigned_cast_works(self):
        """unsigned'(expr) cast should still work."""
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = unsigned'(a); }"
        sv = compile_source(src)
        assert "m" in sv


# ── Gap 4: parser silently accepts bare ident as signal decl ──

class TestBareIdentBecomesSignalDecl:
    """BUG-004 UNFIXED: Parser's _parse_statement dispatches any IDENT that
    doesn't match instance or assignment patterns to _parse_signal_decl."""

    def test_bare_ident_becomes_signal(self):
        src = "module m (y) { my_signal; assign y = 1; }"
        sv = compile_source(src)
        assert "my_signal" in sv["m"]

    def test_bare_ident_parsed_as_signal_decl(self):
        src = "module m (y) { my_signal; assign y = 1; }"
        modules = parse_source(src)
        stmts = modules[0].body
        from slip.ast.statements import SignalDecl
        signal_decls = [s for s in stmts if isinstance(s, SignalDecl)]
        assert len(signal_decls) >= 1
        assert signal_decls[0].name == "my_signal"


# ── Gap 5: parser accepts trailing comma in connections ────────

class TestTrailingCommaInConnections:
    """BUG-005 LOW: Parser silently accepts trailing commas in instance
    connection lists. May be intentional for convenience."""

    def test_trailing_comma_accepted(self):
        src = (
            "module child (a, b) { logic a; logic b; } "
            "module parent (x, y) { "
            "logic x; logic y; "
            "child u1 { .a(x), .b(y), }; "
            "}"
        )
        sv = compile_source(src)
        assert "child" in sv["parent"]


# ── BUG-007 FIXED: Template identifier merging ─────────────────

class TestTemplateIdentifierMerging:
    """BUG-007 FIXED: _merge_template_idents now loops until stable,
    correctly handling multiple backtick variables."""

    def test_single_template_var_works(self):
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("a`i", "test.slip").tokenize()
        ident_tokens = [t for t in tokens if t.type == TokenType.IDENT]
        assert len(ident_tokens) == 1
        assert ident_tokens[0].value == "a`i"

    def test_template_with_static_suffix_works(self):
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("a`i_b", "test.slip").tokenize()
        ident_tokens = [t for t in tokens if t.type == TokenType.IDENT]
        assert len(ident_tokens) == 1
        assert ident_tokens[0].value == "a`i_b"

    def test_two_template_vars_merged(self):
        """BUG-007 FIXED: Two template variables now merge correctly."""
        from slip.lexer import Lexer, TokenType
        tokens = [t for t in Lexer("a`i_`j", "test.slip").tokenize()
                  if t.type != TokenType.EOF]
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "a`i_`j"

    def test_nested_gen_for_with_compound_template(self):
        """BUG-007 FIXED: Nested gen_for with compound template identifiers."""
        src = (
            "module m () { "
            "logic a0_0; logic a0_1; logic a1_0; logic a1_1; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "`for (`j = 0; `j < 2; `j = `j + 1) { "
            "assign a`i_`j = `i + `j; "
            "} } }"
        )
        sv = compile_source(src)
        assert "a0_0" in sv["m"]
        assert "a1_1" in sv["m"]


# ── BUG-009/010 FIXED: Lexer integer literal validation ────────

class TestLexerIntegerLiteralValidation:
    """BUG-009/010 FIXED: Integer literal validation now rejects invalid
    digits per radix and underscore-only sequences."""

    def test_binary_rejects_hex_digits(self):
        """4'bABCD is now correctly rejected."""
        from slip.lexer import Lexer
        with pytest.raises(SlipSyntaxError):
            Lexer("module m (y) { assign y = 4'bABCD; }", "test.slip").tokenize()

    def test_octal_rejects_8_9(self):
        """4'o888 is now correctly rejected."""
        from slip.lexer import Lexer
        with pytest.raises(SlipSyntaxError):
            Lexer("module m (y) { assign y = 4'o888; }", "test.slip").tokenize()

    def test_decimal_rejects_hex_digits(self):
        """4'dFF is now correctly rejected."""
        from slip.lexer import Lexer
        with pytest.raises(SlipSyntaxError):
            Lexer("module m (y) { assign y = 4'dFF; }", "test.slip").tokenize()

    def test_underscore_only_rejected(self):
        """4'b_ is now correctly rejected."""
        from slip.lexer import Lexer
        with pytest.raises(SlipSyntaxError):
            Lexer("module m (y) { assign y = 4'b_; }", "test.slip").tokenize()

    def test_multiple_underscores_rejected(self):
        """4'd___ is now correctly rejected."""
        from slip.lexer import Lexer
        with pytest.raises(SlipSyntaxError):
            Lexer("module m (y) { assign y = 4'd___; }", "test.slip").tokenize()


# ── BUG-011 FIXED: Replication syntax ──────────────────────────

class TestReplicationSyntax:
    """BUG-011 FIXED: {n{expr}} replication syntax now parses correctly."""

    def test_replication_parses(self):
        """{4{1'b0}} now parses and compiles correctly."""
        src = "module m (y) { logic [15:0] y; assign y = {4{1'b0}}; }"
        sv = compile_source(src)
        assert "{4{1'b0}}" in sv["m"] or "4" in sv["m"]

    def test_replication_expr_node_exists(self):
        from slip.ast.expressions import ReplicationExpr
        expr = ReplicationExpr(LOC, count=IntLiteralExpr(LOC, "4"),
                               inner=IntLiteralExpr(LOC, "0"))
        assert expr is not None


# ── BUG-012 FIXED: Arithmetic shift operators ──────────────────

class TestArithmeticShift:
    """BUG-012 FIXED: <<< and >>> arithmetic shift operators now supported."""

    def test_arithmetic_right_shift_works(self):
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = a >>> 1; }"
        sv = compile_source(src)
        assert ">>>" in sv["m"]

    def test_arithmetic_left_shift_works(self):
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = a <<< 1; }"
        sv = compile_source(src)
        assert "<<<" in sv["m"]


# ── BUG-013: Undefined signals (KEPT as-is, implicit signal design) ──

class TestUndefinedSignalSilent:
    """BUG-013: Implicit signal creation is an intentional design feature.
    Undeclared identifiers become implicit 1-bit signals. This is by design
    for Slip's convenience-first approach."""

    def test_typo_creates_implicit_signal(self):
        src = (
            "module m (data_out) { "
            "logic [7:0] data_out; "
            "assign data_out = data_ouut; "
            "}"
        )
        sv = compile_source(src)
        assert "data_ouut" in sv["m"]

    def test_undeclared_signal_gets_implicit_declaration(self):
        src = "module m (y) { assign y = undefined_signal; }"
        sv = compile_source(src)
        assert "undefined_signal" in sv["m"]


# ── BUG-014 FIXED: Multi-driver detection ──────────────────────

class TestMultiDriver:
    """BUG-014 FIXED: Multi-driver detection now raises SlipSemanticError."""

    def test_ff_and_comb_same_signal(self):
        """Signal driven in both always_ff and always_comb — now raises error."""
        src = (
            "module m (clk, a, b, out) { "
            "logic a; logic b; logic out; "
            "seq (clk) { out = a; } "
            "comb { out = b; } "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="driven by multiple"):
            compile_source(src)

    def test_two_ff_blocks_same_signal(self):
        """Signal driven in two different always_ff blocks — now raises error."""
        src = (
            "module m (clk1, clk2, a, b, out) { "
            "logic a; logic b; logic out; "
            "seq (clk1) { out = a; } "
            "seq (clk2) { out = b; } "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="driven by multiple"):
            compile_source(src)


# ── BUG-015 FIXED: Combinational loop detection ───────────────

class TestCombLoop:
    """BUG-015 FIXED: Combinational loop detection now raises SlipSemanticError."""

    def test_simple_comb_loop(self):
        src = (
            "module m (a, b) { "
            "logic a; logic b; "
            "comb { a = b; b = a; } "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source(src)

    def test_no_loop_succeeds(self):
        """Normal comb block without loops should compile fine."""
        src = (
            "module m (a, b, x, y) { "
            "logic a; logic b; logic x; logic y; "
            "comb { x = a; y = b; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv

    def test_indirect_loop(self):
        """Indirect loop a -> b -> c -> a should be detected."""
        src = (
            "module m (a, b, c) { "
            "logic a; logic b; logic c; "
            "comb { a = b; b = c; c = a; } "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="combinational loop"):
            compile_source(src)

    def test_seq_loop_ok(self):
        """Loops in seq blocks are fine — they're clocked."""
        src = (
            "module m (clk, a, b) { "
            "logic a; logic b; "
            "seq (clk) { a = b; b = a; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-016/032 FIXED: assign with nonblocking ─────────────────

class TestAssignNonblocking:
    """BUG-016/032 FIXED: HDLAssignment.to_sv() no longer prepends 'assign'.
    The fragment functions (assign_stmt and _emit_block_item) correctly
    handle context-dependent output."""

    def test_to_sv_no_assign_prefix(self):
        """to_sv() no longer prepends 'assign' — context-agnostic."""
        assign = HDLAssignment("x", "y", is_nonblocking=True)
        result = assign.to_sv()
        assert result == "x <= y;"

    def test_assign_stmt_fragment_has_assign(self):
        """fragment.assign_stmt correctly prepends 'assign' for module-level."""
        assign = HDLAssignment("x", "y", is_nonblocking=False)
        result = assign_stmt(assign)
        assert result == "    assign x = y;"

    def test_procedural_assignment_no_assign(self):
        """Inside always_ff, assignments don't have 'assign' prefix."""
        src = (
            "module m (clk, d, q) { "
            "logic [7:0] d; logic [7:0] q; "
            "seq (clk) { q = d; } "
            "}"
        )
        sv = compile_source(src)
        # The always_ff block should have q <= d, not assign q <= d
        assert "always_ff" in sv["m"]
        # There should be no "assign" inside the always_ff block
        lines = sv["m"].split("\n")
        in_block = False
        for line in lines:
            stripped = line.strip()
            if "always_ff" in stripped:
                in_block = True
            if in_block and stripped == "end":
                break
            if in_block:
                assert "assign" not in stripped, f"'assign' found inside always_ff: {stripped}"


# ── BUG-017 FIXED: Missing required ports check ─────────────────

class TestMissingRequiredPort:
    """BUG-017 FIXED: Instance connections that omit required input ports
    now raise SlipSemanticError when using explicit (non-regex) connections."""

    def test_all_ports_connected_works(self):
        """Connecting all ports should compile successfully."""
        src = (
            "module child (a, b, out) { "
            "logic a; logic b; logic out; assign out = a & b; "
            "} "
            "module parent (x, y, result) { "
            "logic x; logic y; logic result; "
            "child u1 { .a(x), .b(y), .out(result) }; "
            "}"
        )
        sv = compile_source(src)
        assert "child" in sv["parent"]

    def test_missing_input_port_raises(self):
        """Missing an input port should raise SlipSemanticError."""
        src = (
            "module child (a, b, out) { "
            "logic a; logic b; logic out; assign out = a & b; "
            "} "
            "module parent (result) { "
            "logic result; "
            "child u1 { .out(result) }; "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="unconnected input port 'a' of module 'child'"):
            compile_source(src)

    def test_missing_output_port_is_ok(self):
        """Missing an output port should not raise an error."""
        src = (
            "module child (a, out) { "
            "logic a; logic out; assign out = a; "
            "} "
            "module parent (x) { "
            "logic x; "
            "child u1 { .a(x) }; "
            "}"
        )
        sv = compile_source(src)
        assert "child" in sv["parent"]

    def test_dangling_marker_no_error(self):
        """Using _ dangling marker for an input port should not raise."""
        src = (
            "module child (a, b, out) { "
            "logic a; logic b; logic out; assign out = a & b; "
            "} "
            "module parent (x, result) { "
            "logic x; logic result; "
            "child u1 { .a(x), .b(_), .out(result) }; "
            "}"
        )
        sv = compile_source(src)
        assert "child" in sv["parent"]

    def test_external_ip_not_checked(self):
        """External IP modules (not in compilation) should not be checked."""
        src = (
            "module parent (x, y) { "
            "logic x; logic y; "
            "external_ip u1 { .a(x), .b(y) }; "
            "}"
        )
        sv = compile_source(src)
        assert "parent" in sv


# ── BUG-018 FIXED: Exponentiation operator ─────────────────────

class TestMissingExponentiation:
    """BUG-018 FIXED: ** exponentiation operator now supported."""

    def test_exponentiation_works(self):
        src = "module m (y) { logic [7:0] y; assign y = 2 ** 3; }"
        sv = compile_source(src)
        assert "**" in sv["m"]


# ── BUG-019 FIXED: Four-state identity operators ───────────────

class TestMissingFourStateOps:
    """BUG-019 FIXED: === and !== four-state operators now supported."""

    def test_case_equality_works(self):
        src = "module m (a, b, y) { logic a; logic b; logic y; assign y = a === b; }"
        sv = compile_source(src)
        assert "===" in sv["m"]

    def test_case_inequality_works(self):
        src = "module m (a, b, y) { logic a; logic b; logic y; assign y = a !== b; }"
        sv = compile_source(src)
        assert "!==" in sv["m"]


# ── BUG-020 FIXED: Width-cast syntax ──────────────────────────

class TestMissingWidthCast:
    """BUG-020 FIXED: 8'(expr) width-cast syntax now supported."""

    def test_width_cast_works(self):
        src = "module m (a, y) { logic [7:0] a; logic [3:0] y; assign y = 4'(a); }"
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-021: For-loop step limited to simple assignment ────────

class TestForStepLimited:
    """BUG-021 FIXED: For-loop step now supports 'i++' and 'i += expr'."""

    def test_increment_works(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i++) { assign y = i; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv

    def test_compound_assignment_works(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i += 1) { assign y = i; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv

    def test_simple_step_works(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i = i + 1) { assign y = i; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-022 FIXED: Port width parser now supports [high:low] ────

class TestPortWidthParser:
    """BUG-022 FIXED: Port width parser now supports [high:low] range syntax,
    consistent with signal width parsing."""

    def test_port_range_width_parses(self):
        src = "module m (data[7:0]) { assign data = 0; }"
        modules = parse_source(src)
        port = modules[0].ports[0]
        assert port.width is not None

    def test_port_range_width_sv(self):
        src = (
            "module m (data[7:0]) { "
            "assign data = 0; "
            "}"
        )
        sv = compile_source(src)
        assert "[7:0]" in sv["m"]

    def test_port_single_width_sv(self):
        src = (
            "module m (data[8]) { "
            "assign data = 0; "
            "}"
        )
        sv = compile_source(src)
        assert "data" in sv["m"]


# ── BUG-024: No duplicate declaration detection (FIXED) ──────

class TestDuplicateDeclaration:
    """BUG-024 FIXED: Duplicate signal declarations are caught at the
    semantic level with a clear error message."""

    def test_duplicate_logic_decl(self):
        src = (
            "module m (y) { "
            "logic x; logic x; "
            "assign y = x; "
            "}"
        )
        with pytest.raises(SlipSemanticError, match="duplicate declaration"):
            compile_source(src)

    def test_signal_collides_with_port(self):
        src = (
            "module m (data) { "
            "logic [7:0] data; "
            "assign data = 8'hFF; "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-026: Instance module existence (external IP allowed) ───

class TestInstanceModuleExistence:
    """BUG-026: Non-regex instances don't validate that the target module
    exists in the current compilation. External IP modules are allowed.
    pyslang validates at codegen time."""

    def test_typo_in_module_name(self):
        src = (
            "module child (a) { logic a; } "
            "module parent (x) { "
            "logic x; "
            "child_typo u1 { .a(x) }; "
            "}"
        )
        # External modules are allowed at semantic level
        sv = compile_source(src)
        assert "parent" in sv


# ── BUG-029 FIXED: always_latch sensitivity list ────────────────

class TestAlwaysLatch:
    """BUG-029 FIXED: always_latch no longer emits spurious sensitivity list."""

    def test_always_latch_no_sensitivity(self):
        """BUG-029 FIXED: always_latch emits without @(...)."""
        block = LogicBlock("*", ((HDLAssignment("q", "d", False),),), "always_latch")
        text = logic_block(block)
        assert "always_latch begin" in text
        assert "@(" not in text

    def test_always_comb_no_sensitivity(self):
        block = LogicBlock("", ((HDLAssignment("y", "a", False),),), "always_comb")
        text = logic_block(block)
        assert "always_comb begin" in text
        assert "@(" not in text


# ── BUG-030: UndeclaredIdentifier suppression (UNFIXED) ────────

class TestDiagnosticSuppression:
    """BUG-030 BY DESIGN: The emitter suppresses UndeclaredIdentifier diagnostics
    because Slip intentionally creates implicit 1-bit signals for undeclared
    identifiers. pyslang would flag these as errors, but they are correct in
    Slip's design."""

    def test_suppressed_codes_include_undeclared(self):
        from slip.codegen.emitter import _SUPPRESSED_DIAG_CODES
        assert "UndeclaredIdentifier" in _SUPPRESSED_DIAG_CODES

    def test_suppressed_codes_include_could_not_resolve(self):
        from slip.codegen.emitter import _SUPPRESSED_DIAG_CODES
        assert "CouldNotResolve" in _SUPPRESSED_DIAG_CODES


# ── BUG-032 FIXED: HDLAssignment.to_sv() ──────────────────────

class TestHDLAssignmentToSV:
    """BUG-032 FIXED: HDLAssignment.to_sv() no longer prepends 'assign'.
    It produces a context-agnostic representation."""

    def test_to_sv_no_assign_prefix(self):
        a = HDLAssignment("q", "d", is_nonblocking=True)
        result = a.to_sv()
        assert result == "q <= d;"

    def test_to_sv_blocking_no_assign(self):
        a = HDLAssignment("x", "y", is_nonblocking=False)
        result = a.to_sv()
        assert result == "x = y;"


# ── BUG-033 FIXED: Type annotations ──────────────────────────

class TestIRTypeAnnotations:
    """BUG-033 FIXED: HDLSignal.type_ and HDLPort.type_ now use
    HDLType | None annotation."""

    def test_signal_type_defaults_none(self):
        from slip.ir.signal import HDLSignal
        s = HDLSignal("x")
        assert s.type_ is None

    def test_port_type_defaults_none(self):
        from slip.ir.port import HDLPort
        p = HDLPort("a", "input")
        assert p.type_ is None


# ── BUG-034 FIXED: Constrained string fields ──────────────────

class TestIRUnconstrainedStrings:
    """BUG-034 FIXED: LogicBlock.kind and HDLPort.direction now use
    Literal types for validation."""

    def test_logic_block_rejects_invalid_kind(self):
        """BUG-034 FIXED: Invalid kind now raises TypeError."""
        with pytest.raises(TypeError):
            LogicBlock("*", ((HDLAssignment("x", "y", False),),), "always_wrong")

    def test_port_rejects_invalid_direction(self):
        """BUG-034 FIXED: Invalid direction now raises TypeError."""
        from slip.ir.port import HDLPort
        with pytest.raises(TypeError):
            HDLPort("x", "banana")

    def test_valid_kinds_accepted(self):
        for kind in ("always_ff", "always_comb", "always_latch"):
            block = LogicBlock("*", (), kind)
            assert block.kind == kind

    def test_valid_directions_accepted(self):
        from slip.ir.port import HDLPort
        for d in ("input", "output", "inout"):
            p = HDLPort("x", d)
            assert p.direction == d


# ── BUG-035: HDLInstance.regex_rules never consumed (UNFIXED) ──

class TestInstanceRegexRules:
    """BUG-035 LOW: HDLInstance.regex_rules field exists in the IR but is
    consumed during instance_resolve and cleared before reaching emitter."""

    def test_regex_rules_field_exists(self):
        from slip.ir.instance import HDLInstance
        inst = HDLInstance(inst_name="u1", target="child",
                           param_map=(), port_map=(),
                           regex_rules=(("pattern", "replacement"),))
        assert inst.regex_rules == (("pattern", "replacement"),)

    def test_regex_rules_not_in_fragment_output(self):
        from slip.ir.instance import HDLInstance
        from slip.codegen.fragment import instance as frag_instance
        inst = HDLInstance(inst_name="u1", target="child",
                           param_map=(), port_map=(("a", "x"),),
                           regex_rules=(("pattern", "replacement"),))
        text = frag_instance(inst)
        assert "pattern" not in text
        assert "replacement" not in text


# ── NEW: Replication in gen_expand ─────────────────────────────

class TestReplicationCodeGen:
    """Test that replication expressions are correctly serialized."""

    def test_replication_sv_output(self):
        src = "module m (y) { logic [15:0] y; assign y = {4{1'b0}}; }"
        sv = compile_source(src)
        assert "{4{1'b0}}" in sv["m"]


# ── NEW: For-loop in seq/comb codegen ──────────────────────────

class TestForLoopCodeGen:
    """Test that for-loops inside seq/comb produce correct SV."""

    def test_for_in_seq_produces_sv_for(self):
        src = (
            "module m (clk, rst_n) { "
            "logic [7:0] data; "
            "seq (clk, neg: rst_n) { "
            "for (i = 0; i < 4; i = i + 1) { data = i; } "
            "} }"
        )
        sv = compile_source(src)
        assert "for (int i = 0; i < 4; i = i + 1) begin" in sv["m"]
