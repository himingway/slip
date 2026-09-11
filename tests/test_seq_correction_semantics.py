"""Semantics of the blocking-to-nonblocking conversion in seq blocks.

Every blocking assignment in a seq block becomes nonblocking (documented
behaviour).  This file pins down which programs the conversion changes
meaning for, and that only those emit a warning:

* idioms the conversion exists to support (shift registers, state
  machines, gated counters) must convert silently and produce
  nonblocking SV;
* idioms whose dataflow depends on blocking evaluation (loop
  accumulators, reset-then-reuse) must convert *and* warn, because the
  nonblocking result silently differs.
"""

import warnings

import pytest

from conftest import compile_source

SEQ_WARNING_MARKER = "after conversion to non-blocking"


def _compile_with_warnings(src):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        sv = compile_source(src)
    seq_warns = [x for x in w if SEQ_WARNING_MARKER in str(x.message)]
    return sv, seq_warns


class TestConvertedSilently:
    """Programs where blocking and nonblocking agree — no warning."""

    @pytest.mark.parametrize("name,src", [
        ("plain increment",
         "module m (clk) { logic [7:0] q; seq (clk) { q = q + 1; } }"),
        ("increment with reset branch",
         "module m (clk, rst_n) { logic [7:0] q; "
         "seq (clk, neg: rst_n) { if (!rst_n) { q = 0; } else { q = q + 1; } } }"),
        ("gated counter",
         "module m (clk, en) { logic [7:0] c; seq (clk) { if (en) { c = c + 1; } } }"),
        ("state machine mux",
         "module m (clk, en) { logic [1:0] st; "
         "seq (clk) { if (st == 0) { if (en) { st = 1; } } "
         "else { if (st == 1) { st = 2; } else { st = 0; } } } }"),
        ("shift register over an array",
         "module m (clk, d) { logic [7:0] d; logic [7:0] st [0:2]; "
         "seq (clk) { st[0] = d; st[1] = st[0]; st[2] = st[1]; } }"),
        ("priority rotation",
         "module m (clk, rst_n) { logic [3:0] p; "
         "seq (clk, neg: rst_n) { if (!rst_n) { p = 1; } "
         "else { p = {p[2:0], p[3]}; } } }"),
        ("temporary then use",
         "module m (clk, a) { logic [7:0] a; logic [7:0] t; logic [7:0] o; "
         "seq (clk) { t = a + 1; o = t; } }"),
    ])
    def test_no_warning_and_nonblocking(self, name, src):
        sv, warns = _compile_with_warnings(src)
        assert warns == [], f"{name}: unexpected warning {warns}"
        # conversion still happened
        assert "<=" in sv["m"]
        assert " = " not in sv["m"].split("always_ff", 1)[1] if "always_ff" in sv["m"] else True


class TestConvertedWithWarning:
    """Programs whose meaning changes under nonblocking — must warn."""

    @pytest.mark.parametrize("name,src", [
        ("accumulator loop with result read",
         "module m (clk, b) { logic [7:0] b; logic [7:0] s; logic [7:0] r; "
         "seq (clk) { s = 0; for (k = 0; k < 4; k = k + 1) { s = s + b; } r = s; } }"),
        ("loop self-accumulate without init",
         "module m (clk, b) { logic [7:0] b; logic [7:0] s; "
         "seq (clk) { for (k = 0; k < 4; k = k + 1) { s = s + b; } } }"),
        ("reset then reuse",
         "module m (clk, b) { logic [7:0] b; logic [7:0] y; "
         "seq (clk) { y = 0; y = y + b; } }"),
    ])
    def test_warning_emitted(self, name, src):
        _, warns = _compile_with_warnings(src)
        assert warns, f"{name}: expected a conversion warning"
        assert "seq block" in str(warns[0].message)

    def test_warning_names_the_signal(self):
        _, warns = _compile_with_warnings(
            "module m (clk, b) { logic [7:0] b; logic [7:0] s; "
            "seq (clk) { s = 0; s = s + b; } }"
        )
        assert "'s'" in str(warns[0].message)

    def test_accumulator_still_compiles(self):
        """The warning is a diagnostic, not an error — code still emits."""
        sv, warns = _compile_with_warnings(
            "module m (clk, b) { logic [7:0] b; logic [7:0] s; "
            "seq (clk) { s = 0; for (k = 0; k < 4; k = k + 1) { s = s + b; } } }"
        )
        assert "always_ff" in sv["m"]
        assert "s <= s + b" in sv["m"]


class TestElementAwareSelfReference:
    """Index-aware detection: disjoint storage is not a self-reference.

    Note that a read of storage never written earlier in the block sees
    the pre-clock value under *both* semantics, so no warning is due
    regardless of indices; the index comparison matters once a prior
    write on the same path exists.
    """

    def test_disjoint_part_select_no_warning(self):
        _, warns = _compile_with_warnings(
            "module m (clk) { logic [7:0] x; "
            "seq (clk) { x = 0; x[3:0] = x[7:4]; } }"
        )
        # x[3:0] written, x[7:4] read — disjoint storage
        assert warns == []

    def test_overlapping_part_select_warns(self):
        _, warns = _compile_with_warnings(
            "module m (clk) { logic [7:0] x; "
            "seq (clk) { x = 0; x[3:0] = x[2:0]; } }"
        )
        assert warns, "overlapping part-selects after a prior write"

    def test_bit_to_disjoint_bit_is_a_transfer(self):
        """Moving a bit between disjoint positions is a register transfer.

        The statement's target does not overlap what it reads, so the
        standard nonblocking reading (sample the pre-clock value) is the
        right one — same category as ``stage[1] = stage[0]``.
        """
        _, warns = _compile_with_warnings(
            "module m (clk) { logic [7:0] x; "
            "seq (clk) { x = 0; x[3] = x[0]; } }"
        )
        assert warns == []

    def test_first_write_self_read_is_silent(self):
        """x[3:0] = x[2:0] with no prior write: identical under both."""
        _, warns = _compile_with_warnings(
            "module m (clk) { logic [7:0] x; "
            "seq (clk) { x[3:0] = x[2:0]; } }"
        )
        assert warns == []

    def test_non_constant_index_warns_conservatively(self):
        _, warns = _compile_with_warnings(
            "module m (clk, k) { logic [7:0] x; logic [1:0] k; "
            "seq (clk) { x = 0; x[k] = x[k]; } }"
        )
        assert warns

    def test_array_element_shift_no_warning(self):
        sv, warns = _compile_with_warnings(
            "module m (clk, d) { logic [7:0] d; logic [7:0] st [0:3]; "
            "seq (clk) { st[3] = st[2]; st[2] = st[1]; st[1] = st[0]; st[0] = d; } }"
        )
        assert warns == []
        assert "st[3] <= st[2];" in sv["m"]


class TestExpressionShapes:
    """RHS expression types are all walked when detecting self-reads."""

    @pytest.mark.parametrize("rhs", [
        "~x",                    # unary
        "x ? 1'b1 : 1'b0",       # ternary
        "{x, 1'b0}",             # concatenation
        "{2{x}}",                # replication
        "8'h00 + x",             # binary
        "(x)",                   # paren
    ])
    def test_self_read_detected_through_expression(self, rhs):
        _, warns = _compile_with_warnings(
            f"module m (clk) {{ logic [7:0] x; "
            f"seq (clk) {{ x = 0; x = {rhs}; }} }}"
        )
        assert warns, f"self-read through {rhs} not detected"

    def test_case_arm_assignments_scanned(self):
        _, warns = _compile_with_warnings(
            "module m (clk, s, b) { logic [1:0] s; logic [7:0] b; logic [7:0] y; "
            "seq (clk) { y = 0; "
            "case (s) { 2'b00: y = 1; 2'b01: y = y + b; default: y = b; } } }"
        )
        assert warns, "self-referential assignment inside a case arm"

    def test_case_arms_are_exclusive(self):
        """A read in one arm cannot observe another arm's write."""
        _, warns = _compile_with_warnings(
            "module m (clk, s, b) { logic [1:0] s; logic [7:0] b; logic [7:0] y; "
            "seq (clk) { case (s) { 2'b00: y = 1; 2'b01: y = y + b; default: y = b; } } }"
        )
        assert warns == []

    def test_if_else_after_prior_write_warns(self):
        _, warns = _compile_with_warnings(
            "module m (clk, en, b) { logic [7:0] b; logic [7:0] y; "
            "seq (clk) { y = 0; if (en) { y = y + b; } else { y = b; } } }"
        )
        assert warns

    def test_if_else_arms_are_exclusive(self):
        """No prior write, arms exclusive — the reads see the pre-block value."""
        _, warns = _compile_with_warnings(
            "module m (clk, en, b) { logic [7:0] b; logic [7:0] y; "
            "seq (clk) { if (en) { y = 0; } else { y = y + b; } } }"
        )
        assert warns == []
