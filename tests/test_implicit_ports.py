"""Tests for implicit port inference - verifying the bug fix in ir_builder.py"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, '/home/badppg/slip_proj/slip/tests')
from conftest import compile_source

class TestImplicitPortInference:
    """Test that implicit ports are correctly inferred when port list is omitted."""
    
    def test_simple_implicit_ports(self):
        """Basic implicit port inference - used but undeclared signals become ports."""
        sv = compile_source('''
module passthrough {
    assign out = in;
}
''')
        text = sv['passthrough']
        # Both 'in' and 'out' should be inferred as ports
        assert 'input logic in' in text
        assert 'output logic out' in text
        # Should not have standalone logic declarations (they're ports now)
        # Check that there's no "logic in;" or "logic out;" line
        lines = text.split('\n')
        for line in lines:
            stripped = line.strip()
            assert stripped != 'logic in;'
            assert stripped != 'logic out;'
    
    def test_implicit_ports_with_direction_inference(self):
        """Port directions should be inferred from usage context."""
        sv = compile_source('''
module adder {
    assign sum = a + b;
}
''')
        text = sv['adder']
        # a and b are inputs (read only), sum is output (driven)
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic sum' in text
    
    def test_implicit_ports_in_seq_block(self):
        """Signals used in seq blocks should be inferred correctly."""
        sv = compile_source('''
module my_reg {
    seq (clk) {
        q <= d;
    }
}
''')
        text = sv['my_reg']
        # clk is input (used in sensitivity), d is input, q is output
        assert 'input logic clk' in text
        assert 'input logic d' in text
        assert 'output logic q' in text
    
    def test_implicit_ports_in_comb_block(self):
        """Signals used in comb blocks should be inferred correctly."""
        sv = compile_source('''
module mux {
    comb {
        if (sel) {
            y = a;
        } else {
            y = b;
        }
    }
}
''')
        text = sv['mux']
        # sel, a, b are inputs, y is output
        assert 'input logic sel' in text
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
    
    def test_implicit_ports_mixed_usage(self):
        """Signals used in multiple contexts should be inferred correctly."""
        sv = compile_source('''
module counter {
    seq (clk, pos: rst) {
        if (rst) {
            count = 0;
        } else {
            count = count + 1;
        }
    }
}
''')
        text = sv['counter']
        # clk and rst are inputs, count is output
        assert 'input logic clk' in text
        assert 'input logic rst' in text
        assert 'output logic count' in text
    
    def test_implicit_ports_with_width(self):
        """Implicit ports should have correct width inference."""
        sv = compile_source('''
module adder8 {
    assign sum = a + b;
}
''')
        text = sv['adder8']
        # Without explicit width, should be 1-bit
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic sum' in text
    
    def test_implicit_ports_with_explicit_signal_decl(self):
        """Explicitly declared signals should not become ports."""
        sv = compile_source('''
module example {
    logic [7:0] temp;
    assign temp = a + b;
    assign y = temp;
}
''')
        text = sv['example']
        # temp is declared, so it's a signal not a port
        assert 'logic [7:0] temp' in text
        # a, b, y are implicit ports
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
    
    def test_implicit_ports_no_ports_when_all_declared(self):
        """When all signals are declared, there should be no implicit ports."""
        sv = compile_source('''
module all_declared {
    logic a;
    logic b;
    logic y;
    assign y = a & b;
}
''')
        text = sv['all_declared']
        # All signals are declared, so no implicit ports
        assert 'logic a' in text
        assert 'logic b' in text
        assert 'logic y' in text
        # Module should have empty port list
        assert 'module all_declared;' in text
    
    def test_implicit_ports_with_instance_same_name_shorthand(self):
        """Implicit ports should work with module instantiation using same-name shorthand."""
        sv = compile_source('''
module inner (a, b, y) {
    logic a;
    logic b;
    logic y;
    assign y = a & b;
}

module top {
    inner u1 { .a, .b, .y };
}
''')
        text = sv['top']
        # When instance uses same-name shorthand, signals should be inferred as ports
        # Check that the instance is present
        assert 'inner u1' in text
        # Check that a, b, y are inferred as ports (not declared as logic)
        # Note: direction inference depends on driver analysis of current module only
        # Since a, b, y are only used in instance connections (readers), they're inputs
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'input logic y' in text
    
    def test_implicit_ports_empty_module(self):
        """Module with no body should have no ports."""
        sv = compile_source('''
module empty {
}
''')
        text = sv['empty']
        # Should have no ports
        assert 'module empty;' in text
    
    def test_implicit_ports_only_assigns(self):
        """Module with only assigns should infer ports correctly."""
        sv = compile_source('''
module assigns_only {
    assign y = a & b;
    assign z = a | b;
}
''')
        text = sv['assigns_only']
        # a, b are inputs, y, z are outputs
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
        assert 'output logic z' in text
    
    def test_implicit_ports_direction_from_seq_sensitivity(self):
        """Clock and reset in sensitivity list should be inputs."""
        sv = compile_source('''
module seq_module {
    seq (clk, neg: rst_n) {
        if (!rst_n) {
            q <= 0;
        } else {
            q <= d;
        }
    }
}
''')
        text = sv['seq_module']
        # clk and rst_n are inputs (from sensitivity list)
        assert 'input logic clk' in text
        assert 'input logic rst_n' in text
        # d is input, q is output
        assert 'input logic d' in text
        assert 'output logic q' in text
    
    def test_implicit_ports_complex_expression(self):
        """Complex expressions should still infer ports correctly."""
        sv = compile_source('''
module complex {
    assign y = (a & b) | (c ^ d);
}
''')
        text = sv['complex']
        # a, b, c, d are inputs, y is output
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'input logic c' in text
        assert 'input logic d' in text
        assert 'output logic y' in text
    
    def test_implicit_ports_with_ternary(self):
        """Ternary operator should infer ports correctly."""
        sv = compile_source('''
module ternary_mux {
    assign y = sel ? a : b;
}
''')
        text = sv['ternary_mux']
        # sel, a, b are inputs, y is output
        assert 'input logic sel' in text
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
    
    def test_implicit_ports_multiple_comb_blocks(self):
        """Multiple comb blocks should infer ports correctly."""
        sv = compile_source('''
module multi_comb {
    comb {
        y1 = a & b;
    }
    comb {
        y2 = a | b;
    }
}
''')
        text = sv['multi_comb']
        # a, b are inputs, y1, y2 are outputs
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y1' in text
        assert 'output logic y2' in text
    
    def test_implicit_ports_with_if_else(self):
        """If/else in comb block should infer ports correctly."""
        sv = compile_source('''
module if_else {
    comb {
        if (sel) {
            y = a;
        } else {
            y = b;
        }
    }
}
''')
        text = sv['if_else']
        # sel, a, b are inputs, y is output
        assert 'input logic sel' in text
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
    
    def test_implicit_ports_with_explicit_ports_module(self):
        """Modules with explicit ports should not use implicit port inference."""
        sv = compile_source('''
module explicit (a, b, y) {
    logic a;
    logic b;
    logic y;
    assign y = a & b;
}
''')
        text = sv['explicit']
        # Should have explicit ports
        assert 'input logic a' in text
        assert 'input logic b' in text
        assert 'output logic y' in text
        # Should have module header with ports
        assert 'module explicit (' in text

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
