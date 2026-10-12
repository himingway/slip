"""Tests for the include directive (CLI pipeline include resolution)."""

import pytest

from slip.cli._pipeline import run_build, run_check
from slip.errors.semantic import SlipSemanticError


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


class TestIncludeResolution:
    def test_include_merges_modules(self, tmp_path):
        _write(tmp_path, "helpers.slip",
               "module helper (a, b) { logic a; logic b; assign b = a; }")
        top = _write(tmp_path, "top.slip",
                     'include "helpers.slip";\n'
                     "module top (x, y) { logic x; logic y; helper u1 { .a(x), .b(y) }; }")
        result = run_build(top, tmp_path / "out", [])
        assert "helper" in result
        assert "top" in result

    def test_include_merges_defun(self, tmp_path):
        _write(tmp_path, "funcs.slip", "defun prefix(s):\n    return \"pre_\" + s\n")
        top = _write(tmp_path, "top.slip",
                     'include "funcs.slip";\n'
                     "module child (clk, data_a) { logic clk; logic data_a; }\n"
                     'module top (clk, pre_a) { logic clk; logic pre_a;\n'
                     '  child u1 { .clk, "data_(.*)" => "$prefix(\\1)" }; }')
        result = run_build(top, tmp_path / "out", [])
        assert ".data_a(pre_a)" in result["top"]

    def test_nested_include(self, tmp_path):
        _write(tmp_path, "leaf.slip",
               "module leaf (a, b) { logic a; logic b; assign b = a; }")
        _write(tmp_path, "mid.slip",
               'include "leaf.slip";\n'
               "module mid (a, b) { logic a; logic b; leaf u1 { .a(a), .b(b) }; }")
        top = _write(tmp_path, "top.slip",
                     'include "mid.slip";\n'
                     "module top (x, y) { logic x; logic y; mid u1 { .a(x), .b(y) }; }")
        result = run_build(top, tmp_path / "out", [])
        assert {"leaf", "mid", "top"} <= set(result)

    def test_relative_path_resolved_from_including_file(self, tmp_path):
        _write(tmp_path, "lib/common.slip",
               "module common (a, b) { logic a; logic b; assign b = a; }")
        top = _write(tmp_path, "top.slip",
                     'include "lib/common.slip";\n'
                     "module top (x, y) { logic x; logic y; common u1 { .a(x), .b(y) }; }")
        result = run_build(top, tmp_path / "out", [])
        assert "common" in result

    def test_diamond_include_merges_once(self, tmp_path):
        _write(tmp_path, "common.slip",
               "module common (a, b) { logic a; logic b; assign b = a; }")
        _write(tmp_path, "a.slip", 'include "common.slip";\n')
        _write(tmp_path, "b.slip", 'include "common.slip";\n')
        top = _write(tmp_path, "top.slip",
                     'include "a.slip";\ninclude "b.slip";\n'
                     "module top (x, y) { logic x; logic y; common u1 { .a(x), .b(y) }; }")
        # Diamond include must not duplicate the module definition.
        result = run_build(top, tmp_path / "out", [])
        assert "common" in result

    def test_include_cycle_terminates(self, tmp_path):
        _write(tmp_path, "a.slip", 'include "b.slip";\n')
        _write(tmp_path, "b.slip", 'include "a.slip";\n')
        top = _write(tmp_path, "top.slip",
                     "include \"a.slip\";\n"
                     "module top (y) { logic y; assign y = 1'b0; }")
        result = run_build(top, tmp_path / "out", [])
        assert "top" in result

    def test_include_of_entry_file_terminates(self, tmp_path):
        # A file that re-includes the entry file must not duplicate modules.
        top = _write(tmp_path, "top.slip",
                     "include \"top.slip\";\n"
                     "module top (y) { logic y; assign y = 1'b0; }")
        result = run_build(top, tmp_path / "out", [])
        assert "top" in result

    def test_missing_include_reports_location(self, tmp_path):
        top = _write(tmp_path, "top.slip",
                     "include \"nope.slip\";\n"
                     "module top (y) { logic y; assign y = 1'b0; }")
        with pytest.raises(SlipSemanticError, match="cannot find included file"):
            run_build(top, tmp_path / "out", [])

    def test_include_through_check(self, tmp_path):
        _write(tmp_path, "helpers.slip",
               "module helper (a, b) { logic a; logic b; assign b = a; }")
        top = _write(tmp_path, "top.slip",
                     'include "helpers.slip";\n'
                     "module top (x, y) { logic x; logic y; helper u1 { .a(x), .b(y) }; }")
        result = run_check(top, [])
        assert "helper" in result


class TestDuplicateModuleDetection:
    def test_duplicate_module_in_one_file(self, tmp_path):
        top = _write(tmp_path, "top.slip",
                     "module sub (a) { logic a; } "
                     "module sub (b) { logic b; } ")
        with pytest.raises(SlipSemanticError, match="duplicate module definition"):
            run_build(top, tmp_path / "out", [])

    def test_distinct_modules_ok(self, tmp_path):
        top = _write(tmp_path, "top.slip",
                     "module a (x) { logic x; } module b (y) { logic y; } ")
        result = run_build(top, tmp_path / "out", [])
        assert {"a", "b"} <= set(result)
