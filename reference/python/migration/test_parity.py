"""Behavioral migration tests; Python is an oracle, never a native runtime dependency."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import warnings
from pathlib import Path

import pytest
import pyslang

from slip.cli._pipeline import run_check, _resolve_includes
from slip.codegen import CodeGenerator
from slip.lexer import Lexer
from slip.parser import Parser
from slip.semantic import SemanticAnalyzer
from slip.semantic.ir_builder import _collect_for_vars
from slip.errors.base import SlipError

ROOT = Path(__file__).resolve().parents[3]
REFERENCE_TESTS = ROOT / "reference/python/tests"
BINARY = Path(os.environ.get("SLIP_BIN", ROOT / "build/release/slip"))
IP = ROOT / "tests/fixtures/ip"


def native(source, tmp_path, *, ip_dirs=(), filelists=(), strict=False):
    out = tmp_path / "generated"
    command = [str(BINARY), "build", "-", "-o", str(out), "--diagnostics=json"]
    for directory in ip_dirs:
        command += ["-ip", str(directory)]
    for file in filelists:
        command += ["-f", str(file)]
    if strict:
        command += ["--strict"]
    result = subprocess.run(command, input=source, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return {file.stem: file.read_text() for file in out.glob("*.sv")}


def cases():
    seen = set()
    for file in sorted(REFERENCE_TESTS.rglob("test_*.py")):
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "module " in node.value and node.value not in seen:
                seen.add(node.value)
                yield pytest.param(node.value, id=f"{file.stem}:{node.lineno}")
    # These programs moved out of the Python test into the shared C++ test tree.
    for name in ["design.slip", "tb.sv"]:
        yield pytest.param((ROOT / "tests/behavior" / name).read_text(), id=f"behavior:{name}")


def reference(source):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        unit = Parser(Lexer(source, "test.slip").tokenize(), "test.slip").parse()
        _resolve_includes(unit, ROOT)
        return CodeGenerator().generate(SemanticAnalyzer().analyze(unit, [IP]))


def syntax(source):
    tree = json.loads(pyslang.SyntaxTree.fromText(source).to_json())["root"]

    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        kind = value.get("kind")
        if kind == "ParenthesizedExpression":
            return normalize(value["expression"])
        result = {key: normalize(item) for key, item in value.items() if key != "trivia"}
        # Independent declarations / processes may be emitted in a different order.
        if kind == "ModuleDeclaration":
            if "members" in result:
                result["members"] = sorted(result["members"], key=lambda x: json.dumps(x, sort_keys=True))
        # Python historically used sets for implicit port ordering.
        if kind == "AnsiPortList":
            result["ports"] = sorted([port for port in result["ports"] if port.get("kind") != "Comma"], key=lambda x: json.dumps(x, sort_keys=True))
        return result

    return normalize(tree)


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
@pytest.mark.parametrize("source", list(cases()))
def test_existing_programs(source, tmp_path):
    try:
        expected = reference(source)
    except SlipError:
        result = subprocess.run([str(BINARY), "check", "-", "-ip", str(IP)],
            input=source, text=True, capture_output=True, timeout=30)
        assert result.returncode == 1, result.stdout + result.stderr
        return
    actual = native(source, tmp_path, ip_dirs=[IP])
    assert actual.keys() == expected.keys()
    parsed = Parser(Lexer(source).tokenize()).parse()
    implicit_loops = {module.name: _collect_for_vars(module.body) for module in parsed.modules if not module.ports}
    for name in expected:
        expected_syntax = syntax(expected[name])
        # Intentional fix: runtime loop variables belong to their process; the old
        # implicit-interface analysis accidentally exposed them as module inputs.
        loops = implicit_loops.get(name, set())
        ports = expected_syntax["header"].get("ports")
        if loops and ports:
            ports["ports"] = [p for p in ports["ports"] if p["declarator"]["name"]["text"] not in loops]
            if not ports["ports"]:
                del expected_syntax["header"]["ports"]
        assert syntax(actual[name]) == expected_syntax, name


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
@pytest.mark.parametrize("file", sorted((ROOT / "tests/fixtures").glob("*.slip")), ids=lambda p: p.name)
def test_fixtures(file, tmp_path):
    expected = run_check(file, [IP])
    actual = native(file.read_text(), tmp_path, ip_dirs=[IP])
    for name in expected:
        assert syntax(actual[name]) == syntax(expected[name]), name


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_native_behavior_against_independent_rtl(tmp_path):
    specification = importlib.util.spec_from_file_location("native_behavior", REFERENCE_TESTS / "test_integration/test_behavior.py")
    module = importlib.util.module_from_spec(specification)
    # The test's own import uses the existing helpers; only its compile call is replaced.
    import sys
    sys.path.insert(0, str(REFERENCE_TESTS))
    try:
        specification.loader.exec_module(module)
        module.compile_source = lambda source: native(source, tmp_path)
        module.test_pipeline_and_metaprogram_arithmetic_match_reference(tmp_path)
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_runtime_needs_no_python(tmp_path):
    result = subprocess.run([str(BINARY), "build", "-", "--stdout"],
        input="module m(a,y) { assign y=a; }", text=True, capture_output=True,
        env={**os.environ, "PATH": ""}, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "assign y = a;" in result.stdout


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_failure_does_not_publish_outputs(tmp_path):
    out = tmp_path / "out"
    result = subprocess.run([str(BINARY), "build", "-", "-o", str(out), "--diagnostics=json"],
        input="module good(a,y) { assign y=a; } module bad { unknown x {}; }",
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 1
    assert not out.exists()
    diagnostic = json.loads(result.stderr.splitlines()[-1])
    assert diagnostic["code"] == "E_MODULE"


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_filelist_include_and_caller_parameter(tmp_path):
    (tmp_path / "defs.svh").write_text("`define EXTRA 1\n")
    (tmp_path / "ip.sv").write_text('`include "defs.svh"\nmodule ext #(parameter W=8)(input logic [W+`EXTRA-1:0] a, output logic [W+`EXTRA-1:0] y); assign y=a; endmodule\n')
    filelist = tmp_path / "sources.f"
    filelist.write_text("+incdir+.\nip.sv\n")
    source = "module top #(param W=16)(a,y) { ext #(.W(W)) u {.a,.y}; }"
    expected = CodeGenerator().generate(SemanticAnalyzer().analyze(Parser(Lexer(source).tokenize()).parse(), [], [filelist]))
    actual = native(source, tmp_path, filelists=[filelist])
    assert syntax(actual["top"]) == syntax(expected["top"])


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
@pytest.mark.parametrize("expression", [
    's.upper()', 's.lower()', 's.reverse()', 's[1:4]', 's[-1]',
    's.replace("_", "X")', 's.strip("h")', 's.split("_")[0]',
    's.rsplit("_",1)[1]', '"_".join(s.split("_")[1:])',
    's.startswith("h")', 's.endswith("x")',
    's.endswith("x") ? "yes" : "no"',
    'str(s.find("w",2))', 'str(s.rfind("l",1,8))',
    'str(s.count("l",1,8))', 's.startswith("world",6)',
    's.title()', 's.capitalize()', 's.swapcase()', 's.casefold()',
    's.isalpha()', 's.isalnum()', 's.isdigit()', 's.islower()', 's.isupper()',
    's.removeprefix("hello_")', 's.removesuffix("_world")',
    's.rjust(12,"X")', 's.ljust(12,"X")',
])
def test_defun_interpreter_matches_reference(expression, tmp_path):
    source = f'''defun f(s):
    return {expression}
module child(p_hello_world) {{ logic p_hello_world; }}
module top {{ child u {{ "p_(.*)" => "sig_$f(\\1)" }}; }}
'''
    expected = reference(source)
    actual = native(source, tmp_path)
    assert syntax(actual["top"]) == syntax(expected["top"])


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_include_diamond_and_cycle(tmp_path):
    (tmp_path / "leaf.slip").write_text('include "top.slip"; module child(a,y) { assign y=a; }')
    (tmp_path / "left.slip").write_text('include "leaf.slip";')
    (tmp_path / "right.slip").write_text('include "leaf.slip";')
    entry = tmp_path / "top.slip"
    entry.write_text('include "left.slip"; include "right.slip"; module top(a,y) { child u {.a,.y}; }')
    expected = run_check(entry, [])
    result = subprocess.run([str(BINARY), "build", str(entry), "-o", str(tmp_path / "out")], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for name in expected:
        assert syntax((tmp_path / "out" / f"{name}.sv").read_text()) == syntax(expected[name])


@pytest.mark.skipif(not BINARY.is_file(), reason="build the native compiler first")
def test_ip_module_already_instantiated_inside_other_ip(tmp_path):
    (tmp_path / "ip.sv").write_text('''
module ext_leaf #(parameter W=8)(input logic [W-1:0] a, output logic [W-1:0] y); assign y=a; endmodule
module ext_parent(input logic [7:0] a, output logic [7:0] y); ext_leaf u(.a,.y); endmodule
''')
    modules = native("module top(a,y) { ext_leaf #(.W(16)) u {.a,.y}; }", tmp_path, ip_dirs=[tmp_path])
    assert "input logic [15:0] a" in modules["top"]
    assert "output logic [15:0] y" in modules["top"]
