#include "../test_support.hpp"

TEST_CASE(signed_ports_keep_width_and_direction) {
    const auto sv = test::module("module m(a,y) { signed logic [7:0] a; signed logic [15:0] y; assign y=a; }");
    test::contains(sv, "input logic signed [7:0] a");
    test::contains(sv, "output logic signed [15:0] y");
}
TEST_CASE(ascending_dimensions_are_preserved) {
    const auto sv = test::module("module m(a[0:7],y[0:7]) { assign y=a; }", "m", true);
    test::contains(sv, "input logic [0:7] a");
    test::contains(sv, "output logic [0:7] y");
}
TEST_CASE(width_loss_warning_and_strict_error) {
    const auto source = "module m(a,y) { logic [15:0] a; logic [7:0] y; assign y=a; }";
    auto result = slip::compile(source);
    CHECK(result.warnings.size() == 1);
    CHECK(result.warnings[0].code == "W_WIDTH");
    slip::Options strict; strict.strict = true;
    test::rejected(source, "E_SV", {}, strict);
}
TEST_CASE(fitting_unsized_constant_is_silent) {
    auto result = slip::compile("module m(y) { logic [7:0] y; assign y=255; }");
    CHECK(result.warnings.empty());
    test::contains(result.modules.at("m"), "assign y = 255;");
}
TEST_CASE(signed_shift_and_cast_are_preserved) {
    const auto sv = test::module("module m(a,y) { signed logic [7:0] a; signed logic [7:0] y; assign y=signed'(a) >>> 2; }");
    test::contains(sv, "signed'(a) >>> 2");
}
TEST_CASE(assignment_context_preserves_carry) {
    const auto sv = test::module("module m(narrow,wide) { logic [7:0] narrow; logic [15:0] wide; assign narrow=(8'hff+8'h01)>>1; assign wide=(8'hff+8'h01)>>1; }");
    test::contains(sv, "assign narrow = (8'hff + 8'h01) >> 1;");
    test::contains(sv, "assign wide = (8'hff + 8'h01) >> 1;");
}
TEST_CASE(parameter_override_uses_parent_scope) {
    const auto sv = test::module("module leaf #(param W=8)(a,y) { logic [W-1:0] a; logic [W-1:0] y; assign y=a; } module m #(param W=16)(a,y) { leaf #(.W(W)) u {.a,.y}; }");
    test::contains(sv, "input logic [(W) - 1:0] a");
    test::contains(sv, ".W(W)");
}
TEST_CASE(parameter_defaults_depend_on_overridden_parameter) {
    const auto sv = test::module("module leaf #(param W=8,param N=W+2)(a,y) { logic [N-1:0] a; logic [N-1:0] y; assign y=a; } module m(a,y) { leaf #(.W(14)) u {.a,.y}; }");
    test::contains(sv, "output logic [15:0] y");
}
TEST_CASE(parameter_overrides_resolve_forward_references_in_any_order) {
    const auto sv = test::module("module leaf #(param W=8,param N=W+2)(a,y) { logic [N-1:0] a; logic [N-1:0] y; assign y=a; } module m #(param BASE=12)(a,y) { leaf #(.N(BASE+1),.W(BASE)) u {.a,.y}; }");
    test::contains(sv, "output logic [(BASE + 1) - 1:0] y");
    test::contains(sv, ".N(BASE + 1),");
    test::contains(sv, ".W(BASE)");
}
TEST_CASE(localparam_width_resolves_in_parent) {
    const auto sv = test::module("module leaf #(param W=8)(a,y) { localparam N=W+1; logic [N-1:0] a; logic [N-1:0] y; assign y=a; } module m(a,y) { leaf #(.W(15)) u {.a,.y}; }");
    test::contains(sv, "input logic [15:0] a");
}
TEST_CASE(transitive_metaprogram_parameter_is_frozen) {
    test::rejected("module leaf #(param BASE=2,param N=BASE+1)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b0; } } module m(y) { leaf #(.BASE(4)) u {.y}; }", "E_PARAMETER", "controls expanded structure");
}
TEST_CASE(localparam_and_unknown_parameter_overrides_are_rejected) {
    for (auto name : {"N", "TYPO"}) {
        test::rejected("module leaf(a,y) { localparam N=8; assign y=a; } module m(a,y) { leaf #(." +
            std::string(name) + "(16)) u {.a,.y}; }", "E_PARAMETER");
    }
}
TEST_CASE(interface_propagates_through_reordered_wrappers) {
    const auto sv = test::module("module m(a,y) { mid u {.a,.y}; } module mid(a,y) { leaf #(.W(32)) u {.a,.y}; } module leaf #(param W=8)(a,y) { logic [W-1:0] a; logic [W-1:0] y; assign y=a; }");
    test::contains(sv, "output logic [31:0] y");
}
TEST_CASE(overlapping_partial_drivers_are_rejected) {
    test::rejected("module m(a,b,y) { logic [3:0] a; logic [3:0] b; logic [7:0] y; assign y[3:0]=a; assign y[5:2]=b; }", "E_MULTIPLE_DRIVERS", "y");
}
TEST_CASE(disjoint_partial_drivers_are_allowed) {
    test::module("module m(a,b,y) { logic [3:0] a; logic [3:0] b; logic [7:0] y; assign y[3:0]=a; assign y[7:4]=b; }");
}
TEST_CASE(array_element_drivers_are_distinct) {
    test::module("module m(a,y) { logic [7:0] a; logic [7:0] y; logic [7:0] data[0:1]; assign data[0]=a; assign data[1]=~a; assign y=data[0]^data[1]; }");
    test::rejected("module m(a,y) { logic [7:0] a; logic [7:0] y; logic [7:0] data[0:1]; assign data[0]=a; assign data[0]=~a; assign y=data[0]; }", "E_MULTIPLE_DRIVERS");
}
TEST_CASE(unpacked_element_packed_slices_have_precise_driver_overlap) {
    test::module("module m(a,b,y) { logic [3:0] a; logic [3:0] b; logic [7:0] y; logic [7:0] data[0:1]; assign data[0][3:0]=a; assign data[0][7:4]=b; assign y=data[0]; }");
    test::rejected("module m(a,b,y) { logic [3:0] a; logic [3:0] b; logic [7:0] y; logic [7:0] data[0:1]; assign data[0][3:0]=a; assign data[0][2:1]=b; assign y=data[0]; }", "E_MULTIPLE_DRIVERS", "data");
}
TEST_CASE(feedback_through_distinct_unpacked_elements_is_detected) {
    test::rejected("module m(y) { logic [7:0] y; logic [7:0] data[0:1]; assign data[0][0]=data[1][0]; assign data[1][0]=data[0][0]; assign y=data[0][0]; }", "E_COMB_LOOP", "data");
}
TEST_CASE(dynamic_index_driver_conflicts_conservatively) {
    test::rejected("module m(a,i,y) { logic a; logic [1:0] i; logic [3:0] y; assign y[i]=a; assign y[0]=~a; }", "E_MULTIPLE_DRIVERS");
}
TEST_CASE(instance_outputs_overlap_with_process_storage) {
    test::rejected("module leaf(a,y) { assign y=a; } module m(a,y) { leaf u {.a,.y}; comb { y=a; } }", "E_MULTIPLE_DRIVERS");
}
TEST_CASE(instance_output_dynamic_selection_is_rejected) {
    test::rejected("module leaf(a,y) { assign y=a; } module m(a,i,y) { logic a; logic [1:0] i; logic [3:0] y; leaf u {.a,.y(y[i])}; }", "E_SV", "non-constant");
}
TEST_CASE(instance_output_fixed_selection_is_allowed) {
    const auto sv = test::module("module leaf(a,y) { assign y=a; } module m(a,y) { logic a; logic [3:0] y; leaf u {.a,.y(y[1])}; }");
    test::contains(sv, "output logic [3:0] y");
    test::contains(sv, ".y(y[1])");
}
TEST_CASE(control_dependency_feedback_is_rejected) {
    test::rejected("module m(y) { comb { if(y) y=1'b0; else y=1'b1; } }", "E_COMB_LOOP", "y");
    test::rejected("module m(y) { comb { case(y) { 0: y=1'b1; default: y=1'b0; } } }", "E_COMB_LOOP");
}
TEST_CASE(initialized_accumulator_and_indexed_chain_are_allowed) {
    test::module("module m(a,y) { logic [7:0] a; logic [7:0] y; comb { y=0; for(i=0;i<4;i=i+1) { y=y+a; } } }");
    test::module("module m(a,y) { logic [7:0] a; logic [7:0] y; logic [7:0] data[0:2]; assign data[0]=a; assign data[1]=data[0]; assign data[2]=data[1]; assign y=data[2]; }");
}
TEST_CASE(indexed_feedback_is_rejected) {
    test::rejected("module m(y) { logic [7:0] y; logic [7:0] data[0:1]; assign data[0]=data[1]; assign data[1]=data[0]; assign y=data[0]; }", "E_COMB_LOOP", "data");
}
TEST_CASE(seq_conversion_reports_prior_write) {
    auto result = slip::compile("module m(clk,a,y) { logic clk; logic [7:0] a; logic [7:0] y; seq(clk) { y=0; y=y+a; } }");
    CHECK(result.warnings.size() == 1);
    CHECK(result.warnings[0].code == "W_SEQ_CONVERSION");
    test::contains(result.modules.at("m"), "y <= y + a;");
}
