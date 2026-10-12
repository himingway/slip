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
