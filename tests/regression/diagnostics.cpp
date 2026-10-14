#include "../test_support.hpp"

TEST_CASE(lexical_error_has_exact_source_location) {
    auto error = test::rejected("module m {\n    \\bad\n}", "E_LEX");
    CHECK(error.location.file == "regression.slip");
    CHECK(error.location.line == 2);
    CHECK(error.location.column == 5);
    test::contains(error.what(), "regression.slip:2:5");
}
TEST_CASE(parse_error_has_exact_source_location) {
    auto error = test::rejected("module m {\n    assign y = ;\n}", "E_PARSE");
    CHECK(error.location.line == 2);
    CHECK(error.location.column == 16);
    test::contains(error.message, "unexpected token");
}
TEST_CASE(crlf_source_keeps_line_and_column_locations) {
    const auto source = "module m {\r\n    assign y = ;\r\n}";
    auto error = test::rejected(source, "E_PARSE");
    CHECK(error.location.line == 2);
    CHECK(error.location.column == 16);
}
TEST_CASE(duplicate_declaration_reports_second_declaration) {
    auto error = test::rejected("module m {\n    logic a;\n    logic a;\n}", "E_DUPLICATE", "a");
    CHECK(error.location.line == 3);
    CHECK(error.location.column == 5);
}
TEST_CASE(unknown_module_reports_instance_location) {
    auto error = test::rejected("module m {\n    missing u {};\n}", "E_MODULE", "missing");
    CHECK(error.location.line == 2);
    CHECK(error.location.column == 5);
}
TEST_CASE(unknown_port_is_distinct_from_unknown_module) {
    auto error = test::rejected("module leaf(a,y) { assign y=a; }\nmodule m(a,y) {\n    leaf u {.typo(a),.y};\n}", "E_CONNECTION", "typo");
    CHECK(error.location.line == 3);
}
TEST_CASE(include_error_retains_included_filename) {
    test::Directory directory;
    auto child = directory.write("child.slip", "module m {\n    assign y=;\n}\n");
    auto top = directory.write("top.slip", "include \"child.slip\";\n");
    auto error = test::error([&] { slip::compile_file(top); }, "E_PARSE");
    CHECK(error.location.file == child.string());
    CHECK(error.location.line == 2);
    CHECK(error.location.column == 14);
}
TEST_CASE(undefined_constant_and_four_state_control_are_diagnosed) {
    test::rejected("module m { `if (NOT_DEFINED) { logic a; } }", "E_CONSTANT");
    test::rejected("module m { `if (8'hxz) { logic a; } }", "E_CONSTANT", "known integer");
}
TEST_CASE(unsupported_nested_process_reports_context) {
    auto error = test::rejected("module m {\n    comb {\n        seq(clk) { y=a; }\n    }\n}", "E_CONTEXT");
    CHECK(error.location.line == 3);
    CHECK(error.location.column == 9);
}

TEST_CASE(backend_error_maps_to_original_assignment) {
    auto error = test::rejected("module m(a,y) {\n    logic a;\n    logic y;\n    assign y = missing(a);\n}\n", "E_SV", "missing");
    CHECK(error.location.file == "regression.slip");
    CHECK(error.location.line == 4);
    CHECK(error.location.column == 5);
    CHECK(error.message.find("m.sv") == std::string::npos);
}
TEST_CASE(backend_error_maps_to_procedural_statement) {
    auto error = test::rejected("module m(a,y) {\n    logic a; logic y;\n    comb {\n        y = missing(a);\n    }\n}\n", "E_SV", "missing");
    CHECK(error.location.line == 4);
    CHECK(error.location.column == 9);
}
TEST_CASE(backend_error_retains_included_source_filename) {
    test::Directory directory;
    auto child = directory.write("child.slip", "module m(a,y) {\n    logic a; logic y;\n    assign y = missing(a);\n}\n");
    auto top = directory.write("top.slip", "include \"child.slip\";\n");
    auto error = test::error([&] { slip::compile_file(top); }, "E_SV", "missing");
    CHECK(error.location.file == child.string());
    CHECK(error.location.line == 3);
    CHECK(error.location.column == 5);
}
TEST_CASE(width_diagnostics_map_to_source_and_loop_bindings) {
    const auto source = "module m(y) {\n    logic [1:0] y;\n    `for (`i=0; `i<2; `i=`i+1) {\n        assign y[`i] = 300;\n    }\n}\n";
    auto result = slip::compile(source, "loop.slip");
    CHECK(result.warnings.size() == 2);
    for (const auto& warning : result.warnings) {
        CHECK(warning.code == "W_WIDTH");
        CHECK(warning.loc.file == "loop.slip");
        CHECK(warning.loc.line == 4);
        CHECK(warning.loc.column == 9);
        CHECK(warning.loc.expansion == "i=0" || warning.loc.expansion == "i=1");
    }
    slip::Options options; options.widths_as_errors = true;
    auto error = test::rejected(source, "E_SV", {}, options);
    CHECK(error.location.line == 4);
    CHECK(error.location.expansion == "i=0");
}
TEST_CASE(implicit_signal_warning_reports_first_use_and_spelling) {
    auto result = slip::compile("module m(y) {\n    logic data; logic y;\n    assign y = dtaa;\n}\n", "typo.slip");
    CHECK(result.warnings.size() == 2);
    const auto& warning = result.warnings.front();
    CHECK(warning.code == "W_IMPLICIT");
    CHECK(warning.loc.file == "typo.slip");
    CHECK(warning.loc.line == 3);
    CHECK(warning.loc.column == 16);
    test::contains(warning.message, "defaults to 1-bit");
    test::contains(warning.message, "did you mean 'data'?");
    CHECK(result.warnings.back().code == "W_UNDRIVEN");
}
TEST_CASE(implicit_signal_ambiguous_spelling_has_no_suggestion) {
    auto result = slip::compile("module m(y) { logic data; logic date; logic y; assign y=dat; }");
    CHECK(result.warnings.size() == 2);
    CHECK(result.warnings.front().message.find("did you mean") == std::string::npos);
}
TEST_CASE(strict_implicit_error_reports_identifier_instead_of_module) {
    slip::Options options; options.no_implicit = true;
    auto error = test::rejected("module m(y) {\n    logic y;\n    assign y = typo;\n}\n", "E_IMPLICIT", "typo", options);
    CHECK(error.location.line == 3);
    CHECK(error.location.column == 16);
}

TEST_CASE(ip_diagnostics_do_not_use_generated_module_map_with_same_basename) {
    test::Directory directory;
    auto ip = directory.write("ip/m.sv", "module leaf(input logic a, output logic y);\n\n    assign y = missing(a);\nendmodule\n");
    slip::Options options; options.ip_dirs.push_back(directory.path() / "ip");
    auto error = test::error([&] { slip::compile("module m(a,y) { leaf u {.a,.y}; }", "original.slip", options); }, "E_SV", "missing");
    CHECK(std::filesystem::path(error.location.file).filename() == ip.filename());
    CHECK(error.location.file != "original.slip");
    CHECK(error.location.line == 3);
}
TEST_CASE(expanded_localparam_error_keeps_nested_loop_bindings) {
    const auto source = "module m {\n    `for (`i=0; `i<1; `i=`i+1) {\n        `for (`j=0; `j<1; `j=`j+1) {\n            localparam P_`i_`j = missing(1);\n        }\n    }\n}\n";
    auto error = test::rejected(source, "E_SV", "missing");
    CHECK(error.location.file == "regression.slip");
    CHECK(error.location.line == 4);
    CHECK(error.location.expansion == "i=0, j=0");
}
