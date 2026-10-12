#include "slip/compiler.hpp"
#include <iostream>
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
                 "Usage: slip build|check FILE [OPTIONS]\n"
                 "  -o, --out-dir DIR       Output directory (build only; default: build)\n"
                 "  -ip, --ip-dirs DIR      External Verilog/SystemVerilog IP directory; repeatable\n"
                 "  -f, --filelist FILE     VCS source filelist; repeatable\n"
                 "  --strict               Require explicit signals and reject width mismatches\n"
                 "  --stdout               Write generated SV to stdout (build only)\n"
                 "  --diagnostics=json     Machine-readable diagnostics on stderr\n"
                 "  --help, --version      Show help or version\n"
                 "FILE may be '-' to read stdin.\n";
}
void diagnostic(const slip::Location& loc, std::string_view code, std::string_view message, bool machine, std::string_view severity) {
    if (machine) std::cerr << "{\"severity\":" << json(severity) << ",\"code\":" << json(code) << ",\"file\":" << json(loc.file)
                          << ",\"line\":" << loc.line << ",\"column\":" << loc.column << ",\"message\":" << json(message) << "}\n";
    else std::cerr << loc.file << ':' << loc.line << ':' << loc.column << ": " << severity << " [" << code << "]: " << message << '\n';
}
} // namespace

int main(int argc, char** argv) {
    bool machine = false;
    for (int i = 1; i < argc; ++i) if (std::string_view(argv[i]) == "--diagnostics=json") machine = true;
    try {
        if (argc == 1) { help(); return 0; }
        std::string command(argv[1]);
        if (command == "--version") { std::cout << "slip, version 0.2.0 (C++)\n"; return 0; }
        if (command == "--help" || command == "-h") { help(); return 0; }
        if (command != "build" && command != "check") throw slip::Error({"<command>"}, "E_USAGE", "expected build or check");
        slip::Options options;
        std::filesystem::path output = "build";
        std::string file;
        bool stdout_output = false;
        for (int i = 2; i < argc; ++i) {
            std::string arg(argv[i]);
            auto value = [&]() -> std::string { if (++i == argc) throw slip::Error({"<command>"}, "E_USAGE", "missing value after " + arg); return argv[i]; };
            if (arg == "--help" || arg == "-h") { help(); return 0; }
            if (arg == "--strict") options.strict = true;
            else if (arg == "-o" || arg == "--out-dir") output = value();
            else if (arg == "-ip" || arg == "--ip-dirs") options.ip_dirs.emplace_back(value());
            else if (arg == "-f" || arg == "--filelist") options.filelists.emplace_back(value());
            else if (arg == "--stdout") stdout_output = true;
            else if (arg == "--diagnostics=json" || arg == "--verbose") {}
            else if (arg.starts_with('-') && arg != "-") throw slip::Error({"<command>"}, "E_USAGE", "unknown option " + arg);
            else if (!file.empty()) throw slip::Error({"<command>"}, "E_USAGE", "expected one input file");
            else file = std::move(arg);
        }
        if (file.empty()) throw slip::Error({"<command>"}, "E_USAGE", "missing input file");
        if (stdout_output && command != "build") throw slip::Error({"<command>"}, "E_USAGE", "--stdout requires build");
        slip::Result result;
        if (file == "-") { std::ostringstream text; text << std::cin.rdbuf(); result = slip::compile(text.str(), "<stdin>", options); }
        else result = slip::compile_file(file, options);
        for (const auto& warning : result.warnings) diagnostic(warning.loc, warning.code, warning.message, machine, "warning");
        if (command == "check") std::cout << "No errors found.\n";
        else if (stdout_output) for (const auto& [name, source] : result.modules) { (void)name; std::cout << source; }
        else slip::write_outputs(result, output);
        return 0;
    } catch (const slip::Error& error) {
        diagnostic(error.location, error.code, error.message, machine, "error");
        return error.code == "E_USAGE" ? 2 : 1;
    } catch (const std::exception& error) {
        diagnostic({"<compiler>"}, "E_INTERNAL", error.what(), machine, "error");
        return 1;
    }
}
