"""Tests for regex port mapping custom functions."""

import pytest
from pathlib import Path

from slip.semantic.regex_funcs import (
    evaluate_replacement,
    register,
    REGISTRY,
)
from conftest import compile_source, FIXTURES


# ────────────────────────────────────────────────────────────────
# Unit tests for evaluate_replacement
# ────────────────────────────────────────────────────────────────


class TestEvaluateReplacement:
    """Test the evaluate_replacement function directly."""

    def test_simple_backreference(self):
        """Basic \\1 backreference without functions."""
        result = evaluate_replacement(r"bus_\1", "data_in", "data_(.*)")
        assert result == "bus_in"

    def test_multiple_backreferences(self):
        """Multiple backreferences in replacement."""
        result = evaluate_replacement(r"\1_\2", "data_in_out", "(data)_(.*)")
        assert result == "data_in_out"

    def test_upper_function(self):
        """$upper function."""
        result = evaluate_replacement(r"$upper(\1)", "data_in", "data_(.*)")
        assert result == "IN"

    def test_lower_function(self):
        """$lower function."""
        result = evaluate_replacement(r"$lower(\1)", "DATA_IN", "DATA_(.*)")
        assert result == "in"

    def test_reverse_function(self):
        """$reverse function."""
        result = evaluate_replacement(r"$reverse(\1)", "data_abc", "data_(.*)")
        assert result == "cba"

    def test_add_function(self):
        """$add function with backreference and literal."""
        result = evaluate_replacement(r"$add(\1, 1)", "ch_3", "ch_(.*)")
        assert result == "4"

    def test_sub_function(self):
        """$sub function."""
        result = evaluate_replacement(r"$sub(\1, 1)", "ch_5", "ch_(.*)")
        assert result == "4"

    def test_mul_function(self):
        """$mul function."""
        result = evaluate_replacement(r"$mul(\1, 2)", "ch_3", "ch_(.*)")
        assert result == "6"

    def test_div_function(self):
        """$div function."""
        result = evaluate_replacement(r"$div(\1, 2)", "ch_7", "ch_(.*)")
        assert result == "3"

    def test_mod_function(self):
        """$mod function."""
        result = evaluate_replacement(r"$mod(\1, 2)", "ch_7", "ch_(.*)")
        assert result == "1"

    def test_function_with_prefix(self):
        """Function call with text prefix."""
        result = evaluate_replacement(r"prefix_$upper(\1)", "data_in", "data_(.*)")
        assert result == "prefix_IN"

    def test_function_with_suffix(self):
        """Function call with text suffix."""
        result = evaluate_replacement(r"$upper(\1)_suffix", "data_in", "data_(.*)")
        assert result == "IN_suffix"

    def test_function_with_both_prefix_suffix(self):
        """Function call with both prefix and suffix."""
        result = evaluate_replacement(r"pre_$upper(\1)_post", "data_in", "data_(.*)")
        assert result == "pre_IN_post"

    def test_multiple_functions(self):
        """Multiple function calls in one replacement."""
        result = evaluate_replacement(r"$upper(\1)_$lower(\2)", "DATA_IN_OUT", "(DATA)_(.*)")
        assert result == "DATA_in_out"

    def test_nested_function_args(self):
        """Function with multiple backreference args."""
        result = evaluate_replacement(r"$concat(\1, \2)", "a_b", "(.*)_(.*)")
        assert result == "ab"

    def test_unknown_function_raises(self):
        """Unknown function name raises ValueError."""
        with pytest.raises(ValueError, match="unknown regex function"):
            evaluate_replacement(r"$unknown(\1)", "data_in", "data_(.*)")

    def test_no_function_calls(self):
        """Replacement without function calls works as before."""
        result = evaluate_replacement(r"bus_\1", "data_in", "data_(.*)")
        assert result == "bus_in"

    def test_no_match_fallback(self):
        """When port_regex doesn't match, fallback to re.sub."""
        result = evaluate_replacement(r"bus_\1", "other_port", "data_(.*)")
        # When regex doesn't match, re.sub returns original string
        assert result == "other_port"


# ────────────────────────────────────────────────────────────────
# Unit tests for built-in functions
# ────────────────────────────────────────────────────────────────


class TestBuiltinFunctions:
    """Test individual built-in functions."""

    def test_reverse(self):
        from slip.semantic.regex_funcs import _reverse
        assert _reverse("abc") == "cba"
        assert _reverse("a") == "a"
        assert _reverse("") == ""

    def test_upper(self):
        from slip.semantic.regex_funcs import _upper
        assert _upper("abc") == "ABC"
        assert _upper("ABC") == "ABC"
        assert _upper("aBc") == "ABC"

    def test_lower(self):
        from slip.semantic.regex_funcs import _lower
        assert _lower("ABC") == "abc"
        assert _lower("abc") == "abc"
        assert _lower("aBc") == "abc"

    def test_substr(self):
        from slip.semantic.regex_funcs import _substr
        assert _substr("abcdef", 2, 3) == "cde"
        assert _substr("abcdef", 0, 3) == "abc"
        assert _substr("abcdef", 3, 10) == "def"

    def test_replace(self):
        from slip.semantic.regex_funcs import _replace
        assert _replace("abc", "b", "X") == "aXc"
        assert _replace("aaa", "a", "b") == "bbb"
        assert _replace("abc", "d", "X") == "abc"

    def test_concat(self):
        from slip.semantic.regex_funcs import _concat
        assert _concat("ab", "cd") == "abcd"
        assert _concat("", "abc") == "abc"
        assert _concat("abc", "") == "abc"

    def test_add(self):
        from slip.semantic.regex_funcs import _add
        assert _add(3, 1) == "4"
        assert _add(0, 0) == "0"
        assert _add(-1, 1) == "0"

    def test_sub(self):
        from slip.semantic.regex_funcs import _sub
        assert _sub(5, 2) == "3"
        assert _sub(0, 0) == "0"
        assert _sub(1, 5) == "-4"

    def test_mul(self):
        from slip.semantic.regex_funcs import _mul
        assert _mul(2, 3) == "6"
        assert _mul(0, 5) == "0"
        assert _mul(-2, 3) == "-6"

    def test_div(self):
        from slip.semantic.regex_funcs import _div
        assert _div(7, 2) == "3"
        assert _div(6, 3) == "2"
        with pytest.raises(ValueError, match="division by zero"):
            _div(1, 0)

    def test_mod(self):
        from slip.semantic.regex_funcs import _mod
        assert _mod(7, 2) == "1"
        assert _mod(6, 3) == "0"
        with pytest.raises(ValueError, match="division by zero"):
            _mod(1, 0)

    def test_bit_reverse(self):
        from slip.semantic.regex_funcs import _bit_reverse
        assert _bit_reverse("0110") == "0110"
        assert _bit_reverse("1000") == "0001"
        assert _bit_reverse("1") == "1"

    def test_bit_select(self):
        from slip.semantic.regex_funcs import _bit_select
        assert _bit_select("1010", 3, 1) == "010"
        assert _bit_select("1010", 3, 0) == "1010"
        assert _bit_select("1010", 1, 0) == "10"


# ────────────────────────────────────────────────────────────────
# Custom function registration
# ────────────────────────────────────────────────────────────────


class TestCustomFunction:
    """Test custom function registration."""

    def test_register_custom_function(self):
        """Register and use a custom function."""
        def my_func(s: str) -> str:
            return f"custom_{s}"

        register("my_func", my_func)
        assert "my_func" in REGISTRY

        result = evaluate_replacement(r"$my_func(\1)", "data_in", "data_(.*)")
        assert result == "custom_in"

    def test_override_builtin(self):
        """Custom function can override built-in."""
        original = REGISTRY.get("upper")
        try:
            def my_upper(s: str) -> str:
                return f"MY_{s.upper()}"

            register("upper", my_upper)
            result = evaluate_replacement(r"$upper(\1)", "data_in", "data_(.*)")
            assert result == "MY_IN"
        finally:
            # Restore original
            if original:
                REGISTRY["upper"] = original


# ────────────────────────────────────────────────────────────────
# Integration tests with compile_source
# ────────────────────────────────────────────────────────────────


class TestRegexFuncsIntegration:
    """Test regex functions end-to-end with the compiler."""

    def test_upper_in_compile(self):
        """$upper function works in full compilation."""
        src = """
module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$upper(\\1)" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        # $upper(\1) with "data_in" → captures "in" → "IN"
        assert "IN" in text

    def test_lower_in_compile(self):
        """$lower function works in full compilation."""
        src = """
module inner (DATA_IN, DATA_OUT) {
    logic DATA_IN;
    logic DATA_OUT;
    assign DATA_OUT = DATA_IN;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "DATA_(.*)" => "$lower(\\1)" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        # $lower(\1) with "DATA_IN" → captures "IN" → "in"
        assert "in" in text

    def test_add_in_compile(self):
        """$add function works in full compilation."""
        src = """
module inner (ch_0, ch_1, ch_2) {
    logic ch_0;
    logic ch_1;
    logic ch_2;
    assign ch_2 = ch_0 & ch_1;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "ch_(.*)" => "bus_$add(\\1, 1)" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        assert "bus_1" in text
        assert "bus_2" in text
        assert "bus_3" in text

    def test_reverse_in_compile(self):
        """$reverse function works in full compilation."""
        src = """
module inner (abc, def_) {
    logic abc;
    logic def_;
    assign def_ = abc;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "(.*)" => "$reverse(\\1)" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        assert "cba" in text
        assert "_fed" in text

    def test_mixed_functions_in_compile(self):
        """Multiple different functions in one instance."""
        src = """
module inner (data_in, bus_out) {
    logic data_in;
    logic bus_out;
    assign bus_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "$upper(\\1)", "bus_(.*)" => "$lower(\\1)" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        assert "IN" in text
        assert "out" in text

    def test_function_with_prefix_suffix(self):
        """Function call with surrounding text."""
        src = """
module inner (data_in, data_out) {
    logic data_in;
    logic data_out;
    assign data_out = data_in;
}

module top (clk) {
    logic clk;
    inner u1 { .clk, "data_(.*)" => "prefix_$upper(\\1)_suffix" };
}
"""
        sv = compile_source(src)
        text = sv["top"]
        assert "prefix_IN_suffix" in text
        assert "prefix_OUT_suffix" in text
