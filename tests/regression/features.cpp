#include "../test_support.hpp"
#include <algorithm>

namespace {
std::string text(const slip::Result& result) {
    std::string output;
    for (const auto& [name, source] : result.modules) { (void)name; output += source; }
    return output;
}
const std::string stream = "bundle Stream #(param W=8) { output logic [W-1:0] data; output logic valid; input logic ready; } ";
}

TEST_CASE(concatenated_assignment_preserves_all_targets) {
    auto sv = test::module("module m(data,hi,lo) { logic [7:0] data; logic [3:0] hi; logic [3:0] lo; assign {hi,lo}=data; }", "m", true);
    test::contains(sv, "assign {hi, lo} = data;");
    test::contains(sv, "output logic [3:0] hi");
    test::contains(sv, "output logic [3:0] lo");
}
TEST_CASE(indexed_part_selects_support_reads_and_writes) {
    auto sv = test::module("module m(data,base,y) { logic [31:0] data; logic [4:0] base; logic [7:0] y; assign y=data[base +: 8]; }", "m", true);
    test::contains(sv, "data[base +: 8]");
    sv = test::module("module m(a,y) { logic [3:0] a; logic [7:0] y; assign y[3 -: 4]=a; assign y[4 +: 4]=a; }", "m", true);
    test::contains(sv, "y[3 -: 4]");
    test::rejected("module m(a,y) { logic [3:0] a; logic [7:0] y; assign y[0 +: 4]=a; assign y[2 +: 4]=a; }", "E_MULTIPLE_DRIVERS");
}
TEST_CASE(multidimensional_arrays_keep_all_dimensions) {
    auto sv = test::module("module m(a,y) { logic [7:0] a; logic [7:0] y; logic [7:0] mem[0:1][0:2]; assign mem[0][1]=a; assign y=mem[0][1]; }", "m", true);
    test::contains(sv, "mem [0:1][0:2]");
}
TEST_CASE(falling_clock_edge_is_independent_of_reset_edge) {
    auto sv = test::module("module m(clk,rst,d,q) { logic clk; logic rst; logic d; logic q; seq(neg:clk,pos:rst) { if(rst) { q=0; } else { q=d; } } }", "m", true);
    test::contains(sv, "always_ff @(negedge clk or posedge rst)");
}
TEST_CASE(enums_have_named_states_and_explicit_values) {
    auto sv = test::module("module m(clk,en,y) { logic clk; logic en; logic y; enum [1:0] { IDLE, RUN=2, DONE } state; seq(clk) { if(en) { state=RUN; } else { state=IDLE; } } assign y=state==RUN; }", "m", true);
    test::contains(sv, "RUN = 2");
    test::contains(sv, "DONE = RUN + 1");
}
TEST_CASE(shared_struct_types_work_in_ports_and_fields) {
    const auto source = "typedef struct packed { logic [3:0] hi; logic [3:0] lo; } packet_t; module m(a,y) { logic [7:0] a; packet_t y; assign y.hi=a[7:4]; assign y.lo=a[3:0]; }";
    auto sv = test::module(source, "m", true);
    test::contains(sv, "output packet_t y;");
    test::contains(sv, "assign y.hi = a[7:4];");
    test::rejected("typedef struct packed { logic x; } t; module m(a,y) { logic a; t y; assign y.x=a; assign y.x=~a; }", "E_MULTIPLE_DRIVERS");
}
TEST_CASE(rtl_functions_have_local_storage_and_control_flow) {
    auto sv = test::module("function [7:0] invert(logic [7:0] x) { logic [7:0] tmp; tmp=~x; if(x==0) { return 8'hff; } else { return tmp; } } module m(a,y) { logic [7:0] a; logic [7:0] y; assign y=invert(a); }", "m", true);
    test::contains(sv, "function automatic logic [7:0] invert(input logic [7:0] x);");
    test::contains(sv, "return tmp;");
    CHECK(sv.find("input logic tmp") == std::string::npos);
}
TEST_CASE(rtl_functions_require_return_values_on_all_paths) {
    test::rejected("function f(logic x) { if(x) { return 1; } } module m(a,y) { logic a; logic y; assign y=f(a); }", "E_FUNCTION");
}
TEST_CASE(rtl_functions_reject_stateful_or_nonlocal_operations) {
    test::rejected("module m(a,y) { logic a; logic y; function f(logic x) { return a & x; } assign y=f(a); }", "E_FUNCTION", "nonlocal");
    test::rejected("function f(logic x) { x<=0; return x; } module m {}", "E_FUNCTION", "blocking");
    test::rejected("function f(logic x) { logic y; y=x; } module m {}", "E_FUNCTION", "return");
}
TEST_CASE(assertions_generate_checks_and_static_failures_prevent_output) {
    auto sv = test::module("module m(clk,valid) { logic clk; logic valid; static_assert(8>0); seq(clk) { assert(valid, \"valid required\"); } }", "m", true);
    test::contains(sv, "assert (valid) else $error(\"valid required\");");
    test::rejected("module m { static_assert(0, \"bad configuration\"); }", "E_ASSERT", "bad configuration");
    test::rejected("module m(a) { assert(a); }", "E_CONTEXT");
    test::rejected("module m { return 1; }", "E_CONTEXT");
}
TEST_CASE(generated_modules_support_distinct_instance_parameters) {
    const auto source = "module leaf #(param N=2)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b0; } } module m(a,b,c) { logic [1:0] a; logic [3:0] b; logic [3:0] c; leaf u0 {.y(a)}; leaf #(.N(4)) u1 {.y(b)}; leaf #(.N(4)) u2 {.y(c)}; }";
    auto result = slip::compile(source);
    CHECK(result.modules.size() == 3);
    test::contains(result.modules.at("m"), "output logic [3:0] b");
    test::contains(text(result), "assign y[3] = 1'b0;");
    CHECK(slip::compile(source).modules == result.modules);
}
TEST_CASE(specialized_child_freezes_its_parent_control_parameters) {
    auto result = slip::compile("module leaf #(param N=1)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b1; } } module m #(param W=3)(y) { logic [W-1:0] y; leaf #(.N(W)) u {.y}; }");
    test::contains(result.modules.at("m"), "__slip_frozen_W");
    test::contains(text(result), "assign y[2] = 1'b1;");
}
TEST_CASE(specialization_uses_localparams_and_generated_instance_values) {
    auto result = slip::compile("module leaf #(param N=1)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b1; } } module m { localparam COUNT=2; `for (`j=0;`j<COUNT;`j=`j+1) { logic [`j+1:0] result_`j; leaf #(.N(`j+2)) u_`j {.y(result_`j)}; } }");
    CHECK(result.modules.size() == 4);
    test::contains(text(result), "assign y[2] = 1'b1;");
}
TEST_CASE(bundle_ports_have_opposite_master_and_slave_directions) {
    auto sv = test::module(stream + "module m(rx,tx) { slave Stream rx; master Stream tx; assign tx.data=rx.data; assign tx.valid=rx.valid; assign rx.ready=tx.ready; }", "m", true);
    test::contains(sv, "input logic [");
    test::contains(sv, "rx_data");
    test::contains(sv, "output logic rx_ready");
    test::contains(sv, "input logic tx_ready");
    test::contains(sv, "assign tx_data = rx_data;");
}
TEST_CASE(bundle_connections_expand_and_preserve_inferred_interfaces) {
    const auto source = stream +
        "module producer(tx) { master Stream tx; assign tx.data=8'h12; assign tx.valid=1'b1; } "
        "module consumer(rx,y) { slave Stream rx; logic [7:0] y; assign y=rx.data; assign rx.ready=1'b1; } "
        "module m(y) { logic [7:0] y; bus Stream link; producer p {.tx(link)}; consumer c {.rx(link),.y}; }";
    slip::Options options; options.strict = true; options.collect_inspection = true;
    auto result = slip::compile(source, "bundle.slip", options);
    CHECK(result.inspection.at("m").bundles.at("link").size() == 3);
    test::contains(result.modules.at("m"), ".tx_data(link_data)");
    CHECK(result.inspection.at("m").instances.front().connection_details.front().origin == "bundle");
}
TEST_CASE(bundle_contracts_reject_bad_fields_schemas_and_directions) {
    test::rejected(stream + "module m(tx) { master Stream tx; assign tx.missing=0; }", "E_BUNDLE", "unknown field");
    test::rejected(stream + "module m(tx) { slave Stream tx; assign tx.data=0; }", "E_DIRECTION");
    test::rejected(stream + "module m(tx) { bus Stream tx; }", "E_BUNDLE", "role");
    test::rejected(stream + "bundle Other { output logic data; } module leaf(tx) { master Stream tx; assign tx.data=0; assign tx.valid=0; } module m { bus Other link; leaf u {.tx(link)}; }", "E_BUNDLE", "schema mismatch");
}
TEST_CASE(bundle_width_mismatches_are_checked_without_silent_resizing) {
    slip::Options strict; strict.strict = true;
    test::rejected(stream + "module leaf(rx) { slave Stream #(.W(8)) rx; assign rx.ready=1'b1; } module m(tx) { slave Stream #(.W(16)) tx; leaf u {.rx(tx)}; }", "E_SV", {}, strict);
}
TEST_CASE(explicit_scalar_declarations_do_not_inherit_wider_instance_ports) {
    slip::Options strict; strict.strict = true;
    test::rejected("module leaf(a,y) { logic [7:0] a; logic [7:0] y; assign y=a; } module m(a,y) { logic a; logic y; leaf u {.a,.y}; }", "E_SV", {}, strict);
}

TEST_CASE(static_assertions_are_checked_after_instance_parameter_overrides) {
    test::rejected("module cfg #(param W=8) { static_assert(W>0, \"W must be positive\"); } module m { cfg #(.W(0)) u {}; }", "E_SV", "W must be positive");
    auto result = slip::compile("function positive(int x) { return x>0; } module m { static_assert(positive(3)); }");
    test::contains(result.modules.at("m"), "__slip_static_assert_");
}
TEST_CASE(nested_wrappers_specialize_transitive_generation_parameters) {
    auto result = slip::compile("module leaf #(param N=1)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b1; } } module mid #(param W=2)(y) { leaf #(.N(W)) u {.y}; } module m(y) { mid #(.W(4)) u {.y}; }");
    test::contains(result.modules.at("m"), "output logic [3:0] y");
    test::contains(text(result), "assign y[3] = 1'b1;");
}
TEST_CASE(rtl_function_generation_controls_are_specialized) {
    auto result = slip::compile("module leaf #(param N=2)(a,y) { logic [N-1:0] a; logic y; function f(logic [N-1:0] x) { logic p; p=0; `for (`i=0;`i<N;`i=`i+1) { p=p^x[`i]; } return p; } assign y=f(a); } module m(a,y) { logic [3:0] a; logic y; leaf #(.N(4)) u {.a,.y}; }");
    test::contains(text(result), "p = p ^ x[3];");
    test::contains(result.modules.at("m"), "input logic [3:0] a");
}

TEST_CASE(equivalent_parameter_bindings_share_one_specialization) {
    auto result = slip::compile("module leaf #(param BASE=2,param N=BASE+1)(y) { logic [N-1:0] y; `for (`i=0;`i<N;`i=`i+1) { assign y[`i]=1'b0; } } module m(a,b) { logic [3:0] a; logic [3:0] b; leaf #(.N(4)) u {.y(a)}; leaf #(.BASE(2),.N(2+2)) v {.y(b)}; }");
    CHECK(result.modules.size() == 3);
}
TEST_CASE(static_assertions_accept_type_queries_and_wide_truth_values) {
    auto result = slip::compile("typedef struct packed { logic [7:0] data; logic valid; } packet_t; module m { static_assert($bits(packet_t)==9); static_assert(128'hffffffffffffffffffffffffffffffff); }");
    CHECK(result.modules.contains("m"));
    test::rejected("typedef struct packed { logic [7:0] data; logic valid; } packet_t; module m { static_assert($bits(packet_t)==8); }", "E_SV");
}

TEST_CASE(chained_unary_operators_emit_valid_sv_parentheses) {
    auto sv = test::module("module m(a,y) { logic a; logic y; assign y=!!a; }", "m", true);
    test::contains(sv, "!(!a)");
}
TEST_CASE(struct_array_index_feedback_is_detected) {
    test::rejected("typedef struct packed { logic [1:0] value; } packet_t; module m(index) { logic [1:0] index; packet_t memory[0:3]; assign index=memory[index].value; }", "E_COMB_LOOP");
}
TEST_CASE(struct_field_feedback_is_detected) {
    test::rejected("typedef struct packed { logic a; logic b; } packet_t; module m(y) { packet_t p; logic y; assign p.a=p.b; assign p.b=p.a; assign y=p.a; }", "E_COMB_LOOP");
}
