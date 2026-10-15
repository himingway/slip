#pragma once

#include "slip/ir.hpp"
#include <cstddef>
#include <filesystem>
#include <map>

namespace slip {

struct Options {
    bool strict = false;
    std::vector<std::filesystem::path> ip_dirs, filelists;
    std::size_t max_meta_iterations = 10000;
    std::size_t max_expanded_statements = 100000;
    std::size_t max_include_depth = 128;
    bool no_implicit = false;
    bool widths_as_errors = false;
    bool collect_inspection = false;
    std::string top;
    std::map<std::string, std::string> parameter_overrides;
    bool no_implicit_ports = false, no_implicit_signals = false;
    bool warnings_as_errors = false;
    std::map<std::string, std::string> warning_levels; // error, warning, off
};
struct Diagnostic { Location loc; std::string code, message; };
struct Result {
    std::map<std::string, std::string> modules;
    std::vector<Diagnostic> warnings;
    // Populated on request, after instance resolution and whole-design validation.
    std::map<std::string, IRModule> inspection;
    // Dependency order, physical input files, and generated-line origins. Paths
    // are absolute so the build metadata is usable outside the source directory.
    std::vector<std::string> module_order;
    std::vector<std::filesystem::path> dependencies;
    std::vector<std::string> sv_sources, include_dirs, defines;
    std::map<std::string, std::vector<Location>> source_maps;
};

// Every call owns its complete state; independent compilations can run concurrently.
Result compile(std::string_view source, std::string filename = "<input>", const Options& options = {});
Result compile_file(const std::filesystem::path& file, const Options& options = {});
// Reflect an external module's default interface without requiring a valid Slip
// design. Used by editor completion while an instance is still being written.
Result inspect_external(const std::string& module, const Options& options = {});
// No files are written before the entire design has passed validation.
void write_outputs(const Result& result, const std::filesystem::path& directory);

} // namespace slip
