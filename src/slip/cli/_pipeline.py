from __future__ import annotations

from pathlib import Path

from slip.codegen import CodeGenerator
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer


def run_build(
    source: Path,
    out_dir: Path,
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> dict[str, str]:
    """Full compilation pipeline: source -> SV files."""
    text = source.read_text()
    filename = str(source)

    # Lex
    tokens = Lexer(text, filename).tokenize()

    # Parse
    unit = Parser(tokens, filename).parse()

    # Semantic analysis
    ir_modules = SemanticAnalyzer().analyze(unit, ip_dirs, filelists)

    # Generate
    return CodeGenerator().generate(ir_modules, output_dir=out_dir)


def run_check(
    source: Path,
    ip_dirs: list[Path],
    filelists: list[Path] | None = None,
) -> None:
    """Check pipeline: source -> semantic analysis, no output."""
    text = source.read_text()
    filename = str(source)

    # Lex
    tokens = Lexer(text, filename).tokenize()

    # Parse
    unit = Parser(tokens, filename).parse()

    # Semantic analysis (validates IR construction)
    SemanticAnalyzer().analyze(unit, ip_dirs, filelists)
