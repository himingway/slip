#include "../test_support.hpp"
#include <algorithm>

namespace {
std::size_t count(const slip::Result& result, std::string_view code) {
    return std::count_if(result.warnings.begin(), result.warnings.end(),
                         [&](const auto& warning) { return warning.code == code; });
}
const slip::Diagnostic& warning(const slip::Result& result, std::string_view code) {
    const auto found = std::find_if(result.warnings.begin(), result.warnings.end(),
                                  [&](const auto& value) { return value.code == code; });
    CHECK(found != result.warnings.end());
    return *found;
}
} // namespace

TEST_CASE(undriven_internal_signal_warns_at_original_declaration) {
    auto result = slip::compile("module m(y) {\n    logic y;\n    logic forgotten;\n    assign y = forgotten;\n}\n", "lint.slip");
    CHECK(count(result, "W_UNDRIVEN") == 1);
    const auto& diag = warning(result, "W_UNDRIVEN");
    CHECK(diag.loc.file == "lint.slip");
    CHECK(diag.loc.line == 3);
    test::contains(diag.message, "forgotten");
}
TEST_CASE(input_ports_and_instance_outputs_supply_drivers) {
    const auto source = "module leaf(a,y) { assign y=a; } module m(a,y) { logic link; leaf u {.a,.y(link)}; assign y=link; }";
    auto result = slip::compile(source);
    CHECK(count(result, "W_UNDRIVEN") == 0);
}
TEST_CASE(initial_block_supplies_internal_signal_driver) {
    auto result = slip::compile("module m(y) { logic y; logic initialized; initial { initialized=1'b0; } assign y=initialized; }");
    CHECK(count(result, "W_UNDRIVEN") == 0);
}
TEST_CASE(incomplete_comb_branch_warns_about_latch_with_source_location) {
    auto result = slip::compile("module m(sel,a,y) {\n    logic sel; logic a; logic y;\n    comb {\n        if (sel) { y=a; }\n    }\n}\n", "latch.slip");
    CHECK(count(result, "W_LATCH") == 1);
    const auto& diag = warning(result, "W_LATCH");
    CHECK(diag.loc.file == "latch.slip");
    CHECK(diag.loc.line == 4);
    test::contains(diag.message, "y");
    test::contains(diag.message, "default value");
}
TEST_CASE(comb_defaults_and_complete_branches_avoid_latch_warnings) {
    for (auto body : {"y=0; if(sel) { y=a; }", "if(sel) { y=a; } else { y=0; }"}) {
        auto result = slip::compile("module m(sel,a,y) { logic sel; logic a; logic y; comb { " + std::string(body) + " } }");
        CHECK(count(result, "W_LATCH") == 0);
    }
}
TEST_CASE(exhaustive_binary_case_does_not_require_default_for_lint) {
    auto result = slip::compile("module m(sel,y) { logic [1:0] sel; logic y; comb { case(sel) { 0:y=0; 1:y=1; 2:y=0; 3:y=1; } } }");
    CHECK(count(result, "W_LATCH") == 0);
}
TEST_CASE(partial_bit_assignments_are_checked_for_latches) {
    auto result = slip::compile("module m(sel,a,y) { logic sel; logic [3:0] a; logic [7:0] y; comb { if(sel) { y[3:0]=a; } else { y[7:4]=a; } } }");
    CHECK(count(result, "W_LATCH") > 0);
    result = slip::compile("module m(sel,a,y) { logic sel; logic [3:0] a; logic [7:0] y; comb { y=0; if(sel) { y[3:0]=a; } else { y[7:4]=a; } } }");
    CHECK(count(result, "W_LATCH") == 0);
}
TEST_CASE(sequential_enable_is_not_reported_as_a_latch) {
    auto result = slip::compile("module m(clk,en,a,y) { logic clk; logic en; logic a; logic y; seq(clk) { if(en) { y=a; } } }");
    CHECK(count(result, "W_LATCH") == 0);
}
TEST_CASE(lint_warnings_are_not_promoted_by_strict_mode) {
    slip::Options strict; strict.strict = true;
    auto result = slip::compile("module m(sel,a,y) { logic sel; logic a; logic y; comb { if(sel) { y=a; } } }", "lint.slip", strict);
    CHECK(count(result, "W_LATCH") == 1);
}
TEST_CASE(unused_regex_rules_warn_for_no_matches_and_shadowing) {
    for (auto connections : {".a,.y,\"typo_(.*)\" => \"unused_\\1\"", "\"(.*)\" => \"\\1\",\"(.*)\" => \"shadow_\\1\""}) {
        auto result = slip::compile("module leaf(a,y) { assign y=a; } module m(a,y) { leaf u { " + std::string(connections) + " }; }");
        CHECK(count(result, "W_REGEX_UNUSED") == 1);
        test::contains(warning(result, "W_REGEX_UNUSED").message, "connected no ports");
    }
}
TEST_CASE(omitted_output_warns_but_intentional_dangling_connection_is_silent) {
    auto result = slip::compile("module leaf(a,y) { assign y=a; } module m(a) { leaf u {.a}; }");
    CHECK(count(result, "W_UNCONNECTED") == 1);
    test::contains(warning(result, "W_UNCONNECTED").message, ".y(_)");
    result = slip::compile("module leaf(a,y) { assign y=a; } module m(a) { leaf u {.a,.y(_)}; }");
    CHECK(count(result, "W_UNCONNECTED") == 0);
}
TEST_CASE(lint_ignores_vendor_ip_but_recognizes_its_output_driver) {
    test::Directory directory;
    directory.write("ip/leaf.sv", "module leaf(input logic a, input logic en, output logic y); always_comb if(en) y=a; endmodule");
    slip::Options options; options.ip_dirs.push_back(directory.path() / "ip");
    auto result = slip::compile("module m(a,en,y) { logic driven; leaf u {.a,.en,.y(driven)}; assign y=driven; }", "lint.slip", options);
    CHECK(count(result, "W_LATCH") == 0);
    CHECK(count(result, "W_UNDRIVEN") == 0);
}
