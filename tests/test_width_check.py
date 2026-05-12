"""Tests for FEAT-009 / BUG-025: width mismatch warnings."""

import warnings

from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer


def _compile(source: str):
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ir = SemanticAnalyzer().analyze(modules)
        return ir, w


class TestAssignmentWidthMismatch:
    def test_width_mismatch_literal(self):
        """8-bit signal assigned unsized 32-bit literal warns."""
        _, w = _compile("""
            module m (out[7:0]) {
                assign out = 42;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("width mismatch" in m and "8 bits" in m and "32 bits" in m for m in msgs)

    def test_width_match_sized_literal(self):
        """8-bit signal assigned 8-bit sized literal — no warning."""
        _, w = _compile("""
            module m (out[7:0]) {
                assign out = 8'hFF;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("width mismatch" in m for m in msgs)

    def test_width_match_same_width(self):
        """Two signals of same width — no warning."""
        _, w = _compile("""
            module m (out[7:0], in[7:0]) {
                assign out = in;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("width mismatch" in m for m in msgs)

    def test_width_mismatch_signal_to_signal(self):
        """8-bit signal assigned to 4-bit signal warns."""
        _, w = _compile("""
            module m (out[3:0], in[7:0]) {
                assign out = in;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("width mismatch" in m and "4 bits" in m and "8 bits" in m for m in msgs)

    def test_parameterized_width_with_default_evaluated(self):
        """Parameterized width with default value IS evaluated."""
        _, w = _compile("""
            module m #(param W = 8) (out[W-1:0]) {
                assign out = 42;
            }
        """)
        msgs = [str(x.message) for x in w]
        # W has default=8, so W-1:0 = 7:0 = 8 bits, literal 42 = 32 bits → warns
        assert any("width mismatch" in m and "8 bits" in m and "32 bits" in m for m in msgs)

    def test_no_width_declared_skipped(self):
        """Signals without width declarations are skipped."""
        _, w = _compile("""
            module m (out) {
                assign out = 42;
            }
        """)
        msgs = [str(x.message) for x in w]
        # out has no explicit width, so target_width is None → skipped
        assert not any("width mismatch" in m for m in msgs)


class TestInstanceWidthMismatch:
    def test_port_width_mismatch(self):
        """Instance port expects 8 bits but connected signal is 4 bits."""
        _, w = _compile("""
            module sub (data[7:0]) {
                assign data = 8'h00;
            }
            module top (out[3:0]) {
                sub u { .data(out) };
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("port width mismatch" in m and "8 bits" in m and "4 bits" in m for m in msgs)

    def test_port_width_match(self):
        """Instance port and signal same width — no warning."""
        _, w = _compile("""
            module sub (data[7:0]) {
                assign data = 8'h00;
            }
            module top (out[7:0]) {
                sub u { .data(out) };
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("port width mismatch" in m for m in msgs)

    def test_external_module_skipped(self):
        """External (undefined) modules are skipped."""
        _, w = _compile("""
            module top (out[7:0]) {
                ext u { .data(out) };
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("port width mismatch" in m for m in msgs)


class TestBitSelectWidth:
    def test_single_bit_select(self):
        """Single bit select is 1 bit wide."""
        _, w = _compile("""
            module m (out, in[7:0]) {
                assign out = in[3];
            }
        """)
        msgs = [str(x.message) for x in w]
        # out is 1-bit, in[3] is 1-bit — no mismatch
        assert not any("width mismatch" in m for m in msgs)


class TestProceduralWidthMismatch:
    def test_comb_block_assignment(self):
        """Width mismatch inside comb block."""
        _, w = _compile("""
            module m (out[7:0]) {
                comb {
                    out = 42;
                }
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("width mismatch" in m and "8 bits" in m and "32 bits" in m for m in msgs)

    def test_seq_block_assignment(self):
        """Width mismatch inside seq block."""
        _, w = _compile("""
            module m (out[7:0], clk) {
                seq (clk) {
                    out <= 42;
                }
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("width mismatch" in m and "8 bits" in m and "32 bits" in m for m in msgs)
