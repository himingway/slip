"""Tests for FEAT-009 / BUG-025: width mismatch warnings."""

import warnings

from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer


def _compile(source: str, ip_dirs=None):
    tokens = Lexer(source, "test.slip").tokenize()
    modules = Parser(tokens, "test.slip").parse()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ir = SemanticAnalyzer().analyze(modules, ip_dirs or [])
        return ir, w


class TestAssignmentWidthMismatch:
    def test_width_mismatch_literal(self):
        """8-bit signal assigned an unsized literal that overflows warns."""
        _, w = _compile("""
            module m (out[7:0]) {
                assign out = 300;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("300" in m and "does not fit" in m and "8 bits" in m for m in msgs)

    def test_fitting_unsized_literal_no_warning(self):
        """Unsized literal that fits the target does not warn (y = 0 idiom)."""
        _, w = _compile("""
            module m (out[7:0]) {
                assign out = 42;
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("width mismatch" in m or "does not fit" in m for m in msgs)

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
                assign out = 300;
            }
        """)
        msgs = [str(x.message) for x in w]
        # W has default=8, so W-1:0 = 7:0 = 8 bits; 300 does not fit → warns
        assert any("does not fit" in m and "8 bits" in m for m in msgs)

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

    def test_external_module_resolved_from_ip_dir(self, tmp_path):
        """External modules resolved via -ip get width checks (no warning here)."""
        (tmp_path / "ext.sv").write_text(
            "module ext (input logic [7:0] data);\nendmodule\n"
        )
        _, w = _compile("""
            module top (out[7:0]) {
                ext u { .data(out) };
            }
        """, ip_dirs=[tmp_path])
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
        """Overflowing width mismatch inside comb block."""
        _, w = _compile("""
            module m (out[7:0]) {
                comb {
                    out = 300;
                }
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("does not fit" in m and "8 bits" in m for m in msgs)

    def test_seq_block_assignment(self):
        """Overflowing width mismatch inside seq block."""
        _, w = _compile("""
            module m (out[7:0], clk) {
                seq (clk) {
                    out <= 300;
                }
            }
        """)
        msgs = [str(x.message) for x in w]
        assert any("does not fit" in m and "8 bits" in m for m in msgs)


class TestArrayElementConnections:
    """Array elements connected to instance ports are full-width, not 1 bit."""

    def test_array_element_to_instance_port_no_warning(self):
        _, w = _compile("""
            module sub (data[7:0]) {
                assign data = 8'h00;
            }
            module top (din) {
                logic [7:0] din;
                logic [7:0] st [0:1];
                assign st[0] = din;
                sub u { .data(st[1]) };
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("port width mismatch" in m for m in msgs), msgs

    def test_array_element_assignment_same_width_no_warning(self):
        _, w = _compile("""
            module m (din, dout) {
                logic [7:0] din;
                logic [7:0] dout;
                logic [7:0] st [0:2];
                assign st[0] = din;
                `for (`i = 1; `i < 3; `i = `i + 1) {
                    assign st[`i] = st[`i - 1];
                }
                assign dout = st[2];
            }
        """)
        msgs = [str(x.message) for x in w]
        assert not any("width mismatch" in m for m in msgs), msgs
