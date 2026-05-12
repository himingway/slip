"""Shared test helpers and fixtures for the Slip test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from slip.codegen import CodeGenerator
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer

# ── Shared constants ────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
IP_DIR = FIXTURES / "ip"


# ── Pipeline helpers ────────────────────────────────────────────


def compile_source(source: str, ip_dirs: list[Path] | None = None) -> dict[str, str]:
    """Compile a Slip source string through the full pipeline.

    Returns a dict mapping module name -> generated SystemVerilog text.
    """
    tokens = Lexer(source, "test.slip").tokenize()
    unit = Parser(tokens, "test.slip").parse()
    ir = SemanticAnalyzer().analyze(unit, ip_dirs or [])
    return CodeGenerator().generate(ir)


def compile_from_path(slip_path: Path, ip_dirs: list[Path]) -> dict[str, str]:
    """Compile a .slip file on disk, with IP directory resolution."""
    tokens = Lexer(slip_path.read_text(), str(slip_path)).tokenize()
    unit = Parser(tokens, str(slip_path)).parse()
    ir = SemanticAnalyzer().analyze(unit, ip_dirs)
    return CodeGenerator().generate(ir)


def parse_source(source: str):
    """Lex + parse a Slip source string, returning the list of AST modules."""
    tokens = Lexer(source, "test.slip").tokenize()
    unit = Parser(tokens, "test.slip").parse()
    return unit.modules


def parse_unit(source: str):
    """Lex + parse a Slip source string, returning the CompilationUnit."""
    tokens = Lexer(source, "test.slip").tokenize()
    return Parser(tokens, "test.slip").parse()


def parse_module(source: str):
    """Lex + parse and return only the first AST module."""
    return parse_source(source)[0]


# ── pyslang validation helper ───────────────────────────────────


def validate_sv(sv_text: str, allow_missing_modules: bool = False) -> list:
    """Validate SystemVerilog text with pyslang.

    If *allow_missing_modules* is True, diagnostics whose code contains
    ``UnknownModule``, ``UndeclaredIdentifier``, ``CouldNotResolve`` or
    ``NotAModule`` are filtered out (useful for single-module validation).

    Returns the list of pyslang Diagnostic objects that are considered errors.
    """
    pyslang = pytest.importorskip("pyslang")
    tree = pyslang.SyntaxTree.fromText(sv_text, "test.sv")
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    errors = [d for d in comp.getAllDiagnostics() if d.isError()]
    if allow_missing_modules:
        suppressed = {"UnknownModule", "UndeclaredIdentifier", "CouldNotResolve", "NotAModule"}
        errors = [
            e for e in errors
            if not any(s in str(e.code) for s in suppressed)
        ]
    return errors


def validate_sv_all(sv_dict: dict[str, str]) -> None:
    """Validate every module in *sv_dict* with pyslang, asserting no errors."""
    pyslang = pytest.importorskip("pyslang")
    for name, text in sv_dict.items():
        tree = pyslang.SyntaxTree.fromText(text, f"{name}.sv")
        comp = pyslang.Compilation()
        comp.addSyntaxTree(tree)
        errors = [d for d in comp.getAllDiagnostics() if d.isError()]
        assert errors == [], f"pyslang errors in {name}.sv: {errors}"
