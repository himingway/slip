"""Tests for defun — user-defined regex port mapping functions."""

import pytest
from pathlib import Path

from slip.lexer import Lexer
from slip.parser import Parser
from slip.parser.parser import CompilationUnit
from slip.ast.statements import FuncDef, ReturnStmt
from slip.ast.expressions import MethodCallExpr, BinaryExpr, IdentExpr, StringLiteralExpr
from slip.semantic.defun_eval import register_funcdef
from slip.semantic.regex_funcs import REGISTRY, clear_custom
from slip.errors.semantic import SlipSemanticError
from conftest import compile_source, parse_unit


# ────────────────────────────────────────────────────────────────
# Parser tests
# ────────────────────────────────────────────────────────────────


class TestFuncDefParsing:
    """Test parsing of defun statements."""

    def test_simple_defun(self):
        """Parse a simple defun with one parameter."""
        unit = parse_unit('''
defun my_func(s):
    return "prefix_" + s

module top (clk) {
    logic clk;
}
''')
        assert len(unit.funcdefs) == 1
        fd = unit.funcdefs[0]
        assert fd.name == "my_func"
        assert fd.params == ("s",)
        assert len(fd.body) == 1
        assert isinstance(fd.body[0], ReturnStmt)

    def test_defun_multiple_params(self):
        """Parse defun with multiple parameters."""
        unit = parse_unit('''
defun combine(a, b):
    return a + "_" + b

module top (clk) {
    logic clk;
}
''')
        fd = unit.funcdefs[0]
        assert fd.params == ("a", "b")

    def test_defun_with_method_call(self):
        """Parse defun with method call expression."""
        unit = parse_unit('''
defun upper(s):
    return s.upper()

module top (clk) {
    logic clk;
}
''')
        fd = unit.funcdefs[0]
        ret = fd.body[0]
        assert isinstance(ret, ReturnStmt)
        assert isinstance(ret.value, MethodCallExpr)
        assert ret.value.method == "upper"

    def test_defun_before_module(self):
        """defun defined before module."""
        unit = parse_unit('''
defun my_func(s):
    return s

module top (clk) {
    logic clk;
}
''')
        assert len(unit.funcdefs) == 1
        assert len(unit.modules) == 1

    def test_defun_after_module(self):
        """defun defined after module (still processed first)."""
        unit = parse_unit('''
module top (clk) {
    logic clk;
}

defun my_func(s):
    return s
''')
        assert len(unit.funcdefs) == 1
        assert len(unit.modules) == 1

    def test_multiple_defuns(self):
        """Multiple defun definitions."""
        unit = parse_unit('''
defun func_a(s):
    return s.upper()

defun func_b(s):
    return s.lower()

module top (clk) {
    logic clk;
}
''')
        assert len(unit.funcdefs) == 2
        assert unit.funcdefs[0].name == "func_a"
        assert unit.funcdefs[1].name == "func_b"


# ────────────────────────────────────────────────────────────────
# Evaluator unit tests
# ────────────────────────────────────────────────────────────────


class TestDefunEvaluator:
    """Test compile-time evaluation of defun bodies."""

    def setup_method(self):
        clear_custom()

    def teardown_method(self):
        clear_custom()

    def test_string_concatenation(self):
        """String + String = concatenation."""
        unit = parse_unit('''
defun prefix(s):
    return "bus_" + s

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["prefix"]
        assert func("data") == "bus_data"

    def test_method_upper(self):
        """Method .upper() on string."""
        unit = parse_unit('''
defun to_upper(s):
    return s.upper()

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["to_upper"]
        assert func("hello") == "HELLO"

    def test_method_lower(self):
        """Method .lower() on string."""
        unit = parse_unit('''
defun to_lower(s):
    return s.lower()

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["to_lower"]
        assert func("HELLO") == "hello"

    def test_method_reverse(self):
        """Method .reverse() on string."""
        unit = parse_unit('''
defun rev(s):
    return s.reverse()

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["rev"]
        assert func("abc") == "cba"

    def test_method_chaining(self):
        """Chain method calls: s.upper().reverse()."""
        unit = parse_unit('''
defun chain(s):
    return s.upper().reverse()

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["chain"]
        assert func("abc") == "CBA"

    def test_arithmetic_add(self):
        """Integer arithmetic: a + b."""
        unit = parse_unit('''
defun inc(n):
    return n + 1

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["inc"]
        assert func("3") == "4"

    def test_arithmetic_sub(self):
        """Integer subtraction."""
        unit = parse_unit('''
defun dec(n):
    return n - 1

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["dec"]
        assert func("5") == "4"

    def test_arithmetic_mul(self):
        """Integer multiplication."""
        unit = parse_unit('''
defun double(n):
    return n * 2

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["double"]
        assert func("3") == "6"

    def test_arithmetic_div(self):
        """Integer division."""
        unit = parse_unit('''
defun half(n):
    return n / 2

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["half"]
        assert func("7") == "3"

    def test_arithmetic_mod(self):
        """Integer modulo."""
        unit = parse_unit('''
defun mod2(n):
    return n % 2

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["mod2"]
        assert func("7") == "1"

    def test_mixed_string_arithmetic(self):
        """String concatenation with arithmetic result."""
        unit = parse_unit('''
defun bus_inc(n):
    return "bus_" + (n + 1)

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["bus_inc"]
        assert func("3") == "bus_4"

    def test_multiple_params(self):
        """Function with multiple parameters."""
        unit = parse_unit('''
defun join(a, b):
    return a + "_" + b

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["join"]
        assert func("data", "in") == "data_in"

    def test_wrong_arg_count(self):
        """Calling with wrong number of arguments raises ValueError."""
        unit = parse_unit('''
defun my_func(s):
    return s

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["my_func"]
        with pytest.raises(ValueError, match="takes 1 arguments, got 2"):
            func("a", "b")

    def test_division_by_zero(self):
        """Division by zero raises SlipSemanticError."""
        unit = parse_unit('''
defun div_zero(n):
    return n / 0

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["div_zero"]
        with pytest.raises(SlipSemanticError, match="integer division or modulo by zero"):
            func("5")

    def test_replace_method(self):
        """String .replace() method."""
        unit = parse_unit('''
defun replace_underscore(s):
    return s.replace("_", "-")

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["replace_underscore"]
        assert func("hello_world") == "hello-world"

    def test_slice_syntax(self):
        """Python slice syntax s[3:], s[:3], s[1:3]."""
        unit = parse_unit('''
defun slice_start(s):
    return s[3:]

defun slice_end(s):
    return s[:3]

defun slice_range(s):
    return s[1:4]

module top (clk) { logic clk; }
''')
        for fd in unit.funcdefs:
            register_funcdef(fd)
        assert REGISTRY["slice_start"]("hello") == "lo"
        assert REGISTRY["slice_end"]("hello") == "hel"
        assert REGISTRY["slice_range"]("hello") == "ell"

    def test_negative_index(self):
        """Negative index s[-1]."""
        unit = parse_unit('''
defun last_char(s):
    return s[-1]

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["last_char"]
        assert func("hello") == "o"

    def test_strip_method(self):
        """String .strip() method."""
        unit = parse_unit('''
defun trim(s):
    return s.strip()

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["trim"]
        assert func("  hello  ") == "hello"

    def test_split_method(self):
        """String .split() method with indexing."""
        unit = parse_unit('''
defun first_word(s):
    return s.split("_")[0]

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["first_word"]
        assert func("hello_world_foo") == "hello"

    def test_len_builtin(self):
        """len() built-in function."""
        unit = parse_unit('''
defun add_len(s):
    return s + "_" + str(len(s))

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["add_len"]
        assert func("hello") == "hello_5"

    def test_startswith_method(self):
        """String .startswith() method."""
        unit = parse_unit('''
defun has_data_prefix(s):
    return s.startswith("data")

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        func = REGISTRY["has_data_prefix"]
        # startswith returns bool, which gets converted to string
        assert func("data_in") == "True"
        assert func("bus_in") == "False"


# ────────────────────────────────────────────────────────────────
# Registration tests
# ────────────────────────────────────────────────────────────────


class TestDefunRegistration:
    """Test function registration in REGISTRY."""

    def setup_method(self):
        clear_custom()

    def teardown_method(self):
        clear_custom()

    def test_register_funcdef(self):
        """register_funcdef adds function to REGISTRY."""
        unit = parse_unit('''
defun my_func(s):
    return s

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        assert "my_func" in REGISTRY

    def test_clear_custom_removes_user_funcs(self):
        """clear_custom() removes user-defined functions."""
        unit = parse_unit('''
defun my_func(s):
    return s

module top (clk) { logic clk; }
''')
        register_funcdef(unit.funcdefs[0])
        assert "my_func" in REGISTRY
        clear_custom()
        assert "my_func" not in REGISTRY

    def test_clear_custom_preserves_builtins(self):
        """clear_custom() preserves built-in functions."""
        clear_custom()
        assert "upper" in REGISTRY
        assert "lower" in REGISTRY
        assert "add" in REGISTRY


# ────────────────────────────────────────────────────────────────
# End-to-end integration tests
# ────────────────────────────────────────────────────────────────


class TestDefunIntegration:
    """Test defun end-to-end with the compiler."""

    def test_basic_defun_in_compile(self):
        """defun function works in full compilation."""
        src = '''
defun prefix(s):
    return "bus_" + s

module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$prefix(\\1)" };
}
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "bus_in" in text
        assert "bus_out" in text

    def test_upper_defun_in_compile(self):
        """defun with .upper() works in full compilation."""
        src = '''
defun to_upper(s):
    return s.upper()

module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$to_upper(\\1)" };
}
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "IN" in text
        assert "OUT" in text

    def test_arithmetic_defun_in_compile(self):
        """defun with arithmetic works in full compilation."""
        src = '''
defun inc(n):
    return n + 1

module inner (ch_0, ch_1, ch_2) {
    logic ch_0;
    logic ch_1;
    logic ch_2;
    assign ch_2 = ch_0 & ch_1;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "ch_(.*)" => "bus_$inc(\\1)" };
}
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "bus_1" in text
        assert "bus_2" in text
        assert "bus_3" in text

    def test_defun_after_module(self):
        """defun defined after module still works (processed first)."""
        src = '''
module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$prefix(\\1)" };
}

defun prefix(s):
    return "bus_" + s
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "bus_in" in text
        assert "bus_out" in text

    def test_multiple_defuns_in_compile(self):
        """Multiple defun functions in one instance."""
        src = '''
defun to_upper(s):
    return s.upper()

defun to_lower(s):
    return s.lower()

module inner (data_in, bus_out) {
    logic data_in;
    logic bus_out;
    assign bus_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$to_upper(\\1)", "bus_(.*)" => "$to_lower(\\1)" };
}
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "IN" in text
        assert "out" in text

    def test_defun_with_prefix_suffix(self):
        """defun function with surrounding text."""
        src = '''
defun upper(s):
    return s.upper()

module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "prefix_$upper(\\1)_suffix" };
}
'''
        sv = compile_source(src)
        text = sv["top"]
        assert "prefix_IN_suffix" in text
        assert "prefix_OUT_suffix" in text
