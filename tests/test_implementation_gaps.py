"""Tests that document known implementation gaps in the Slip compiler.

Each test demonstrates a behavior that is likely incorrect or incomplete.
These tests PASS to document the current behavior — they should be updated
when the corresponding implementation gap is fixed.
"""

import pytest
from pathlib import Path

from slip.ast.base import SourceLocation
from slip.ast.expressions import IdentExpr, IntLiteralExpr
from slip.ast.statements import (
    AssignStmt, BlockStmt, ForStmt, IfStmt, LValue, SeqBlock,
)
from slip.errors.syntax import SlipSyntaxError
from slip.errors.codegen import SlipCodegenError
from slip.codegen.fragment import assign_stmt, logic_block
from slip.ir.assignment import HDLAssignment
from slip.ir.logic_block import LogicBlock

from conftest import compile_source, parse_source


LOC = SourceLocation("test.slip", 1, 1)


# ── Gap 1: ir_builder._convert_block silently drops ForStmt ────

class TestIRBuilderForStmtDrop:
    """ir_builder._convert_block only handles AssignStmt and IfStmt.
    ForStmt inside a seq or comb body is silently dropped — no error,
    no warning, the for-loop body just vanishes from the output.
    The always_ff/always_comb block ends up empty."""

    def test_for_at_top_level_of_seq_dropped(self):
        src = (
            "module m (clk, rst_n) { "
            "logic [7:0] data; "
            "seq (clk, neg: rst_n) { "
            "for (i = 0; i < 4; i = i + 1) { data = i; } "
            "} }"
        )
        sv = compile_source(src)
        # The always_ff block should contain the for-loop body,
        # but _convert_block doesn't handle ForStmt, so the block is empty.
        assert "always_ff" in sv["m"]
        # The body between begin/end is empty
        lines = sv["m"].split("\n")
        begin_idx = next(i for i, l in enumerate(lines) if "begin" in l)
        end_idx = next(i for i, l in enumerate(lines) if "end" in l)
        body_lines = [l.strip() for l in lines[begin_idx + 1 : end_idx] if l.strip()]
        assert body_lines == [], f"Expected empty always_ff body, got: {body_lines}"

    def test_for_at_top_level_of_comb_dropped(self):
        src = (
            "module m () { "
            "logic [7:0] data; "
            "comb { "
            "for (i = 0; i < 4; i = i + 1) { data = i; } "
            "} }"
        )
        sv = compile_source(src)
        assert "always_comb" in sv["m"]
        lines = sv["m"].split("\n")
        begin_idx = next(i for i, l in enumerate(lines) if "begin" in l)
        end_idx = next(i for i, l in enumerate(lines) if "end" in l)
        body_lines = [l.strip() for l in lines[begin_idx + 1 : end_idx] if l.strip()]
        assert body_lines == []

    def test_for_inside_if_in_seq_dropped(self):
        """IfStmt is handled, but ForStmt nested inside the if's body is not.
        _convert_if calls _convert_block which doesn't handle ForStmt."""
        src = (
            "module m (clk, rst_n, en) { "
            "logic [7:0] data; "
            "seq (clk, neg: rst_n) { "
            "if (en) { for (i = 0; i < 4; i = i + 1) { data = i; } } "
            "} }"
        )
        sv = compile_source(src)
        # The if block appears but the for-loop body inside it is dropped
        assert "if (en) begin" in sv["m"]
        lines = sv["m"].split("\n")
        # Find the if-begin and its matching end
        in_if = False
        body_lines = []
        for line in lines:
            if "if (en) begin" in line:
                in_if = True
                continue
            if in_if and line.strip() == "end":
                break
            if in_if and line.strip():
                body_lines.append(line.strip())
        assert body_lines == [], f"Expected empty if body, got: {body_lines}"


# ── Gap 2: validation.py is dead code ──────────────────────────

class TestValidationDeadCode:
    """slang_integration.validation.validate_sv is exported but never called
    by any production code. emitter.py has its own inline validation."""

    def test_validate_sv_not_called_by_emitter(self):
        """emitter.py has its own pyslang validation inline, separate from
        validation.py. The validation module is exported but unused."""
        from slip.codegen import emitter
        import inspect
        source = inspect.getsource(emitter.emit)
        # emitter.emit does NOT import from validation
        assert "from slip.slang_integration.validation" not in source
        assert "from slip.slang_integration import" not in source

    def test_validate_sv_works(self):
        """validation.py's pyslang API actually works (getLineCol via sourceManager).
        The module is functional but nobody calls it."""
        from slip.slang_integration.validation import validate_sv
        result = validate_sv("module m (); endmodule")
        assert isinstance(result, list)
        assert len(result) == 0


# ── Gap 3: pratt.py unsigned vs signed inconsistency ───────────

class TestUnsignedSignedInconsistency:
    """In pratt.py, `signed` without a following tick raises SlipSyntaxError,
    but `unsigned` without a tick silently becomes an identifier.
    This is inconsistent behavior."""

    def test_signed_without_tick_raises(self):
        src = "module m (y) { assign y = signed(1); }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_unsigned_without_tick_accepted_by_parser(self):
        """Parser silently treats `unsigned` as a variable name when not
        followed by a tick. The error only surfaces later during pyslang
        validation in the emitter (if pyslang is available)."""
        src = "module m (y) { logic unsigned; assign y = unsigned; }"
        # Parser accepts it without error
        modules = parse_source(src)
        stmts = modules[0].body
        # 'unsigned' is parsed as a signal declaration
        assert any(
            hasattr(s, "name") and s.name == "unsigned" for s in stmts
        )


# ── Gap 4: parser silently accepts bare ident as signal decl ──

class TestBareIdentBecomesSignalDecl:
    """Parser's _parse_statement dispatches any IDENT that doesn't match
    instance or assignment patterns to _parse_signal_decl. A bare
    `foo;` becomes a signal declaration with no `logic` keyword."""

    def test_bare_ident_becomes_signal(self):
        src = "module m (y) { my_signal; assign y = 1; }"
        sv = compile_source(src)
        # my_signal is accepted as a signal declaration without `logic`
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
    """Parser silently accepts trailing commas in instance connection lists:
    child u1 { .a(x), .b(y), } — the trailing comma after .b(y) is consumed
    without error."""

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


# ── Gap 6: Lexer template identifier merging fails with multiple backtick vars

class TestTemplateIdentifierMerging:
    """_merge_template_idents only does a single left-to-right pass.
    Multiple backtick variables in one identifier (a`i_`j) are not merged
    into a single token, causing parse errors."""

    def test_single_template_var_works(self):
        """Single template variable: a`i → single IDENT token."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("a`i", "test.slip").tokenize()
        ident_tokens = [t for t in tokens if t.type == TokenType.IDENT]
        assert len(ident_tokens) == 1
        assert ident_tokens[0].value == "a`i"

    def test_template_with_static_suffix_works(self):
        """Template with static suffix: a`i_b → single IDENT token."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("a`i_b", "test.slip").tokenize()
        ident_tokens = [t for t in tokens if t.type == TokenType.IDENT]
        assert len(ident_tokens) == 1
        assert ident_tokens[0].value == "a`i_b"

    def test_two_template_vars_broken(self):
        """Two template variables: a`i_`j → split into two tokens (BUG)."""
        from slip.lexer import Lexer, TokenType
        tokens = [t for t in Lexer("a`i_`j", "test.slip").tokenize()
                  if t.type != TokenType.EOF]
        # BUG: should be a single IDENT `a`i_`j`, but is split
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "a`i_"
        assert tokens[1].type == TokenType.TICK_IDENT
        assert tokens[1].value == "`j"

    def test_two_template_vars_causes_parse_error(self):
        """Nested gen_for with two template variables in signal name fails."""
        src = (
            "module m () { "
            "logic a0_0; logic a0_1; logic a1_0; logic a1_1; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "`for (`j = 0; `j < 2; `j = `j + 1) { "
            "assign a`i_`j = `i + `j; "
            "} } }"
        )
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_workaround_separate_names(self):
        """Workaround: use separate signal names per iteration instead of
        compound template identifiers."""
        src = (
            "module m () { "
            "logic a0; logic a1; logic b0; logic b1; "
            "`for (`i = 0; `i < 2; `i = `i + 1) { "
            "assign a`i = `i; "
            "`for (`j = 0; `j < 2; `j = `j + 1) { "
            "assign b`j = `i + `j; "
            "} } }"
        )
        sv = compile_source(src)
        assert "a0" in sv["m"]
        assert "a1" in sv["m"]


# ── BUG-009/010: Lexer integer literal validation ──────────────

class TestLexerIntegerLiteralValidation:
    """The lexer regex for Verilog integer literals uses a single character
    class [0-9a-fA-F_xXzZ] for all radixes. This means binary literals
    accept hex digits, octal accepts 8-9, etc. Also, underscore-only
    digit sequences are accepted."""

    def test_binary_accepts_hex_digits(self):
        """4'bABCD should be rejected but is accepted as a valid binary literal."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("4'bABCD", "test.slip").tokenize()
        int_tokens = [t for t in tokens if t.type == TokenType.INT_LITERAL]
        assert len(int_tokens) == 1  # BUG: should be 0 (invalid binary)

    def test_octal_accepts_8_9(self):
        """4'o888 should be rejected but is accepted as a valid octal literal."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("4'o888", "test.slip").tokenize()
        int_tokens = [t for t in tokens if t.type == TokenType.INT_LITERAL]
        assert len(int_tokens) == 1  # BUG: should be 0

    def test_decimal_accepts_hex_digits(self):
        """4'dFF should be rejected but is accepted as a valid decimal literal."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("4'dFF", "test.slip").tokenize()
        int_tokens = [t for t in tokens if t.type == TokenType.INT_LITERAL]
        assert len(int_tokens) == 1  # BUG: should be 0

    def test_underscore_only_digits_accepted(self):
        """4'b_ should be rejected — no actual digit value — but is accepted."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("4'b_", "test.slip").tokenize()
        int_tokens = [t for t in tokens if t.type == TokenType.INT_LITERAL]
        assert len(int_tokens) == 1  # BUG: should be 0

    def test_multiple_underscores_only(self):
        """4'd___ should be rejected but is accepted."""
        from slip.lexer import Lexer, TokenType
        tokens = Lexer("4'd___", "test.slip").tokenize()
        int_tokens = [t for t in tokens if t.type == TokenType.INT_LITERAL]
        assert len(int_tokens) == 1  # BUG: should be 0


# ── BUG-011: Replication syntax broken ─────────────────────────

class TestReplicationSyntax:
    """The {n{expr}} replication syntax is not implemented in the Pratt parser.
    The ReplicationExpr AST node exists but is unreachable dead code."""

    def test_replication_causes_parse_error(self):
        """{4{1'b0}} should parse as a replication expression but fails."""
        src = "module m (y) { logic [7:0] y; assign y = {4{1'b0}}; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_replication_expr_node_exists(self):
        """ReplicationExpr is defined in the AST but never constructed by parser."""
        from slip.ast.expressions import ReplicationExpr
        # The class exists and can be constructed manually
        expr = ReplicationExpr(LOC, count=IntLiteralExpr(LOC, "4"),
                               inner=IntLiteralExpr(LOC, "0"))
        assert expr is not None


# ── BUG-012: Missing arithmetic shift operators ────────────────

class TestArithmeticShift:
    """<<< and >>> (arithmetic shift) are not supported. The lexer has no
    token type for them, and the Pratt parser has no binding power entry."""

    def test_arithmetic_right_shift_fails(self):
        """a >>> 1 should work but fails to lex/parse."""
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = a >>> 1; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_arithmetic_left_shift_fails(self):
        """a <<< 1 should work but fails to lex/parse."""
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = a <<< 1; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_logical_shift_works(self):
        """Logical shifts (<<, >>) do work."""
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = a >> 1; }"
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-013: Undefined signals silently become implicit 1-bit ──

class TestUndefinedSignalSilent:
    """When a signal name is referenced but never declared, the IR builder
    silently creates an implicit 1-bit signal instead of raising an error.
    Typos in signal names produce incorrect hardware with no warning."""

    def test_typo_creates_implicit_signal(self):
        """Typo 'data_ouut' silently creates a new 1-bit signal."""
        src = (
            "module m (data_out) { "
            "logic [7:0] data_out; "
            "assign data_out = data_ouut; "  # typo: should be data_out
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error, creates implicit 'data_ouut' signal
        assert "data_ouut" in sv["m"]
        assert "m" in sv

    def test_undeclared_signal_gets_implicit_declaration(self):
        """Any referenced but undeclared name becomes a 1-bit logic signal."""
        src = "module m (y) { assign y = undefined_signal; }"
        sv = compile_source(src)
        # BUG: 'undefined_signal' silently becomes a 1-bit signal
        assert "undefined_signal" in sv["m"]


# ── BUG-014: No multi-driver detection ─────────────────────────

class TestMultiDriver:
    """The driver analysis only tracks which signals are driven (flat set),
    not where they are driven from. Multiple drivers on the same signal
    pass silently."""

    def test_ff_and_comb_same_signal(self):
        """Signal driven in both always_ff and always_comb — no error."""
        src = (
            "module m (clk, a, b, out) { "
            "logic a; logic b; logic out; "
            "seq (clk) { out = a; } "
            "comb { out = b; } "
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error — should detect multi-driver
        assert "m" in sv

    def test_two_ff_blocks_same_signal(self):
        """Signal driven in two different always_ff blocks — no error."""
        src = (
            "module m (clk1, clk2, a, b, out) { "
            "logic a; logic b; logic out; "
            "seq (clk1) { out = a; } "
            "seq (clk2) { out = b; } "
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error
        assert "m" in sv


# ── BUG-015: No combinational loop detection ───────────────────

class TestCombLoop:
    """No graph analysis exists to detect combinational loops.
    Signals that read each other in always_comb produce nonsynthesizable
    hardware with no warning."""

    def test_simple_comb_loop(self):
        """a = b; b = a; in always_comb — no error."""
        src = (
            "module m (a, b) { "
            "logic a; logic b; "
            "comb { a = b; b = a; } "
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error — should detect combinational loop
        assert "m" in sv


# ── BUG-016: assign with nonblocking is illegal SV ─────────────

class TestAssignNonblocking:
    """The codegen emits 'assign foo <= bar;' for nonblocking continuous
    assignments, which is illegal SystemVerilog. The 'assign' keyword
    only permits blocking '='."""

    def test_assign_nonblocking_in_output(self):
        """Nonblocking assignment at module level produces illegal SV."""
        src = (
            "module m (clk, d, q) { "
            "logic [7:0] d; logic [7:0] q; "
            "seq (clk) { q = d; } "
            "}"
        )
        sv = compile_source(src)
        # The seq_correction converts blocking to nonblocking, and the
        # emitter puts it inside always_ff (correct).
        # But if someone creates a nonblocking assign at module level:
        assign = HDLAssignment("x", "y", is_nonblocking=True)
        result = assign.to_sv()
        # BUG: produces 'assign x <= y;' which is illegal SV
        assert "assign" in result
        assert "<=" in result

    def test_assign_stmt_fragment_nonblocking(self):
        """fragment.assign_stmt also produces illegal 'assign x <= y;'."""
        assign = HDLAssignment("x", "y", is_nonblocking=True)
        result = assign_stmt(assign)
        # BUG: produces 'assign x <= y;' which is illegal SV
        assert "assign" in result
        assert "<=" in result


# ── BUG-017: Missing required ports not checked ────────────────

class TestMissingRequiredPort:
    """Instance connections that omit required input ports pass silently
    when using explicit (non-regex) connections."""

    def test_missing_input_ports(self):
        """Instance with missing required input ports — no error."""
        src = (
            "module child (a, b, out) { "
            "logic a; logic b; logic out; assign out = a & b; "
            "} "
            "module parent (result) { "
            "logic result; "
            "child u1 { .out(result) }; "  # missing .a() and .b()
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error — should flag missing ports
        assert "child" in sv["parent"]


# ── BUG-018: Missing exponentiation operator ───────────────────

class TestMissingExponentiation:
    """** operator is not supported (no token type, no lexer rule, no
    Pratt parser entry)."""

    def test_exponentiation_fails(self):
        src = "module m (y) { logic [7:0] y; assign y = 2 ** 3; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)


# ── BUG-019: Missing four-state identity operators ─────────────

class TestMissingFourStateOps:
    """=== and !== (four-state/case equality) are not supported."""

    def test_case_equality_fails(self):
        src = "module m (a, b, y) { logic a; logic b; logic y; assign y = a === b; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_case_inequality_fails(self):
        src = "module m (a, b, y) { logic a; logic b; logic y; assign y = a !== b; }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)


# ── BUG-020: Missing width-cast syntax ─────────────────────────

class TestMissingWidthCast:
    """8'(expr) and WIDTH'(expr) width-cast syntax is not supported.
    Only signed'(expr) and unsigned'(expr) work."""

    def test_width_cast_fails(self):
        src = "module m (a, y) { logic [7:0] a; logic [3:0] y; assign y = 4'(a); }"
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_signed_cast_works(self):
        src = "module m (a, y) { logic [7:0] a; logic [7:0] y; assign y = signed'(a); }"
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-021: For-loop step limited to simple assignment ────────

class TestForStepLimited:
    """For-loop step only supports 'IDENT = expr'. No i++, i--, i += 1."""

    def test_increment_fails(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i++) { assign y = i; } "
            "}"
        )
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_compound_assignment_fails(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i += 1) { assign y = i; } "
            "}"
        )
        with pytest.raises(SlipSyntaxError):
            compile_source(src)

    def test_simple_step_works(self):
        src = (
            "module m (y) { "
            "logic [7:0] y; "
            "for (i = 0; i < 8; i = i + 1) { assign y = i; } "
            "}"
        )
        sv = compile_source(src)
        assert "m" in sv


# ── BUG-024: No duplicate declaration detection ────────────────

class TestDuplicateDeclaration:
    """Declaring the same signal name twice passes silently — the set
    deduplicates without warning."""

    def test_duplicate_logic_decl(self):
        """Two 'logic x;' declarations — pyslang catches this, but slip's
        own semantic analysis doesn't detect it."""
        src = (
            "module m (y) { "
            "logic x; logic x; "
            "assign y = x; "
            "}"
        )
        # BUG: slip's semantic layer doesn't detect duplicates.
        # pyslang catches it at codegen time, but that's too late for
        # good error messages. Document that pyslang saves us here.
        with pytest.raises(SlipCodegenError, match="redefinition"):
            compile_source(src)

    def test_signal_collides_with_port(self):
        """Declaring a signal with the same name as a port — no error."""
        src = (
            "module m (data) { "
            "logic [7:0] data; "
            "assign data = 8'hFF; "
            "}"
        )
        sv = compile_source(src)
        # BUG: port and signal name collision not detected
        assert "m" in sv


# ── BUG-026: Instance module existence not checked ──────────────

class TestInstanceModuleExistence:
    """Non-regex instances don't validate that the target module exists.
    A typo in the module name only fails at codegen, not semantic analysis."""

    def test_typo_in_module_name(self):
        """Typo in instance module name — no error in semantic phase."""
        src = (
            "module child (a) { logic a; } "
            "module parent (x) { "
            "logic x; "
            "child_typo u1 { .a(x) }; "  # typo: should be 'child'
            "}"
        )
        sv = compile_source(src)
        # BUG: compiles without error — module existence not checked
        assert "child_typo" in sv["parent"] or "parent" in sv


# ── BUG-029: always_latch emitted with sensitivity list ─────────

class TestAlwaysLatch:
    """always_latch should not have an explicit sensitivity list per IEEE 1800.
    The codegen emits 'always_latch @(sensitivity) begin' which is incorrect."""

    def test_always_latch_with_sensitivity(self):
        """LogicBlock with kind='always_latch' emits spurious sensitivity list."""
        block = LogicBlock("*", ((HDLAssignment("q", "d", False),),), "always_latch")
        text = logic_block(block)
        # BUG: should be 'always_latch begin' not 'always_latch @(*) begin'
        assert "always_latch" in text
        assert "@(*)" in text  # BUG: this should not be present

    def test_always_comb_no_sensitivity(self):
        """always_comb correctly omits sensitivity list."""
        block = LogicBlock("", ((HDLAssignment("y", "a", False),),), "always_comb")
        text = logic_block(block)
        assert "always_comb begin" in text
        assert "@(" not in text


# ── BUG-030: UndeclaredIdentifier suppression too broad ────────

class TestDiagnosticSuppression:
    """The emitter suppresses UndeclaredIdentifier diagnostics, which means
    real typos in signal names within expressions are hidden."""

    def test_suppressed_codes_include_undeclared(self):
        """UndeclaredIdentifier is in the suppression list."""
        from slip.codegen.emitter import _SUPPRESSED_DIAG_CODES
        assert "UndeclaredIdentifier" in _SUPPRESSED_DIAG_CODES

    def test_suppressed_codes_include_could_not_resolve(self):
        """CouldNotResolve is in the suppression list — could mask real errors."""
        from slip.codegen.emitter import _SUPPRESSED_DIAG_CODES
        assert "CouldNotResolve" in _SUPPRESSED_DIAG_CODES


# ── BUG-032: HDLAssignment.to_sv() always prepends assign ──────

class TestHDLAssignmentToSV:
    """HDLAssignment.to_sv() always prepends 'assign', making it wrong
    for use inside procedural blocks where 'assign' should not appear."""

    def test_to_sv_always_has_assign(self):
        """Even with is_nonblocking=True, to_sv() prepends 'assign'."""
        a = HDLAssignment("q", "d", is_nonblocking=True)
        result = a.to_sv()
        # BUG: 'assign q <= d;' — should be 'q <= d;' inside procedural block
        assert result.startswith("assign")

    def test_to_sv_blocking_has_assign(self):
        a = HDLAssignment("x", "y", is_nonblocking=False)
        result = a.to_sv()
        assert result == "assign x = y;"


# ── BUG-033: Missing Optional type annotation ──────────────────

class TestIRTypeAnnotations:
    """IR dataclasses have type_ fields annotated as HDLType but defaulting
    to None, which violates the type annotation."""

    def test_signal_type_defaults_none(self):
        from slip.ir.signal import HDLSignal
        s = HDLSignal("x")
        # type_ is annotated as HDLType but is None
        assert s.type_ is None

    def test_port_type_defaults_none(self):
        from slip.ir.port import HDLPort
        p = HDLPort("a", "input")
        assert p.type_ is None


# ── BUG-034: Unconstrained string fields in IR ─────────────────

class TestIRUnconstrainedStrings:
    """LogicBlock.kind and HDLPort.direction accept any string with no validation."""

    def test_logic_block_accepts_invalid_kind(self):
        """Any string is accepted as kind — no validation."""
        block = LogicBlock("*", ((HDLAssignment("x", "y", False),),), "always_wrong")
        assert block.kind == "always_wrong"

    def test_port_accepts_invalid_direction(self):
        from slip.ir.port import HDLPort
        p = HDLPort("x", "banana")
        assert p.direction == "banana"


# ── BUG-035: HDLInstance.regex_rules never consumed ────────────

class TestInstanceRegexRules:
    """HDLInstance.regex_rules field exists in the IR but is never referenced
    by the emitter or fragment code."""

    def test_regex_rules_field_exists(self):
        from slip.ir.instance import HDLInstance
        inst = HDLInstance(inst_name="u1", target="child",
                           param_map=(), port_map=(),
                           regex_rules=(("pattern", "replacement"),))
        assert inst.regex_rules == (("pattern", "replacement"),)

    def test_regex_rules_not_in_fragment_output(self):
        """The instance() fragment function does not use regex_rules."""
        from slip.ir.instance import HDLInstance
        from slip.codegen.fragment import instance as frag_instance
        inst = HDLInstance(inst_name="u1", target="child",
                           param_map=(), port_map=(("a", "x"),),
                           regex_rules=(("pattern", "replacement"),))
        text = frag_instance(inst)
        # regex_rules are not reflected in the output
        assert "pattern" not in text
        assert "replacement" not in text
