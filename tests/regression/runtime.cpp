#include "../test_support.hpp"
#include <future>
#include <limits>
#include <tuple>

namespace {
const std::string maximum = "int(\"9223372036854775807\")";
const std::string minimum = "int(\"-9223372036854775808\")";
}
TEST_CASE(defun_addition_overflow_and_boundary) {
    test::function_value(maximum + "-1", "9223372036854775806");
    test::rejected(test::function_source(maximum + "+1"), "E_LIMIT", "overflow");
    test::rejected(test::function_source(minimum + "-1"), "E_LIMIT", "overflow");
}
TEST_CASE(defun_subtraction_minimum_operands) {
    test::function_value(minimum + "-" + minimum, "0");
    test::function_value("(-1)-" + minimum, "9223372036854775807");
    test::rejected(test::function_source("0-" + minimum), "E_LIMIT", "overflow");
}
TEST_CASE(defun_multiplication_overflow_and_zero) {
    test::function_value(minimum + "*0", "0");
    test::function_value(minimum + "*1", minimum);
    test::rejected(test::function_source(maximum + "*2"), "E_LIMIT", "overflow");
    test::rejected(test::function_source(minimum + "*(-1)"), "E_LIMIT", "overflow");
}
TEST_CASE(defun_negation_absolute_and_division_overflow) {
    for (const auto& expression : {"-" + minimum, "abs(" + minimum + ")", minimum + "/(-1)"})
        test::rejected(test::function_source(expression), "E_LIMIT", "overflow");
}
TEST_CASE(defun_floor_division_and_remainder) {
    test::function_value("(-7)/3", "-3");
    test::function_value("7/(-3)", "-3");
    test::function_value("(-7)%3", "2");
    test::function_value("7%(-3)", "-2");
    test::function_value(minimum + "%(-1)", "0");
}
TEST_CASE(defun_division_by_zero_has_function_location) {
    auto error = test::rejected(test::function_source("1/0"), "E_FUNCTION", "division by zero");
    CHECK(error.location.file == "regression.slip");
    CHECK(error.location.line == 2);
}
TEST_CASE(defun_integer_conversion_overflow_is_limit_error) {
    test::rejected(test::function_source("int(\"9223372036854775808\")"), "E_LIMIT", "integer");
    test::rejected(test::function_source("int(\"-9223372036854775809\")"), "E_LIMIT", "integer");
    test::rejected(test::function_source("int(\"abc\")"), "E_FUNCTION", "decimal integer");
}
TEST_CASE(defun_shift_and_power_limits) {
    test::function_value("1<<62", "4611686018427387904");
    test::function_value("(-8)>>2", "-2");
    test::rejected(test::function_source("1<<63"), "E_LIMIT");
    test::rejected(test::function_source("1<<(-1)"), "E_LIMIT");
    test::rejected(test::function_source("1>>64"), "E_LIMIT");
    test::rejected(test::function_source("2**63"), "E_LIMIT", "overflow");
}
TEST_CASE(defun_short_circuit_avoids_unselected_errors) {
    test::function_value("0 && (1/0)", "0");
    test::function_value("1 || (1/0)", "1");
    test::function_value("3 if 1 else (1/0)", "3");
}
TEST_CASE(defun_python_and_sv_conditionals_and_boolean_equality) {
    test::function_value("3 if 1 else 1/0", "3");
    test::function_value("1 ? 3 : 1/0", "3");
    test::function_value("((1==1)==1)", "1");
    test::function_value("((1==0)!=0)", "0");
    test::function_value("1 if 0 else 2 if 1 else 3", "2");
}
TEST_CASE(defun_recursion_is_bounded_and_does_not_poison_next_compile) {
    test::rejected("defun f(s):\n    return f(s)\nmodule leaf(p_x) { logic p_x; } module m { leaf u { \"p_(.*)\" => \"v_$f(\\1)\" }; }", "E_LIMIT", "depth");
    test::function_value("3+4", "7");
}
TEST_CASE(defun_padding_string_limit) {
    test::rejected(test::function_source("s.ljust(1000001,\"a\")"), "E_LIMIT", "string size");
    test::function_value("len(s.ljust(1000000,\"a\"))", "1000000");
}
TEST_CASE(defun_replace_join_concat_string_limits) {
    test::rejected(test::function_source("s.ljust(1001,\"a\").replace(\"a\",s.ljust(1001,\"b\"))"), "E_LIMIT");
    test::rejected(test::function_source("concat(s.ljust(600000,\"a\"),s.ljust(600000,\"b\"))"), "E_LIMIT");
    test::rejected(test::function_source("s.ljust(600000,\"a\").join(\"a_b_c\".split(\"_\"))"), "E_LIMIT");
}
TEST_CASE(defun_replace_empty_needle_and_zero_count) {
    test::function_value("\"abc\".replace(\"\", \"-\", 2)", "\"-a-bc\"");
    test::function_value("\"abc\".replace(\"\", \"-\")", "\"-a-b-c-\"");
    test::function_value("\"banana\".replace(\"a\", \"x\", 0)", "\"banana\"");
}
TEST_CASE(defun_split_rsplit_limits_and_whitespace) {
    test::function_value("\"|\".join(\"a::b::c\".rsplit(\"::\", 1))", "\"a::b|c\"");
    test::function_value("\"|\".join(\"  a  b  \".split())", "\"a|b\"");
    test::function_value("\"|\".join(\"a::b::c\".split(\"::\", 1))", "\"a|b::c\"");
}
TEST_CASE(defun_splitlines_keepends_and_negative_slice) {
    test::function_value("\"|\".join(\"a\\r\\nb\\n\".splitlines(1))", "\"a\\r\\n|b\\n\"");
    test::function_value("\"abcdef\"[-4:-1]", "\"cde\"");
}
TEST_CASE(defun_string_search_bounds_and_signed_zero_fill) {
    test::function_value("\"banana\".find(\"na\", -3)", "4");
    test::function_value("\"banana\".count(\"\")", "7");
    test::function_value("\"-42\".zfill(5)", "\"-0042\"");
}
TEST_CASE(meta_iteration_limit_accepts_exact_boundary) {
    slip::Options options; options.max_meta_iterations = 3;
    const auto source = "module m { `for (`i=0;`i<3;`i=`i+1) { logic q_`i; } }";
    CHECK(slip::compile(source, "limit.slip", options).modules.size() == 1);
    options.max_meta_iterations = 2;
    test::rejected(source, "E_LIMIT", "iteration", options);
}
TEST_CASE(meta_zero_iteration_and_descending_range) {
    const auto zero = test::module("module m { `for (`i=3;`i<3;`i=`i+1) { logic never_`i; } logic kept; }");
    CHECK(zero.find("never_") == std::string::npos);
    CHECK(zero.find("kept") != std::string::npos);
    const auto descending = test::module("module m { `for (`i=2;`i>=0;`i=`i-1) { logic bit_`i; } }");
    for (const auto* name : {"bit_2", "bit_1", "bit_0"}) test::contains(descending, name);
}
TEST_CASE(meta_iteration_limit_counts_nested_and_sibling_loops) {
    slip::Options options; options.max_meta_iterations = 5;
    test::rejected("module m { `for (`i=0;`i<2;`i=`i+1) { `for (`j=0;`j<2;`j=`j+1) { logic q_`i_`j; } } }", "E_LIMIT", "iteration", options);
    options.max_meta_iterations = 3;
    test::rejected("module m { `for (`i=0;`i<2;`i=`i+1) { logic a_`i; } `for (`j=0;`j<2;`j=`j+1) { logic b_`j; } }", "E_LIMIT", "iteration", options);
}
TEST_CASE(expanded_statement_limit_accepts_exact_boundary) {
    slip::Options options; options.max_expanded_statements = 2;
    CHECK(slip::compile("module m { logic a; logic b; }", "limit.slip", options).modules.size() == 1);
    test::rejected("module m { logic a; logic b; logic c; }", "E_LIMIT", "statement", options);
}
TEST_CASE(include_depth_limit_and_include_cycle) {
    test::Directory directory;
    directory.write("a.slip", "include \"b.slip\"; module a {}\n");
    directory.write("b.slip", "include \"c.slip\"; module b {}\n");
    directory.write("c.slip", "include \"a.slip\"; module c {}\n");
    slip::Options options; options.max_include_depth = 2;
    CHECK(slip::compile_file(directory.path()/"a.slip", options).modules.size() == 3);
    options.max_include_depth = 1;
    test::error([&] { slip::compile_file(directory.path()/"a.slip", options); }, "E_LIMIT", "include");
}
TEST_CASE(meta_integer_limit_preserves_wide_hardware_literals) {
    test::rejected("module m { `if(64'h8000000000000000) { logic a; } }", "E_LIMIT", "64-bit");
    test::module("module m(y) { logic [127:0] y; assign y=128'hffffffffffffffffffffffffffffffff; }");
}
TEST_CASE(parser_limits_deep_parentheses_before_stack_exhaustion) {
    std::string source(10000, '('); source += "a"; source += std::string(10000, ')');
    test::error([&] { slip::parse_expression(source); }, "E_LIMIT");
}
TEST_CASE(ast_depth_limit_accepts_exact_boundary) {
    auto expr=slip::expression(slip::Location{},slip::Identifier{"a"});
    for(unsigned depth=1;depth<256;++depth) expr=slip::expression(slip::Location{},slip::Unary{"~",expr});
    CHECK(expr->depth==256);
    test::error([&] { slip::expression(slip::Location{},slip::Unary{"~",expr}); },"E_LIMIT","depth");
}
TEST_CASE(source_token_limit_is_enforced_before_parsing) {
    std::string source(1000001,';');
    test::error([&] { slip::parse(source,"tokens.slip"); },"E_LIMIT","token");
}
TEST_CASE(regex_pattern_work_and_size_are_bounded) {
    const auto source = "module leaf(p_x) { logic p_x; } module m { leaf u { \"" + std::string(65537,'a') + "\" => \"x\" }; }";
    test::rejected(source, "E_LIMIT", "pattern size");
    test::rejected("module leaf(p_x) { logic p_x; } module m { leaf u { \"(\" => \"x\" }; }", "E_REGEX", "invalid regex");
}
TEST_CASE(regex_backtracking_budget_is_enforced) {
    const auto port="p_"+std::string(80,'a')+"b";
    test::rejected("module leaf("+port+") { logic "+port+"; } module m { leaf u { \"(*NO_AUTO_POSSESS)(*NO_START_OPT)p_(a+)+$\" => \"x\" }; }", "E_REGEX", "resource limits");
}
TEST_CASE(owned_ast_survives_input_and_unit_destruction) {
    slip::ExprPtr value;
    {
        std::string input = "module m(a,y) { assign y=a+1; }";
        auto unit = slip::parse(input, "owned.slip");
        value = std::get<slip::Assignment>(unit.modules[0].body[0].node).value;
        input.assign(100000, 'x');
    }
    CHECK(slip::to_sv(value) == "a + 1");
    CHECK(value->loc.file == "owned.slip");
}
TEST_CASE(compilation_result_survives_ip_files_and_options_destruction) {
    slip::Result result;
    {
        test::Directory directory;
        directory.write("ip.sv", "module ext(input logic [7:0] a, output logic [7:0] y); assign y=a; endmodule");
        slip::Options options; options.ip_dirs = {directory.path()};
        result = slip::compile("module m(a,y) { ext u {.a,.y}; }", "owned.slip", options);
    }
    test::contains(result.modules.at("m"), "output logic [7:0] y");
    test::Directory output;
    slip::write_outputs(result, output.path());
    CHECK(std::filesystem::file_size(output.path()/"m.sv") > 0);
}
TEST_CASE(ip_type_parameters_work_and_unconnected_interfaces_report_diagnostics) {
    test::Directory directory;
    directory.write("unit.sv", "module typed #(parameter type T=logic)(input T a); endmodule\ninterface bus_if; logic a; modport mp(input a); endinterface module ext(bus_if.mp bus); endmodule\n");
    slip::Options options; options.ip_dirs = {directory.path()};
    CHECK(slip::compile("module top {}", "top.slip", options).modules.contains("top"));
    CHECK(slip::compile("module top { typed u {.a(1'b0)}; }", "top.slip", options).modules.contains("top"));
    const auto error = test::error([&] { slip::compile("module top { ext u {}; }", "top.slip", options); }, "E_CONNECTION", "unconnected interface port");
    CHECK(error.location.file == "top.slip");
}
TEST_CASE(filelist_cycles_and_missing_sources_have_io_diagnostics) {
    test::Directory directory;
    const auto root = directory.write("root.f", "-f nested/child.f\n");
    directory.write("nested/child.f", "-f ../root.f\n");
    slip::Options options; options.filelists = {root};
    test::error([&] { slip::compile("module top {}", "top.slip", options); }, "E_FILELIST", "circular");

    const auto missing_list = directory.write("missing.f", "missing.sv\n");
    options.filelists = {missing_list};
    auto error = test::error([&] { slip::compile("module top {}", "top.slip", options); }, "E_IO", "regular file");
    CHECK(error.location.file.find("missing.sv") != std::string::npos);
}
TEST_CASE(concurrent_compilers_isolate_functions_ip_and_constant_caches) {
    test::Directory directory;
    std::vector<std::future<std::string>> jobs;
    for (unsigned i=0; i<12; ++i) {
        const auto tag=std::to_string(i), width=std::to_string(i+1);
        const auto file=directory.write(tag+"/ip.sv", "module ext(input logic ["+width+"-1:0] p_x, output logic ["+width+"-1:0] y); assign y=p_x; endmodule");
        jobs.push_back(std::async(std::launch::async,[file,tag] {
            slip::Options options; options.ip_dirs={file.parent_path()};
            const auto source="defun f(s):\n    return \"bus"+tag+"\"\nmodule m(y) { ext u { .y, \"p_(.*)\" => \"$f(\\1)\" }; }";
            std::string output;
            for(unsigned repeat=0;repeat<5;++repeat) {
                auto current=slip::compile(source,"thread"+tag+".slip",options).modules.at("m");
                if (!output.empty()) CHECK(output==current);
                output=std::move(current);
            }
            return output;
        }));
    }
    for (unsigned i=0; i<jobs.size(); ++i) {
        const auto output=jobs[i].get();
        test::contains(output,"logic ["+std::to_string(i)+":0] bus"+std::to_string(i));
        test::contains(output,"output logic ["+std::to_string(i)+":0] y");
    }
}
