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


# ── Replacement evaluation ────────────────────────────────────────


def _find_balanced_parens(text: str, open_idx: int) -> int:
    """Return the index of the ')' matching the '(' at *open_idx*."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced parentheses in regex replacement")


def _resolve_piece(text: str, match: re.Match) -> str:
    """Expand backreferences (``\\N``) and ``$func(...)`` calls in *text*.

    The result is assembled piece by piece from the template; function
    outputs are inserted verbatim and never re-expanded.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1].isdigit():
            group_num = int(text[i + 1])
            if group_num > match.re.groups:
                raise ValueError(
                    f"invalid backreference \\{group_num}: pattern has "
                    f"{match.re.groups} group(s)"
                )
            out.append(match.group(group_num))
            i += 2
        elif ch == "$":
            name_end = i + 1
            while name_end < len(text) and (text[name_end].isalnum() or text[name_end] == "_"):
                name_end += 1
            func_name = text[i + 1:name_end]
            if not func_name or name_end >= len(text) or text[name_end] != "(":
                raise ValueError(f"malformed function call near '${func_name}'")
            close_idx = _find_balanced_parens(text, name_end)
            args_str = text[name_end + 1:close_idx]
            out.append(_call_func(func_name, args_str, match))
            i = close_idx + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _call_func(func_name: str, args_str: str, match: re.Match) -> str:
    """Look up and call a registered function with resolved arguments."""
    if func_name not in REGISTRY:
        raise ValueError(f"unknown regex function: ${func_name}")
    func = REGISTRY[func_name]

    resolved_args: list[str] = []
    if args_str.strip():
        # Split on top-level commas only (nested $func(...) calls may
        # themselves contain commas).
        raw_args: list[str] = []
        depth = 0
        current: list[str] = []
        for ch in args_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                raw_args.append("".join(current))
                current = []
            else:
                current.append(ch)
        raw_args.append("".join(current))

        for raw in raw_args:
            stripped = raw.strip()
            # A pure backreference resolves to the captured group;
            # anything else (including nested $func calls) is expanded
            # as a replacement template against the same match.
            backref = re.fullmatch(r"\\(\d+)", stripped)
            if backref:
                group_num = int(backref.group(1))
                if group_num > match.re.groups:
                    raise ValueError(
                        f"invalid backreference \\{group_num}: pattern has "
                        f"{match.re.groups} group(s)"
                    )
                resolved_args.append(match.group(group_num))
            else:
                resolved_args.append(_resolve_piece(stripped, match))

    try:
        return str(func(*resolved_args))
    except Exception as e:
        raise ValueError(f"error in ${func_name}: {e}") from e


def evaluate_replacement(
    signal_regex: str,
    port_name: str,
    port_regex: str,
) -> str:
    """Evaluate a replacement string with function calls.

    The replacement template is expanded exactly once against the
    ``fullmatch`` of *port_regex* on *port_name*: backreferences
    (``\\1``, ``\\2``, ...) resolve to captured groups and ``$func(...)``
    calls are invoked with the resolved arguments.  Function outputs are
    inserted verbatim (never re-expanded), and patterns that can also
    match the empty string produce the expanded template itself rather
    than a doubled substitution.

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
        raise ValueError(
            f"replacement evaluated without a match: '{port_regex}' "
            f"does not fullmatch '{port_name}'"
        )
    return _resolve_piece(signal_regex, match)
