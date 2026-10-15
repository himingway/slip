#include "slip/compiler.hpp"
#include "project.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>

namespace {
std::string json(std::string_view value) {
    std::string result = "\"";
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned char ch : value) {
        if (ch == '"' || ch == '\\') { result += '\\'; result += ch; }
        else if (ch < 32) { result += "\\u00"; result += digits[ch >> 4]; result += digits[ch & 15]; }
        else result += ch;
    }
    return result + '"';
}
void help() {
    std::cout << "Slip 0.2.0 — native C++ HDL compiler\n\n"
                 "Usage: slip build|check|inspect [FILE] [OPTIONS]\n"
                 "  --project FILE         Read project settings (default without input: ./slip.conf)\n"
                 "  --profile NAME         Select [profile.NAME] from project settings\n"
                 "  --top NAME             Build and validate one top and its dependencies\n"
                 "  -P, --param NAME=EXPR   Override a top parameter; repeatable\n"
                 "  --warning CODE=LEVEL   Set error, warning or off for one warning\n"
                 "  --warnings-as-errors   Promote all unsuppressed warnings\n"
                 "  --warnings-as-warnings Keep warnings from project settings nonfatal\n"
                 "  --no-implicit-ports     Require explicit port names\n"
                 "  --no-implicit-signals   Require explicit internal signals\n"
                 "  -o, --out-dir DIR       Output directory (build only; default: build)\n"
                 "  -ip, --ip-dirs DIR      External Verilog/SystemVerilog IP directory; repeatable\n"
                 "  -f, --filelist FILE     VCS source filelist; repeatable\n"
                 "  --strict               Require explicit signals and reject width mismatches\n"
                 "  --no-strict            Disable both strict checks from project settings\n"
                 "  --no-implicit          Reject implicit declarations\n"
                 "  --allow-implicit       Allow implicit declarations from project settings\n"
                 "  --widths-as-errors     Reject width mismatches\n"
                 "  --widths-as-warnings   Keep width mismatches as warnings\n"
                 "  --interface MODULE     Reflect an external module without compiling a design\n"
                 "  --signal MODULE.NAME   Inspect one signal's drivers, uses and inference\n"
                 "  --format=text|json     Inspection output format (inspect only; default: text)\n"
                 "  --stdout               Write generated SV to stdout (build only)\n"
                 "  --diagnostics=json     Machine-readable diagnostics on stderr\n"
                 "  --help, --version      Show help or version\n"
                 "FILE may be '-' to read stdin. Explicit input uses project settings only with --project.\n";
}
std::string location_json(const slip::Location& loc) {
    return "{\"file\":" + json(loc.file) + ",\"line\":" + std::to_string(loc.line) + ",\"column\":" + std::to_string(loc.column) +
        (loc.expansion.empty() ? "" : ",\"expansion\":" + json(loc.expansion)) + "}";
}
class Reporter {
    bool machine;
    std::map<std::string, std::vector<std::string>> sources;
public:
    explicit Reporter(bool machine) : machine(machine) {}
    void capture(const std::string& file, std::istream& stream) {
        auto& lines = sources[file];
        std::string line;
        while (std::getline(stream, line)) { if (!line.empty() && line.back() == '\r') line.pop_back(); lines.push_back(std::move(line)); }
    }
    void diagnostic(const slip::Location& loc, std::string_view code, std::string_view message, std::string_view severity) {
        if (machine) {
            std::cerr << "{\"severity\":" << json(severity) << ",\"code\":" << json(code) << ",\"file\":" << json(loc.file)
                      << ",\"line\":" << loc.line << ",\"column\":" << loc.column << ",\"message\":" << json(message);
            if (!loc.expansion.empty()) std::cerr << ",\"expansion\":" << json(loc.expansion);
            std::cerr << "}\n";
            return;
        }
        std::cerr << loc.file << ':' << loc.line << ':' << loc.column << ": " << severity << " [" << code << "]: " << message << '\n';
        if (!sources.contains(loc.file)) { std::ifstream stream(loc.file); capture(loc.file, stream); }
        const auto& lines = sources.at(loc.file);
        if (loc.line > 0 && loc.line <= lines.size()) {
            const auto& line = lines[loc.line - 1];
            const auto column = std::min<std::size_t>(loc.column ? loc.column - 1 : 0, line.size());
            const auto start = column > 100 ? column - 100 : 0;
            const auto excerpt = line.substr(start, 240);
            std::string padding;
            for (std::size_t i = start; i < column; ++i) padding += line[i] == '\t' ? '\t' : ' ';
            std::cerr << "  | " << (start ? "..." : "") << excerpt << (start + excerpt.size() < line.size() ? "..." : "") << '\n';
            std::cerr << "  | " << (start ? "   " : "") << padding << "^\n";
        }
        if (!loc.expansion.empty()) std::cerr << "  note: expanded with " << loc.expansion << '\n';
    }
};
std::string signal_type(const slip::IRSignal& signal) {
    return signal.type + " " + std::string(signal.is_signed ? "signed " : "") + (signal.width.empty() ? "" : signal.width + " ") +
        signal.name + (signal.array.empty() ? "" : " " + signal.array);
}
void inspect_text(const slip::Result& result) {
    for (const auto& [name, module] : result.inspection) {
        std::cout << "module " << name << '\n';
        for (const auto& parameter : module.parameters) {
            std::cout << "  parameter " << (parameter.is_type ? "type " : "") << parameter.name << " = " << slip::to_sv(parameter.value);
            for (const auto& [frozen, value] : module.frozen_parameters) if (frozen == parameter.name)
                std::cout << " (fixed at " << value << " by compile-time expansion)";
            for (const auto& [frozen, value] : module.frozen_type_parameters) if (frozen == parameter.name)
                std::cout << " (fixed at " << value << " by compile-time expansion)";
            std::cout << '\n';
        }
        auto signals = [](std::string_view title, const std::vector<slip::IRSignal>& items) {
            if (items.empty()) return;
            std::cout << "  " << title << ":\n";
            for (const auto& signal : items) {
                std::cout << "    " << (signal.direction.empty() ? "" : signal.direction + " ") << signal_type(signal);
                if (!signal.declared) std::cout << " [implicit]";
                if (!signal.direction.empty() && !signal.direction_explicit && !signal.interface_port && !signal.interface_field)
                    std::cout << " [inferred direction: " << signal.direction << "]";
                if (signal.type_inferred) std::cout << " [inferred type: " << signal.type << "]";
                if (!signal.inferred_from.empty()) std::cout << " [width from " << signal.inferred_from << "]";
                std::cout << '\n';
                for (const auto* refs : {&signal.drivers, &signal.uses}) for (const auto& ref : *refs)
                    std::cout << "      " << (refs == &signal.drivers ? "driver" : "use") << ": " << ref.kind << " " << ref.expression
                              << " at " << ref.loc.file << ':' << ref.loc.line << ':' << ref.loc.column << '\n';
            }
        };
        for (const auto& [group, fields] : module.bundles) {
            std::cout << "  bundle " << module.bundle_types.at(group) << " " << group << ":";
            for (const auto& field : fields) std::cout << " " << field;
            std::cout << '\n';
        }
        for (const auto& [name, native] : module.native_interfaces) {
            std::cout << "  interface " << native.type << (native.modport.empty() ? "" : "." + native.modport) << ' ' << name
                      << (native.port ? " [port]" : " [instance]") << (native.array.empty() ? "" : " " + native.array) << '\n';
            for (const auto& [parameter, value] : native.parameters) std::cout << "    parameter " << parameter << " = " << value << '\n';
            for (const auto& field : native.fields) std::cout << "    " << (field.direction.empty() ? "" : field.direction + " ") << field.name << '\n';
        }
        signals("Ports", module.ports); signals("Signals", module.signals);
        for (const auto& instance : module.instances) {
            std::cout << "  instance " << instance.module << ' ' << instance.name << '\n';
            for (const auto& [param, value] : instance.parameters) std::cout << "    parameter " << param << " = " << value << '\n';
            for (const auto& connection : instance.connection_details) {
                std::cout << "    " << connection.direction << ' ' << connection.port;
                if (!connection.width.empty()) std::cout << ' ' << connection.width;
                if (!connection.array.empty()) std::cout << ' ' << connection.array;
                std::cout << " -> " << (connection.signal.empty() ? "(unconnected)" : connection.signal == "_" ? "(intentionally unconnected)" : connection.signal)
                          << " [" << connection.origin << "]\n";
            }
        }
        std::cout << '\n';
    }
}
void inspect_json(const slip::Result& result) {
    std::cout << "{\"modules\":[";
    bool first_module = true;
    for (const auto& [name, module] : result.inspection) {
        if (!first_module) std::cout << ',';
        first_module = false;
        std::cout << "{\"name\":" << json(name) << ",\"location\":" << location_json(module.loc) << ",\"bundles\":[";
        bool first_bundle = true;
        for (const auto& [group, fields] : module.bundles) {
            if (!first_bundle) std::cout << ',';
            first_bundle = false;
            std::cout << "{\"name\":" << json(group) << ",\"schema\":" << json(module.bundle_types.at(group)) << ",\"fields\":[";
            for (std::size_t i = 0; i < fields.size(); ++i) { if (i) std::cout << ','; std::cout << json(fields[i]); }
            std::cout << "]}";
        }
        std::cout << "],\"interfaces\":[";
        bool first_interface = true;
        for (const auto& [name, native] : module.native_interfaces) {
            if (!first_interface) std::cout << ',';
            first_interface = false;
            std::cout << "{\"name\":" << json(name) << ",\"type\":" << json(native.type) << ",\"modport\":" << json(native.modport)
                      << ",\"port\":" << (native.port ? "true" : "false") << ",\"array\":" << json(native.array) << ",\"location\":" << location_json(native.loc) << ",\"parameters\":[";
            for (std::size_t i = 0; i < native.parameters.size(); ++i) {
                if (i) std::cout << ',';
                std::cout << "{\"name\":" << json(native.parameters[i].first) << ",\"value\":" << json(native.parameters[i].second) << '}';
            }
            std::cout << "],\"fields\":[";
            for (std::size_t i = 0; i < native.fields.size(); ++i) {
                if (i) std::cout << ',';
                const auto& field = native.fields[i];
                std::cout << "{\"name\":" << json(field.name) << ",\"type\":" << json(field.type) << ",\"direction\":" << json(field.direction) << ",\"width\":" << json(field.width) << '}';
            }
            std::cout << "]}";
        }
        std::cout << "],\"parameters\":[";

        for (std::size_t i = 0; i < module.parameters.size(); ++i) {
            if (i) std::cout << ',';
            const auto& param = module.parameters[i];
            const auto frozen = std::find_if(module.frozen_parameters.begin(), module.frozen_parameters.end(), [&](const auto& value) { return value.first == param.name; });
            const auto frozen_type = std::find_if(module.frozen_type_parameters.begin(), module.frozen_type_parameters.end(), [&](const auto& value) { return value.first == param.name; });
            std::cout << "{\"name\":" << json(param.name) << ",\"value\":" << json(slip::to_sv(param.value)) << ",\"is_type\":" << (param.is_type ? "true" : "false")
                      << ",\"frozen\":" << (frozen == module.frozen_parameters.end() && frozen_type == module.frozen_type_parameters.end() ? "false" : "true");
            if (frozen != module.frozen_parameters.end()) std::cout << ",\"frozen_value\":" << frozen->second;
            if (frozen_type != module.frozen_type_parameters.end()) std::cout << ",\"fixed_type\":" << json(frozen_type->second);
            std::cout << '}';
        }
        auto signals = [](std::string_view key, const std::vector<slip::IRSignal>& items) {
            std::cout << "]," << json(key) << ":[";
            for (std::size_t i = 0; i < items.size(); ++i) {
                if (i) std::cout << ',';
                const auto& signal = items[i];
                std::cout << "{\"name\":" << json(signal.name) << ",\"direction\":" << json(signal.direction)
                          << ",\"type\":" << json(signal.type) << ",\"width\":" << json(signal.width) << ",\"array\":" << json(signal.array)
                          << ",\"signed\":" << (signal.is_signed ? "true" : "false") << ",\"declared\":" << (signal.declared ? "true" : "false")
                          << ",\"type_inferred\":" << (signal.type_inferred ? "true" : "false")
                          << ",\"direction_inferred\":" << (!signal.direction.empty() && !signal.direction_explicit && !signal.interface_port && !signal.interface_field ? "true" : "false")
                          << ",\"inferred_from\":" << json(signal.inferred_from) << ",\"location\":" << location_json(signal.loc);
                for (const auto* refs : {&signal.drivers, &signal.uses}) {
                    std::cout << (refs == &signal.drivers ? ",\"drivers\":[" : ",\"uses\":[");
                    for (std::size_t j = 0; j < refs->size(); ++j) {
                        if (j) std::cout << ',';
                        const auto& ref = (*refs)[j];
                        std::cout << "{\"kind\":" << json(ref.kind) << ",\"expression\":" << json(ref.expression) << ",\"location\":" << location_json(ref.loc) << '}';
                    }
                    std::cout << ']';
                }
                std::cout << '}';
            }
        };
        signals("ports", module.ports); signals("signals", module.signals);
        std::cout << "],\"instances\":[";
        for (std::size_t i = 0; i < module.instances.size(); ++i) {
            if (i) std::cout << ',';
            const auto& instance = module.instances[i];
            std::cout << "{\"module\":" << json(instance.module) << ",\"name\":" << json(instance.name) << ",\"location\":" << location_json(instance.loc) << ",\"parameters\":[";
            for (std::size_t j = 0; j < instance.parameters.size(); ++j) {
                if (j) std::cout << ',';
                std::cout << "{\"name\":" << json(instance.parameters[j].first) << ",\"value\":" << json(instance.parameters[j].second) << '}';
            }
            std::cout << "],\"connections\":[";
            for (std::size_t j = 0; j < instance.connection_details.size(); ++j) {
                if (j) std::cout << ',';
                const auto& connection = instance.connection_details[j];
                std::cout << "{\"port\":" << json(connection.port) << ",\"direction\":" << json(connection.direction)
                          << ",\"width\":" << json(connection.width) << ",\"array\":" << json(connection.array)
                          << ",\"signal\":" << json(connection.signal) << ",\"origin\":" << json(connection.origin)
                          << ",\"location\":" << location_json(connection.loc) << '}';
            }
            std::cout << "]}";
        }
        std::cout << "]}";
    }
    std::cout << "]}\n";
}
} // namespace

int main(int argc, char** argv) {
    bool machine = false;
    for (int i = 1; i < argc; ++i) if (std::string_view(argv[i]) == "--diagnostics=json") machine = true;
    Reporter reporter(machine);
    try {
        if (argc == 1) { help(); return 0; }
        std::string command(argv[1]);
        if (command == "--version") { std::cout << "slip, version 0.2.0 (C++)\n"; return 0; }
        if (command == "--help" || command == "-h") { help(); return 0; }
        if (command != "build" && command != "check" && command != "inspect") throw slip::Error({"<command>"}, "E_USAGE", "expected build, check or inspect");
        slip::Options cli_options;
        std::filesystem::path output = "build";
        std::string file, project_file, profile, signal_query, external_interface;
        std::vector<std::string> check_overrides;
        bool stdout_output = false;
        bool output_option = false;
        bool format_option = false;
        std::string format = "text";
        for (int i = 2; i < argc; ++i) {
            std::string arg(argv[i]);
            auto value = [&]() -> std::string { if (++i == argc) throw slip::Error({"<command>"}, "E_USAGE", "missing value after " + arg); return argv[i]; };
            if (arg == "--help" || arg == "-h") { help(); return 0; }
            if (arg == "--strict" || arg == "--no-strict" || arg == "--no-implicit" || arg == "--allow-implicit" ||
                arg == "--widths-as-errors" || arg == "--widths-as-warnings") check_overrides.push_back(arg);
            else if (arg == "--interface") external_interface = value();
            else if (arg == "--signal") signal_query = value();
            else if (arg == "--profile") profile = value();
            else if (arg == "--top") cli_options.top = value();
            else if (arg == "--warnings-as-errors" || arg == "--warnings-as-warnings") check_overrides.push_back(arg);
            else if (arg == "--no-implicit-ports" || arg == "--allow-implicit-ports" || arg == "--no-implicit-signals" || arg == "--allow-implicit-signals") check_overrides.push_back(arg);
            else if (arg == "-P" || arg == "--param" || arg == "--warning") {
                const auto setting = value();
                const auto equal = setting.find('=');
                if (equal == setting.npos || equal == 0 || equal + 1 == setting.size()) throw slip::Error({"<command>"}, "E_USAGE", "expected NAME=VALUE after " + arg);
                if (arg == "--warning") cli_options.warning_levels[setting.substr(0, equal)] = setting.substr(equal + 1);
                else cli_options.parameter_overrides[setting.substr(0, equal)] = setting.substr(equal + 1);
            }
            else if (arg == "--project") {
                if (!project_file.empty()) throw slip::Error({"<command>"}, "E_USAGE", "expected one --project configuration");
                project_file = value();
                if (project_file.empty()) throw slip::Error({"<command>"}, "E_USAGE", "--project requires a configuration path");
            }
            else if (arg == "-o" || arg == "--out-dir") { output = value(); output_option = true; }
            else if (arg == "-ip" || arg == "--ip-dirs") cli_options.ip_dirs.emplace_back(value());
            else if (arg == "-f" || arg == "--filelist") cli_options.filelists.emplace_back(value());
            else if (arg == "--stdout") stdout_output = true;
            else if (arg.starts_with("--format=")) { format = arg.substr(9); format_option = true; }
            else if (arg == "--diagnostics=json" || arg == "--verbose") {}
            else if (arg.starts_with('-') && arg != "-") throw slip::Error({"<command>"}, "E_USAGE", "unknown option " + arg);
            else if (!file.empty()) throw slip::Error({"<command>"}, "E_USAGE", "expected one input file");
            else file = std::move(arg);
        }
        if (!external_interface.empty() && (command != "inspect" || !file.empty())) throw slip::Error({"<command>"}, "E_USAGE", "--interface requires inspect without a Slip input file");
        if (!signal_query.empty() && command != "inspect") throw slip::Error({"<command>"}, "E_USAGE", "--signal requires inspect");
        if (stdout_output && command != "build") throw slip::Error({"<command>"}, "E_USAGE", "--stdout requires build");
        if (output_option && command != "build") throw slip::Error({"<command>"}, "E_USAGE", "--out-dir requires build");
        if (format_option && (command != "inspect" || (format != "text" && format != "json")))
            throw slip::Error({"<command>"}, "E_USAGE", "--format=text|json requires inspect");
        std::optional<slip::cli::Project> project;
        if (!project_file.empty()) project = slip::cli::read_project(project_file, profile);
        else if (file.empty() || !profile.empty()) {
            std::error_code error;
            const bool exists = std::filesystem::exists("slip.conf", error);
            if (error) throw slip::Error({"slip.conf"}, "E_IO", "cannot inspect project configuration: " + error.message());
            if (exists) project = slip::cli::read_project("slip.conf", profile);
        }
        if (!profile.empty() && !project) throw slip::Error({"<command>"}, "E_USAGE", "--profile requires --project or ./slip.conf");
        slip::Options options;
        if (project) {
            options = project->options;
            if (file.empty() && external_interface.empty()) file = project->entry;
            if (!output_option) output = project->output;
        }
        if (file.empty() && external_interface.empty()) {
            if (project) throw slip::Error(project->loc, "E_CONFIG", "project has no entry; set entry or pass an input file");
            throw slip::Error({"<command>"}, "E_USAGE", "missing input file; pass FILE or create slip.conf with entry = path/to/design.slip");
        }
        if (!cli_options.top.empty()) options.top = cli_options.top;
        for (const auto& [key, value] : cli_options.parameter_overrides) options.parameter_overrides[key] = value;
        for (const auto& [key, value] : cli_options.warning_levels) options.warning_levels[key] = value;
        options.ip_dirs.insert(options.ip_dirs.end(), cli_options.ip_dirs.begin(), cli_options.ip_dirs.end());
        options.filelists.insert(options.filelists.end(), cli_options.filelists.begin(), cli_options.filelists.end());
        // Apply command-line checks in order, after the project configuration.
        for (const auto& flag : check_overrides) {
            if (flag == "--strict" || flag == "--no-strict") {
                options.no_implicit = flag == "--strict";
                options.widths_as_errors = flag == "--strict";
                options.no_implicit_ports = false; options.no_implicit_signals = false;
            }
            else if (flag == "--no-implicit" || flag == "--allow-implicit") {
                options.no_implicit = flag == "--no-implicit";
                options.no_implicit_ports = false; options.no_implicit_signals = false;
            }
            else if (flag == "--no-implicit-ports" || flag == "--allow-implicit-ports") {
                if (options.no_implicit) { options.no_implicit = false; options.no_implicit_signals = true; }
                options.no_implicit_ports = flag == "--no-implicit-ports";
            }
            else if (flag == "--no-implicit-signals" || flag == "--allow-implicit-signals") {
                if (options.no_implicit) { options.no_implicit = false; options.no_implicit_ports = true; }
                options.no_implicit_signals = flag == "--no-implicit-signals";
            }
            else if (flag == "--warnings-as-errors" || flag == "--warnings-as-warnings") options.warnings_as_errors = flag == "--warnings-as-errors";
            else options.widths_as_errors = flag == "--widths-as-errors";
        }
        options.collect_inspection = command == "inspect";
        slip::Result result;
        if (!external_interface.empty()) result = slip::inspect_external(external_interface, options);
        else if (file == "-") {
            std::ostringstream text; text << std::cin.rdbuf();
            std::istringstream source(text.str()); reporter.capture("<stdin>", source);
            result = slip::compile(text.str(), "<stdin>", options);
        }
        else result = slip::compile_file(file, options);
        if (!signal_query.empty()) {
            const auto dot = signal_query.find('.');
            if (dot == signal_query.npos || dot == 0 || dot + 1 == signal_query.size()) throw slip::Error({"<command>"}, "E_USAGE", "--signal expects MODULE.NAME");
            const auto module = signal_query.substr(0, dot), name = signal_query.substr(dot + 1);
            if (!result.inspection.contains(module)) throw slip::Error({"<command>"}, "E_USAGE", "unknown module in signal query '" + module + "'");
            std::erase_if(result.inspection, [&](const auto& item) { return item.first != module; });
            auto& selected = result.inspection.at(module);
            std::erase_if(selected.ports, [&](const auto& item) { return item.name != name; });
            std::erase_if(selected.signals, [&](const auto& item) { return item.name != name; });
            if (selected.ports.empty() && selected.signals.empty()) throw slip::Error({"<command>"}, "E_USAGE", "unknown signal '" + signal_query + "'");
            selected.instances.clear(); selected.native_interfaces.clear(); selected.bundles.clear();
        }
        if (project) result.dependencies.push_back(std::filesystem::absolute(project->loc.file));
        for (const auto& warning : result.warnings) reporter.diagnostic(warning.loc, warning.code, warning.message, "warning");
        if (command == "check") std::cout << "No errors found.\n";
        else if (command == "inspect") { if (format == "json") inspect_json(result); else inspect_text(result); }
        else if (stdout_output) for (const auto& [name, source] : result.modules) { (void)name; std::cout << source; }
        else slip::write_outputs(result, output);
        return 0;
    } catch (const slip::Error& error) {
        reporter.diagnostic(error.location, error.code, error.message, "error");
        return error.code == "E_USAGE" || error.code == "E_CONFIG" ? 2 : 1;
    } catch (const std::exception& error) {
        reporter.diagnostic({"<compiler>"}, "E_INTERNAL", error.what(), "error");
        return 1;
    }
}
