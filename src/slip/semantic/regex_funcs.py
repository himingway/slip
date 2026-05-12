"""Regex port mapping function registry and evaluator.

Provides built-in functions for transforming captured groups in regex
port mapping replacements. Functions are called with ``$func(args)``
syntax in the replacement string.

Example::

    child u1 {
        .clk,
        "data_(.*)" => "$upper(\\1)",
        "bus_(.*)" => "$add(\\1, 1)"
    };
"""

from __future__ import annotations

import re
from typing import Callable

# Function registry: name -> callable
REGISTRY: dict[str, Callable[..., str]] = {}


def register(name: str, func: Callable[..., str]) -> None:
    """Register a custom function for use in regex replacements."""
    REGISTRY[name] = func


# Names of built-in functions (should not be cleared by clear_custom)
_BUILTIN_NAMES = frozenset({
    "reverse", "upper", "lower", "substr", "replace", "concat",
    "add", "sub", "mul", "div", "mod", "bit_reverse", "bit_select",
})


def clear_custom() -> None:
    """Remove all non-built-in functions from the registry."""
    to_remove = [k for k in REGISTRY if k not in _BUILTIN_NAMES]
    for k in to_remove:
        del REGISTRY[k]


# ── String functions ──────────────────────────────────────────────


def _reverse(s: str) -> str:
    """Reverse a string."""
    return s[::-1]


def _upper(s: str) -> str:
    """Convert to uppercase."""
    return s.upper()


def _lower(s: str) -> str:
    """Convert to lowercase."""
    return s.lower()


def _substr(s: str, start: int, length: int) -> str:
    """Extract substring starting at index with given length."""
    return s[start:start + length]


def _replace(s: str, old: str, new: str) -> str:
    """Replace all occurrences of old with new."""
    return s.replace(old, new)


def _concat(s1: str, s2: str) -> str:
    """Concatenate two strings."""
    return s1 + s2


# ── Arithmetic functions ──────────────────────────────────────────


def _add(a, b) -> str:
    """Add two integers."""
    return str(int(a) + int(b))


def _sub(a, b) -> str:
    """Subtract two integers."""
    return str(int(a) - int(b))


def _mul(a, b) -> str:
    """Multiply two integers."""
    return str(int(a) * int(b))


def _div(a, b) -> str:
    """Integer division."""
    b_int = int(b)
    if b_int == 0:
        raise ValueError("division by zero")
    return str(int(a) // b_int)


def _mod(a, b) -> str:
    """Modulo operation."""
    b_int = int(b)
    if b_int == 0:
        raise ValueError("division by zero")
    return str(int(a) % b_int)


# ── Bit manipulation functions ────────────────────────────────────


def _bit_reverse(s: str) -> str:
    """Reverse the bits in a binary string."""
    return s[::-1]


def _bit_select(s: str, high: int, low: int) -> str:
    """Select bits from high to low (inclusive)."""
    if high < low:
        raise ValueError(f"high ({high}) must be >= low ({low})")
    if high >= len(s):
        raise ValueError(f"high ({high}) out of range for string of length {len(s)}")
    return s[low:high + 1]


# ── Register built-in functions ───────────────────────────────────

# String functions
register("reverse", _reverse)
register("upper", _upper)
register("lower", _lower)
register("substr", _substr)
register("replace", _replace)
register("concat", _concat)

# Arithmetic functions
register("add", _add)
register("sub", _sub)
register("mul", _mul)
register("div", _div)
register("mod", _mod)

# Bit manipulation functions
register("bit_reverse", _bit_reverse)
register("bit_select", _bit_select)


# ── Pattern for function calls ────────────────────────────────────

# Matches: $func_name(arg1, arg2, ...)
_FUNC_PATTERN = re.compile(r'\$(\w+)\(([^)]*)\)')


def _resolve_arg(arg: str, match: re.Match) -> str:
    """Resolve a function argument.

    - ``\\N`` → captured group N from the regex match
    - Otherwise → literal string
    """
    # Check if it's a backreference like \1, \2, etc.
    backref_match = re.match(r'^\\(\d+)$', arg.strip())
    if backref_match:
        group_num = int(backref_match.group(1))
        return match.group(group_num)

    return arg.strip()


def evaluate_replacement(
    signal_regex: str,
    port_name: str,
    port_regex: str,
) -> str:
    """Evaluate a replacement string with function calls.

    Processes ``$func(...)`` calls in the replacement string, resolving
    backreferences (``\\1``, ``\\2``, etc.) and calling registered functions.

    Args:
        signal_regex: The replacement string (may contain ``$func(...)`` calls)
        port_name: The actual port name being matched
        port_regex: The port regex pattern used for matching

    Returns:
        The final signal name after all function evaluations

    Example::

        >>> evaluate_replacement("$upper(\\1)", "data_in", "data_(.*)")
        "IN"
    """
    match = re.fullmatch(port_regex, port_name)
    if not match:
        # Fallback to simple substitution
        return re.sub(port_regex, signal_regex, port_name)

    # First, do a simple re.sub to resolve all \N backreferences
    # This handles cases without function calls
    if '$' not in signal_regex:
        return re.sub(port_regex, signal_regex, port_name)

    # Process function calls
    result = signal_regex
    while True:
        m = _FUNC_PATTERN.search(result)
        if not m:
            break

        func_name = m.group(1)
        args_str = m.group(2)

        if func_name not in REGISTRY:
            raise ValueError(f"unknown regex function: ${func_name}")

        func = REGISTRY[func_name]

        # Parse arguments
        if args_str.strip():
            raw_args = [a.strip() for a in args_str.split(',')]
            resolved_args = [_resolve_arg(a, match) for a in raw_args]
        else:
            resolved_args = []

        # Call the function
        try:
            func_result = func(*resolved_args)
        except Exception as e:
            raise ValueError(f"error in ${func_name}: {e}") from e

        # Replace the function call with the result
        start, end = m.span()
        result = result[:start] + func_result + result[end:]

    # After all function calls are resolved, do final backreference substitution
    # for any remaining \N patterns (shouldn't be any, but handle edge cases)
    result = re.sub(port_regex, result, port_name)

    return result
