#include "../test_support.hpp"

#include <cstdlib>
#include <algorithm>

namespace {
std::string read(const std::filesystem::path& file) {
    std::ifstream stream(file, std::ios::binary);
    std::ostringstream out; out << stream.rdbuf(); return out.str();
}
}
TEST_CASE(outputs_preserve_timestamps_and_clean_only_unchanged_owned_files) {
    test::Directory directory;
    auto result = slip::compile("module a(x,y) { assign y=x; } module b(x,y) { a u {.x,.y}; }", "input.slip");
    directory.write("user.sv", "// handwritten\n");
    slip::write_outputs(result, directory.path());
    const auto old_time = std::filesystem::file_time_type::clock::now() - std::chrono::hours(24);
    for (const auto& entry : std::filesystem::directory_iterator(directory.path())) std::filesystem::last_write_time(entry, old_time);
    slip::write_outputs(result, directory.path());
    CHECK(std::filesystem::last_write_time(directory.path()/"a.sv") == old_time);
    CHECK(std::filesystem::last_write_time(directory.path()/"sources.f") == old_time);
    CHECK(std::filesystem::last_write_time(directory.path()/".slip-manifest") == old_time);
    CHECK(std::filesystem::last_write_time(directory.path()/".slip-build-stamp") > old_time);
    const auto filelist = read(directory.path()/"sources.f");
    CHECK(filelist.find("a.sv") < filelist.find("b.sv"));
    result = slip::compile("module a(x,y) { assign y=~x; }", "input.slip");
    slip::write_outputs(result, directory.path());
    CHECK(!std::filesystem::exists(directory.path()/"b.sv"));
    CHECK(read(directory.path()/"user.sv") == "// handwritten\n");
    directory.write("a.sv", "// edited generated file\n");
    result = slip::compile("module c(x,y) { assign y=x; }", "input.slip");
    slip::write_outputs(result, directory.path());
    CHECK(read(directory.path()/"a.sv") == "// edited generated file\n");
    CHECK(read(directory.path()/"sources.f").find("a.sv") == std::string::npos);
}
TEST_CASE(outputs_reject_modified_destinations_and_symlinks_before_publishing) {
    test::Directory directory;
    auto result = slip::compile("module m(x,y) { assign y=x; }", "input.slip");
    slip::write_outputs(result, directory.path());
    directory.write("m.sv", "// user edit\n");
    result = slip::compile("module a(x,y) { assign y=x; } module m(x,y) { assign y=~x; }", "input.slip");
    test::error([&] { slip::write_outputs(result, directory.path()); }, "E_OUTPUT_MODIFIED");
    CHECK(!std::filesystem::exists(directory.path()/"a.sv"));
    std::filesystem::remove(directory.path()/"m.sv");
    const auto target = directory.write("target.txt", "do not overwrite");
    std::filesystem::create_symlink(target, directory.path()/"m.sv");
    test::error([&] { slip::write_outputs(result, directory.path()); }, "E_IO", "symlink");
    CHECK(read(target) == "do not overwrite");
    CHECK(!std::filesystem::exists(directory.path()/".slip-lock"));
}
TEST_CASE(output_metadata_tracks_includes_ip_headers_filelists_and_loop_origins) {
    test::Directory directory;
    const auto header = directory.write("ip/width.svh", "`define W 4\n");
    const auto ip = directory.write("ip/leaf.sv", "`include \"width.svh\"\nmodule leaf(input logic [`W-1:0] a, output logic [`W-1:0] y); assign y=a; endmodule\n");
    const auto list = directory.write("sources.f", "+incdir+ip\nip/leaf.sv\n");
    const auto included = directory.write("helper.slip", "module helper(a,y) { assign y=a; }\n");
    const auto source = directory.write("top.slip", "include \"helper.slip\";\nmodule top(a,y) { logic [3:0] a; logic [3:0] y; leaf u {.a,.y}; }\nmodule bits(a,y) { logic [1:0] a; logic [1:0] y; `for (`i=0; `i<2; `i=`i+1) { assign y[`i]=a[`i]; } }\n");
    slip::Options options; options.filelists = {list};
    const auto result = slip::compile_file(source, options);
    for (const auto& path : {header, ip, list, included, source})
        CHECK(std::find(result.dependencies.begin(), result.dependencies.end(), path) != result.dependencies.end());
    bool expansion = false;
    for (const auto& loc : result.source_maps.at("bits")) expansion |= loc.expansion == "i=1";
    CHECK(expansion);
    slip::write_outputs(result, directory.path()/"output dir");
    const auto depfile = read(directory.path()/"output dir/slip.d");
    test::contains(depfile, "output\\ dir/top.sv");
    test::contains(depfile, "width.svh");
    test::contains(read(directory.path()/"output dir/source-map.json"), "\"expansion\":\"i=1\"");
    slip::Options downstream;
    downstream.filelists = {directory.path()/"output dir/sources.f"};
    CHECK(slip::compile("module wrapper(a,y) { top u {.a,.y}; }", "wrapper.slip", downstream).modules.contains("wrapper"));
}
TEST_CASE(filelists_handle_quotes_variables_libraries_and_multiple_arguments) {
    test::Directory directory;
    directory.write("lib dir/leaf.svx", "module leaf(input logic [3:0] a, output logic [3:0] y); assign y=a; endmodule\n");
    directory.write("header dir/width.svh", "`define W 4\n");
    directory.write("src dir/extra.sv", "`include \"width.svh\"\nmodule extra(input logic [`W-1:0] a, output logic [`W-1:0] y); assign y=a; endmodule\n");
    const auto list = directory.write("root.f", "/* comment */\n+libext+.svx -y \"lib dir\"\n-I\"header dir\"\n-f \"nested/child.f\"\n-sverilog\n");
    directory.write("nested/child.f", "\"../src dir/extra.sv\" // comment\n+define+MASK=4'hf\n");
    slip::Options options; options.filelists = {list};
    const auto result = slip::compile("module top(a,y) { logic [3:0] link; leaf u {.a,.y(link)}; extra v {.a(link),.y}; }", "top.slip", options);
    test::contains(result.modules.at("top"), "output logic [3:0] y");
    const auto bad = directory.write("bad.f", "\n-unknown silently-ignored-before\n");
    options.filelists = {bad};
    const auto error = test::error([&] { slip::compile("module top {}", "top.slip", options); }, "E_FILELIST", "unsupported");
    CHECK(error.location.line == 2);
    const auto missing = directory.write("missing-var.f", "${SLIP_TEST_VARIABLE_THAT_DOES_NOT_EXIST_29381}/file.sv\n");
    options.filelists = {missing};
    test::error([&] { slip::compile("module top {}", "top.slip", options); }, "E_FILELIST", "not set");
    // An existing environment variable can hold a directory containing spaces.
#ifdef _WIN32
    _putenv_s("SLIP_TEST_FILELIST_ROOT", directory.path().string().c_str());
#else
    setenv("SLIP_TEST_FILELIST_ROOT", directory.path().string().c_str(), 1);
#endif
    const auto variable = directory.write("env.f", "-I\"${SLIP_TEST_FILELIST_ROOT}/header dir\"\n\"$(SLIP_TEST_FILELIST_ROOT)/src dir/extra.sv\"\n");
    options.filelists = {variable};
    CHECK(slip::compile("module top(a,y) { extra u {.a,.y}; }", "top.slip", options).modules.contains("top"));
#ifdef _WIN32
    _putenv_s("SLIP_TEST_FILELIST_ROOT", "");
#else
    unsetenv("SLIP_TEST_FILELIST_ROOT");
#endif
}
TEST_CASE(selected_top_prunes_unused_modules_and_applies_structural_overrides) {
    const std::string source = R"(
module generated #(param N=2) (a,y) {
    logic [N-1:0] a, y;
    `for (`i=0; `i<N; `i+=1) { assign y[`i]=a[`i]; }
}
module top #(param N=2) (a,y) {
    logic [N-1:0] a, y;
    generated #(.N(N)) u {.a,.y};
}
module unused(a,y) { nonexistent u {.a,.y}; }
)";
    slip::Options options; options.top = "top"; options.parameter_overrides = {{"N", "4"}};
    const auto result = slip::compile(source, "selected.slip", options);
    CHECK(result.modules.size() == 2);
    CHECK(!result.modules.contains("unused"));
    test::contains(result.modules.at("top"), "parameter N = 4");
    for (const auto& [name, sv] : result.modules) if (name != "top") test::contains(sv, "assign y[3] = a[3]");
    options.top = "missing";
    test::rejected(source, "E_TOP", "missing", options);
    options.top = "top"; options.parameter_overrides = {{"UNKNOWN", "4"}};
    test::rejected(source, "E_PARAMETER", "unknown", options);
    options.top.clear();
    test::rejected(source, "E_PARAMETER", "require", options);
}
TEST_CASE(warning_policies_promote_disable_and_locally_waive_with_reasons) {
    const std::string source = "module m(a,y) { logic [7:0] a; logic [3:0] y; assign y=a; }\n";
    slip::Options options; options.warning_levels["W_WIDTH"] = "error";
    test::rejected(source, "E_WARNING_AS_ERROR", "W_WIDTH", options);
    options.warning_levels["W_WIDTH"] = "off";
    CHECK(slip::compile(source, "width.slip", options).warnings.empty());
    options.warnings_as_errors = true; options.warning_levels["W_WIDTH"] = "warning";
    CHECK(slip::compile(source, "width.slip", options).warnings.size() == 1);
    options.warning_levels.clear();
    const std::string waived = "module m(a,y) {\nlogic [7:0] a; logic [3:0] y;\n// slip: waive W_WIDTH -- truncation is intentional\nassign y=a;\n}\n";
    CHECK(slip::compile(waived, "waived.slip", options).warnings.empty());
    const std::string region = "module m(a,y) {\nlogic [7:0] a; logic [3:0] y;\n// slip: disable W_WIDTH -- legacy low bits only\nassign y=a;\n// slip: enable W_WIDTH\n}\n";
    CHECK(slip::compile(region, "region.slip", options).warnings.empty());
    test::rejected("// slip: waive W_WIDTH\n"+source, "E_DIAGNOSTIC_CONFIG", "reason", options);
    test::rejected("// slip: disable W_TYPO -- reason\n"+source, "E_DIAGNOSTIC_CONFIG", "unknown", options);
    test::rejected("// slip: enable W_WIDTH\n"+source, "E_DIAGNOSTIC_CONFIG", "not disabled", options);
    options.warning_levels["W_TYPO"] = "off";
    test::rejected(source, "E_CONFIG", "unknown", options);
}
TEST_CASE(implicit_ports_and_internal_signals_can_be_constrained_independently) {
    slip::Options options; options.no_implicit_ports = true;
    test::rejected("module m { assign y=a; }", "E_IMPLICIT", "explicit", options);
    CHECK(slip::compile("module m(a,y) { assign tmp=a; assign y=tmp; }", "internal.slip", options).modules.contains("m"));
    options.no_implicit_ports = false; options.no_implicit_signals = true;
    CHECK(slip::compile("module m { assign y=a; }", "ports.slip", options).modules.contains("m"));
    test::rejected("module m(a,y) { assign tmp=a; assign y=tmp; }", "E_IMPLICIT", "tmp", options);
}
TEST_CASE(signed_literals_common_loops_and_multi_declarations_compile) {
    const auto sv = test::module(R"(
module m(a,y,z) {
    logic signed [7:0] a, y, z;
    logic [7:0] memories [0:1], other [0:2];
    comb { for (int i=7; i>=0; i--) { y[i] = a[i]; } }
    assign z = (a < 8'shff) ? 8'sd1 : 'sh7f;
}
)");
    test::contains(sv, "8'shff");
    test::contains(sv, "'sh7f");
    test::contains(sv, "logic [7:0] other [0:2]");
    test::rejected("module m(a,y) { for (`i=0; `i<4; `i=`i+1) { assign y[`i]=a[`i]; } }", "E_PARSE", "requires `for");
    test::rejected("module m(a,y) { for(i=0;i<4;i++) { assign y[i]=a[i]; } }", "E_CONTEXT", "module-level expansion");
}
TEST_CASE(signal_inspection_tracks_drivers_consumers_and_inference_origins) {
    const std::string source = R"(
module leaf(a,y) { logic [7:0] a,y; assign y=a; }
module m(clk,a,y) {
    logic clk;
    leaf u {.a(a),.y(link)};
    seq(clk) { y=link; }
}
)";
    slip::Options options; options.collect_inspection = true;
    const auto result = slip::compile(source, "trace.slip", options);
    const auto& module = result.inspection.at("m");
    const auto link = std::find_if(module.signals.begin(), module.signals.end(), [](const auto& signal) { return signal.name == "link"; });
    CHECK(link != module.signals.end());
    CHECK(link->inferred_from == "leaf.y");
    CHECK(!link->drivers.empty()); CHECK(!link->uses.empty());
    CHECK(link->drivers.front().kind == "u.y");
    CHECK(link->uses.front().kind == "seq assignment");
    CHECK(link->uses.front().loc.file == "trace.slip");
    const auto clk = std::find_if(module.ports.begin(), module.ports.end(), [](const auto& signal) { return signal.name == "clk"; });
    CHECK(clk != module.ports.end());
    CHECK(clk->uses.front().kind == "clock");
}
TEST_CASE(filelist_roundtrip_preserves_quoted_plus_dollar_and_hash_in_paths) {
    test::Directory directory;
    directory.write("headers+dir/width.svh", "`define W 4\n");
    directory.write("ip+$#dir/leaf.sv", "`include \"width.svh\"\nmodule leaf(input logic [`W-1:0] a, output logic [`W-1:0] y); assign y=a; endmodule\n");
    const auto list = directory.write("root.f", "+incdir+\"headers+dir\"\n\"ip+\\$#dir/leaf.sv\"\n");
    slip::Options options; options.filelists = {list};
    auto result = slip::compile("module m(a,y) { leaf u {.a,.y}; }", "roundtrip.slip", options);
    slip::write_outputs(result, directory.path()/"gen+$#dir");
    options.filelists = {directory.path()/"gen+$#dir/sources.f"};
    CHECK(slip::compile("module wrapper(a,y) { m u {.a,.y}; }", "wrapper.slip", options).modules.contains("wrapper"));
}

TEST_CASE(malformed_signed_literals_fail_without_stalling_the_lexer) {
    for (const auto& literal : {"'s", "'sq", "8'sh_", "'sh", "8'sb2"})
        test::rejected("module m(y) { assign y=" + std::string(literal) + "; }", "E_LEX");
}
TEST_CASE(package_types_and_type_parameters_preserve_external_type_identity) {
    test::Directory directory;
    directory.write("types.sv", R"(
package types;
    typedef struct packed { logic [7:0] data; logic valid; } packet_t;
    parameter N=3;
endpackage
module external #(parameter type T=logic) (input T a, output T y);
    assign y=a;
endmodule
)");
    slip::Options options; options.ip_dirs = {directory.path()};
    const auto result = slip::compile(R"(
module generic #(param type T=logic) (a,y) {
    input T a;
    output T y;
    assign y=a;
}
module top(a,y,z) {
    input types::packet_t a;
    output types::packet_t y;
    output types::packet_t z;
    external #(.T(types::packet_t)) u {.a,.y(link)};
    generic #(.T(types::packet_t)) v {.a(link),.y};
    assign z = types::packet_t'(a);
    `for (`i=0; `i<types::N; `i++) { logic unused_`i; }
}
)", "typed.slip", options);
    test::contains(result.modules.at("generic"), "parameter type T = logic");
    test::contains(result.modules.at("top"), "types::packet_t link");
    test::contains(result.modules.at("top"), "types::packet_t'(a)");
    test::contains(result.modules.at("top"), "unused_2");
}
TEST_CASE(synthesis_attributes_survive_generation_on_modules_signals_instances_and_processes) {
    const auto result = slip::compile(R"(
module leaf(a,y) { assign y=a; }
(* keep_hierarchy="yes" *) module m(clk,a,y) {
    logic clk,a,y;
    (* keep="true" *) logic internal;
    (* dont_touch="yes" *) leaf u {.a,.y(internal)};
    (* preserve *) seq(clk) { y=internal; }
    `for (`i=0; `i<2; `i++) { (* keep=1 *) logic extra_`i; }
}
)", "attributes.slip");
    const auto& sv = result.modules.at("m");
    test::contains(sv, "(* keep_hierarchy = \"yes\" *) module m");
    test::contains(sv, "(* keep = \"true\" *) logic internal");
    test::contains(sv, "(* dont_touch = \"yes\" *) leaf u");
    test::contains(sv, "(* preserve *) always_ff");
    test::contains(sv, "(* keep = 1 *) logic extra_1");
}
TEST_CASE(native_interface_arrays_connect_whole_arrays_and_individual_elements) {
    test::Directory directory;
    directory.write("stream.sv", R"(
interface Stream #(parameter W=8);
    logic [W-1:0] data;
    modport source(output data);
    modport sink(input data);
endinterface
module reader #(parameter N=2) (Stream.sink links[0:N-1], output logic [7:0] y);
    assign y=links[0].data;
endmodule
)");
    slip::Options options; options.ip_dirs = {directory.path()};
    const auto result = slip::compile(R"(
module producer #(param N=2) (a,links) {
    logic [7:0] a;
    interface Stream.source links[0:N-1];
    `for (`i=0;`i<N;`i++) { assign links[`i].data = a; }
}
module consume(link,y) {
    interface Stream.sink link;
    logic [7:0] y;
    assign y=link.data;
}
module top(a,y,z) {
    logic [7:0] a,y,z;
    interface Stream links[0:2];
    producer #(.N(3)) u {.a,.links};
    reader #(.N(3)) v {.links,.y};
    consume w {.link(links[2]),.y(z)};
}
)", "arrays.slip", options);
    test::contains(result.modules.at("top"), "Stream links[0:2]");
    test::contains(result.modules.at("top"), ".link(links[2])");
    bool specialized = false;
    for (const auto& [name, sv] : result.modules) if (name.starts_with("producer__")) {
        test::contains(sv, "links[2].data"); specialized = true;
    }
    CHECK(specialized);
    const auto mismatch = R"(module m(y) { logic [7:0] y; interface Stream links[0:2]; reader #(.N(2)) u {.links,.y}; })";
    test::rejected(mismatch, "E_INTERFACE", "shape mismatch", options);
    test::rejected("module m(y) { logic [7:0] y; interface Stream links[0:2]; assign y=links[3].data; }", "E_INTERFACE", "out of range", options);
}
TEST_CASE(multidimensional_interface_arrays_keep_per_element_direction_and_drivers) {
    test::Directory directory;
    directory.write("stream.sv", "interface Stream; logic data; modport source(output data); modport sink(input data); endinterface\n");
    slip::Options options; options.ip_dirs={directory.path()};
    const auto source = R"(
module m(a,y) {
    logic a,y;
    interface Stream links[1:0][0:1];
    `for (`i=0;`i<2;`i++) {
        `for (`j=0;`j<2;`j++) { assign links[`i][`j].data=a; }
    }
    assign y=links[1][1].data;
}
)";
    options.collect_inspection=true;
    const auto result=slip::compile(source,"matrix.slip",options);
    test::contains(result.modules.at("m"), "Stream links[1:0][0:1]");
    const auto& metadata=result.inspection.at("m").native_interfaces;
    CHECK(metadata.at("links").elements.size()==2);
    CHECK(metadata.at("links[0]").elements.size()==2);
    CHECK(metadata.at("links[1][1]").fields.size()==1);
    test::rejected("module m(a) { logic a; interface Stream links[0:1]; assign links[0].data=a; comb { links[0].data=~a; } }", "E_MULTIPLE_DRIVERS", "links[0].data", options);
    test::rejected("module m(a,links) { logic a; interface Stream.sink links[0:1]; assign links[0].data=a; }", "E_DIRECTION", "input interface field", options);
    options.max_expanded_statements=5;
    test::rejected("module m { interface Stream links[0:100]; }", "E_LIMIT", "expansion", options);
}
TEST_CASE(type_parameters_specialize_generation_and_freeze_parent_type_bindings) {
    const auto result=slip::compile(R"(
module bits #(param type T=logic [0:0]) (a,y) {
    input T a; output T y;
    `for (`i=0;`i<$bits(T);`i++) { assign y[`i]=a[`i]; }
}
module wrapper #(param type P=logic [3:0]) (a,y) {
    input P a; output P y;
    bits #(.T(P)) u {.a,.y};
}
module top(a,b,y,z) {
    logic [7:0] a,y;
    logic [3:0] b,z;
    bits #(.T(logic [7:0])) u {.a,.y};
    wrapper v {.a(b),.y(z)};
}
)","type-generation.slip");
    bool eight=false,four=false;
    for(const auto& [name,sv]:result.modules) if(name.starts_with("bits__")) {
        eight |= sv.find("assign y[7] = a[7]")!=std::string::npos;
        four |= sv.find("assign y[3] = a[3]")!=std::string::npos && sv.find("assign y[4]")==std::string::npos;
        test::contains(sv,"__slip_frozen_type_T");
    }
    CHECK(eight); CHECK(four);
    test::contains(result.modules.at("wrapper"),"__slip_frozen_type_P");
    slip::Options options; options.top="bits"; options.parameter_overrides={{"T","logic [15:0]"}};
    const auto top=slip::compile("module bits #(param type T=logic [0:0]) (a,y) { input T a; output T y; `for (`i=0;`i<$bits(T);`i++) { assign y[`i]=a[`i]; } }", "top-type.slip", options);
    test::contains(top.modules.at("bits"),"assign y[15] = a[15]");
}
TEST_CASE(structural_type_defaults_freeze_width_dependencies_and_reject_downstream_changes) {
    const std::string source=R"(
module typed #(param W=4, param type T=logic [W-1:0]) (a,y) {
    input T a; output T y;
    `for (`i=0;`i<$bits(T);`i++) { assign y[`i]=a[`i]; }
}
)";
    slip::Options options; options.top="typed"; options.parameter_overrides={{"W","8"}};
    const auto result=slip::compile(source,"frozen-type.slip",options);
    test::contains(result.modules.at("typed"),"__slip_frozen_W");
    test::contains(result.modules.at("typed"),"__slip_frozen_type_T");
    test::contains(result.modules.at("typed"),"assign y[7] = a[7]");
    test::Directory directory;
    slip::write_outputs(result,directory.path());
    slip::Options downstream; downstream.ip_dirs={directory.path()};
    test::rejected("module m(a,y) { logic [3:0] a,y; typed #(.W(4),.T(logic [3:0])) u {.a,.y}; }", "E_SV", "controls Slip compile-time expansion", downstream);
}
TEST_CASE(signal_queries_distinguish_native_constructor_inputs_and_static_uses) {
    test::Directory directory;
    directory.write("clocked.sv", "interface Clocked(input logic clk); logic data; modport source(input clk, output data); endinterface\n");
    slip::Options options; options.ip_dirs={directory.path()}; options.collect_inspection=true;
    const auto result=slip::compile("module m(clk,y) { logic clk,y; interface Clocked link {.clk}; assign link.data=clk; assign y=link.data; static_assert($bits(y)==1); }", "refs.slip", options);
    const auto& module=result.inspection.at("m");
    const auto clock=std::find_if(module.signals.begin(),module.signals.end(),[](const auto& item){return item.name=="link.clk";});
    CHECK(clock!=module.signals.end());
    CHECK(clock->drivers.size()==1);
    CHECK(clock->drivers.front().kind=="interface constructor link.clk");
    CHECK(clock->drivers.front().expression=="clk");
    const auto y=std::find_if(module.ports.begin(),module.ports.end(),[](const auto& item){return item.name=="y";});
    CHECK(y!=module.ports.end());
    CHECK(std::any_of(y->uses.begin(),y->uses.end(),[](const auto& item){return item.kind=="static assertion";}));
}
