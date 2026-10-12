"""Regressions for semantic correctness across the complete compiler pipeline."""

import pytest
from click.testing import CliRunner
from pyslang import Compilation, SourceManager, SyntaxTree

from conftest import compile_source
from slip.cli._pipeline import run_build, run_check
from slip.cli.main import slip
from slip.errors.codegen import SlipCodegenError
from slip.errors.semantic import SlipSemanticError


def elaborate(modules):
    manager = SourceManager()
    compilation = Compilation()
    for name, source in modules.items():
        compilation.addSyntaxTree(SyntaxTree.fromText(source, manager, f"{name}.sv"))
    root = compilation.getRoot()
    assert not [d for d in compilation.getAllDiagnostics() if d.isError()]
    # pyslang 10 does not retain a Python-created source manager; keep it
    # alive alongside the compilation while inspecting reflected symbols.
    return (compilation, manager), root


@pytest.mark.parametrize("expression,expected", [
    ("2 && 3", 1), ("2 || 3", 1), ("-3 / 2", -1), ("-3 % 2", -1),
    ("0 && (1 / 0)", 0), ("1 || (1 / 0)", 1),
    ("(8'hff + 8'h01) >> 1", 0), ("8'hff < 8'h00", 0),
])
def test_metaprogram_uses_sv_constant_semantics(expression, expected):
    source = (
        f"module m(y) {{ logic y; localparam RESULT={expression}; "
        f"`if (RESULT == {expected}) {{ assign y=1'b1; }} "
        "`else { assign y=1'b0; } }"
    )
    assert "assign y = 1'b1;" in compile_source(source)["m"]


@pytest.mark.parametrize("expression", [
    "2 && 3", "2 || 3", "(8'hff + 8'h01) >> 1", "8'hxx & 8'hff",
    "{8'hff + 8'h01, 8'h00}", "1'bx * 0", "1'b0 ? 8'h00 : 16'hffff",
])
def test_hardware_expression_survives_metaprogram_substitution(expression):
    sv = compile_source(
        "module m(y) { logic [15:0] y; "
        "`for (`i=0; `i<1; `i=`i+1) { "
        f"assign y={expression}; }} }}"
    )["m"]
    # Check the syntax of the RHS, including literal sizes, against the source.
    # Equivalence here also protects four-state expressions that a two-state
    # simulator cannot exercise.
    generated = SyntaxTree.fromText(sv)
    reference = SyntaxTree.fromText(f"module m; assign y={expression}; endmodule")
    generated_assignment = list(generated.root.members)[-1]
    reference_assignment = list(reference.root.members)[-1]
    assert generated_assignment.isEquivalentTo(reference_assignment)


@pytest.mark.parametrize("order", ["leaf mid top", "top mid leaf", "mid top leaf"])
def test_multilevel_interfaces_propagate_independent_of_source_order(order):
    sources = {
        "leaf": "module leaf(a,q) { logic [7:0] a; logic [7:0] q; assign q=a; }",
        "mid": "module mid(a,q) { leaf u { .a, .q }; }",
        "top": "module top(a,q) { mid u { .a, .q }; }",
    }
    _, root = elaborate(compile_source(" ".join(sources[name] for name in order.split())))
    ports = {p.name: p for p in root.lookupName("top").body.portList}
    assert ports["a"].type.bitWidth == ports["q"].type.bitWidth == 8
    assert "Out" in str(ports["q"].direction)


@pytest.mark.parametrize("override,width", [("", 8), ("#(.W(16))", 16)])
def test_local_parameterized_port_inference(override, width):
    _, root = elaborate(compile_source(
        "module child #(param W=8)(a,q) { "
        "logic [W-1:0] a; logic [W-1:0] q; assign q=a; } "
        f"module top(a,q) {{ child {override} u {{ .a, .q }}; }}"
    ))
    assert all(p.type.bitWidth == width for p in root.lookupName("top").body.portList)


def test_parameter_override_stays_in_parent_scope():
    sv = compile_source(
        "module child #(param W=8)(a,q) { localparam N=W*2; "
        "logic [N-1:0] a; logic [N-1:0] q; assign q=a; } "
        "module top #(param W=5)(a,q) { child #(.W(W+1)) u { .a, .q }; }"
    )
    sv["harness"] = "module harness; top #(.W(9)) u(); endmodule"
    _, root = elaborate(sv)
    ports = root.lookupName("harness").body.lookupName("u").body.portList
    assert all(p.type.bitWidth == 20 for p in ports)


def test_parameterized_ip_keeps_preprocessor_and_caller_scope(tmp_path):
    headers = tmp_path / "headers"
    sources = tmp_path / "ip"
    headers.mkdir()
    sources.mkdir()
    (headers / "width.svh").write_text("`define DEFAULT_WIDTH 8\n")
    (sources / "child.sv").write_text(
        '`include "width.svh"\n'
        "module child #(parameter W=`DEFAULT_WIDTH)(input logic [W-1:0] a, "
        "output logic [W-1:0] q); assign q=a; endmodule"
    )
    filelist = tmp_path / "sources.f"
    filelist.write_text("+incdir+headers\nip/child.sv\n")
    sv = compile_source(
        "module top #(param WIDTH=16)(a,q) { child #(.W(WIDTH)) u { .a, .q }; }",
        filelists=[filelist],
    )
    assert "WIDTH" in sv["top"]
    assert "[7:0]" not in sv["top"]


@pytest.mark.parametrize("connection,message", [
    ("child u { .a, .q, .typo(a) };", "port 'typo' does not exist"),
    ("child #(.TYPO(16)) u { .a, .q };", "parameter 'TYPO' does not exist"),
    ("child #(.W(8), .W(16)) u { .a, .q };", "duplicate parameter override"),
])
def test_bad_interfaces_report_source_location(connection, message):
    with pytest.raises(SlipSemanticError, match=message) as error:
        compile_source(
            "module child #(param W=8)(a,q) { assign q=a; }\n"
            f"module top(a,q) {{ {connection} }}"
        )
    assert "test.slip:2:" in str(error.value)


@pytest.mark.parametrize("nested", [
    "seq(clk) { q=a; }", "comb { q=a; }", "initial { q=a; }",
    "child u { .a, .q };",
])
def test_unsupported_nesting_is_rejected(nested):
    with pytest.raises(SlipSemanticError, match="not supported inside a procedural block"):
        compile_source(
            "module child(a,q) { assign q=a; } "
            f"module top(clk,a,q) {{ comb {{ {nested} }} }}"
        )


def test_comma_localparams_work_in_metaprogram_and_codegen():
    sv = compile_source(
        "module top(y) { localparam A=1, B=A+1; "
        "`if (B==2) { assign y=1'b1; } }"
    )["top"]
    assert "localparam A = 1;" in sv and "localparam B = A + 1;" in sv
    assert "assign y = 1'b1;" in sv


def test_metaprogram_parameter_literals_keep_their_width_and_order():
    sv = compile_source(
        "module m #(param Z=8'hff, param A=8'h01)(y) { logic y; "
        "localparam R=(Z+A)>>1; "
        "`if (R==0) { assign y=1'b1; } `else { assign y=1'b0; } }"
    )["m"]
    assert "assign y = 1'b1;" in sv


def test_same_name_connections_declare_implicit_signals(tmp_path):
    source = tmp_path / "m.slip"
    source.write_text(
        "module child(a,q) { assign q=a; } "
        "module top(q) { child u { .a, .q }; }"
    )
    assert "logic a;" in run_check(source, [])["top"]
    with pytest.raises(SlipSemanticError, match="explicit declarations"):
        run_check(source, [], strict=True)


@pytest.mark.parametrize("statement", [
    "if(q) { q=1'b0; } else { q=1'b1; }",
    "case(q) { 1'b0: q=1'b1; default: q=1'b0; }",
    "q=q[0];",
])
def test_control_and_selected_feedback_are_detected(statement):
    with pytest.raises(SlipSemanticError, match="combinational loop"):
        compile_source(f"module top(q) {{ comb {{ {statement} }} }}")


def test_initialized_condition_does_not_make_a_loop():
    compile_source("module top(a,q) { comb { q=a; if(q) { q=1'b0; } } }")


def test_output_select_drives_storage_but_not_index():
    _, root = elaborate(compile_source(
        "module child(q) { assign q=1'b1; } "
        "module top(q,k) { logic [3:0] q; logic [1:0] k; child u { .q(q[0]) }; }"
    ))
    ports = {p.name: p for p in root.lookupName("top").body.portList}
    assert "Out" in str(ports["q"].direction)
    assert "In" in str(ports["k"].direction)


def test_instance_drivers_cannot_overlap():
    with pytest.raises(SlipSemanticError, match="multiple drivers"):
        compile_source(
            "module child(q) { assign q=1'b1; } "
            "module top(q) { child u1 { .q }; child u2 { .q }; }"
        )


def test_instance_and_procedural_driver_conflict():
    with pytest.raises(SlipSemanticError, match="multiple drivers"):
        compile_source(
            "module child(q) { assign q=1'b1; } "
            "module top(q) { comb { q=1'b0; } child u { .q }; }"
        )


def test_disjoint_instance_outputs_are_allowed():
    compile_source(
        "module child(q) { assign q=1'b1; } "
        "module top(q) { logic [1:0] q; child u1 { .q(q[0]) }; child u2 { .q(q[1]) }; }"
    )


def test_frozen_parameter_override_is_rejected():
    with pytest.raises(SlipSemanticError, match="controls Slip compile-time expansion"):
        compile_source(
            "module child #(param N=4)(q) { localparam B=N/2; "
            "`if (B>1) { assign q=1'b1; } `else { assign q=1'b0; } } "
            "module top(q) { child #(.N(8)) u { .q }; }"
        )


def test_downstream_sv_cannot_override_frozen_parameter():
    from slip.codegen.generator import validate_design
    sv = compile_source(
        "module child #(param N=4)(q) { "
        "`if (N==4) { assign q=1'b1; } `else { assign q=1'b0; } }"
    )
    sv["harness"] = "module harness; child #(.N(8)) u(); endmodule"
    with pytest.raises(SlipCodegenError, match="cannot be overridden"):
        validate_design(sv)


def test_failed_validation_does_not_write_partial_outputs(tmp_path):
    source = tmp_path / "bad.slip"
    source.write_text(
        "module good(q) { assign q=1'b0; } "
        "module bad(q) { assign q=missing_function(); }"
    )
    output = tmp_path / "out"
    output.mkdir()
    existing = output / "good.sv"
    existing.write_text("existing artifact")
    with pytest.raises(SlipCodegenError, match="validation failed"):
        run_build(source, output, [])
    assert existing.read_text() == "existing artifact"
    assert not (output / "bad.sv").exists()
    with pytest.raises(SlipCodegenError):
        run_check(source, [])


@pytest.mark.parametrize("command", ["build", "check"])
def test_strict_cli_requires_declarations(tmp_path, command):
    source = tmp_path / "typo.slip"
    source.write_text("module m(a,q) { assign q=typo; }")
    args = [command, str(source), "--strict"]
    if command == "build":
        args += ["-o", str(tmp_path / "out")]
    result = CliRunner().invoke(slip, args)
    assert result.exit_code == 1
    assert "explicit declarations" in result.output and "typo" in result.output


def test_strict_mode_checks_ip_port_widths(tmp_path):
    ip = tmp_path / "child.sv"
    ip.write_text("module child(input logic [7:0] a); endmodule")
    source = tmp_path / "top.slip"
    source.write_text("module top(a) { logic [15:0] a; child u { .a }; }")
    with pytest.raises(SlipCodegenError, match="validation failed"):
        run_check(source, [tmp_path], strict=True)


def test_strict_mode_evaluates_overrides_in_caller_scope(tmp_path):
    source = tmp_path / "design.slip"
    source.write_text(
        "module child #(param W=8, param N=W*2)(a,q) { "
        "logic [N-1:0] a; logic [N-1:0] q; assign q=a; } "
        "module top #(param W=16)(a,q) { logic [31:0] a; logic [31:0] q; "
        "child #(.W(W)) u { .a(a), .q(q) }; }"
    )
    run_check(source, [], strict=True)


def test_strict_mode_accepts_ascending_dimensions(tmp_path):
    source = tmp_path / "design.slip"
    source.write_text("module m(a,q) { logic [0:7] a; logic [0:7] q; assign q=a; }")
    run_check(source, [], strict=True)
