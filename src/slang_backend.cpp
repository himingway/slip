#include "internal.hpp"

#include <slang/ast/Compilation.h>
#include <slang/ast/symbols/InstanceSymbols.h>
#include <slang/ast/symbols/ParameterSymbols.h>
#include <slang/ast/symbols/PortSymbols.h>
#include <slang/ast/symbols/CompilationUnitSymbols.h>
#include <slang/ast/types/DeclaredType.h>
#include <slang/ast/types/Type.h>
#include <slang/diagnostics/DiagnosticEngine.h>
#include <slang/diagnostics/AllDiags.h>
#include <slang/parsing/Preprocessor.h>
#include <slang/syntax/AllSyntax.h>
#include <slang/syntax/SyntaxTree.h>
#include <slang/text/SourceManager.h>
#include <algorithm>
#include <regex>
#include <sstream>

namespace slip {
namespace {
void append_unique(std::vector<std::string>& items, std::string value) {
    if (std::find(items.begin(), items.end(), value) == items.end()) items.push_back(std::move(value));
}
std::string strip_comments(std::string text) {
    bool in_block = false;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (!in_block && text.substr(i, 2) == "/*") { in_block = true; text[i++] = ' '; text[i] = ' '; }
        else if (in_block && text.substr(i, 2) == "*/") { in_block = false; text[i++] = ' '; text[i] = ' '; }
        else if (in_block && text[i] != '\n') text[i] = ' ';
    }
    if (in_block) throw Error({}, "E_FILELIST", "unterminated block comment in filelist");
    return text;
}
struct Sources {
    std::vector<std::string> files, includes, defines;
    std::set<std::filesystem::path> active;
    void filelist(const std::filesystem::path& file) {
        auto path = std::filesystem::weakly_canonical(file);
        if (active.size() >= 128) throw Error({path.string()}, "E_LIMIT", "filelist nesting limit exceeded");
        if (!active.insert(path).second) throw Error({path.string()}, "E_FILELIST", "circular filelist reference");
        auto resolve = [&](std::string_view value) { return std::filesystem::weakly_canonical(path.parent_path() / std::filesystem::path(trim(value))).string(); };
        std::istringstream lines(strip_comments(read_file(path)));
        std::string line;
        while (std::getline(lines, line)) {
            for (std::size_t i = 0; i + 1 < line.size(); ++i) {
                if (line.substr(i, 2) == "//" && (i == 0 || std::isspace(static_cast<unsigned char>(line[i-1])))) { line.resize(i); break; }
            }
            line = trim(line);
            if (line.empty()) continue;
            bool inc = line.starts_with("+incdir+");
            if (inc || line.starts_with("+define+")) {
                std::istringstream parts(line.substr(inc ? 8 : 8)); std::string part;
                while (std::getline(parts, part, '+')) {
                    part = trim(part);
                    if (!part.empty()) append_unique(inc ? includes : defines, inc ? resolve(part) : part);
                }
            } else if (line.starts_with("-f")) {
                auto sub = trim(std::string_view(line).substr(2));
                if (sub.empty()) throw Error({path.string()}, "E_FILELIST", "missing filelist after -f");
                filelist(resolve(sub));
            } else if (line[0] != '+' && line[0] != '-') append_unique(files, resolve(line));
        }
        active.erase(path);
    }
};
std::string packed_dimensions(const slang::syntax::DataTypeSyntax* type) {
    if (!type) return {};
    std::string result;
    std::string text = type->toString();
    static const std::regex brackets(R"(\[[^\]]*\])");
    for (auto it = std::sregex_iterator(text.begin(), text.end(), brackets); it != std::sregex_iterator(); ++it) result += it->str();
    return result;
}
} // namespace

struct Backend::Impl {
    // Destruction order is intentional: trees die before their source manager.
    slang::SourceManager source_manager;
    std::shared_ptr<slang::syntax::SyntaxTree> ip_tree;
    std::map<std::string, std::int64_t> constants;
};
Backend::~Backend() = default;
Backend::Backend(const Options& options) : impl(std::make_unique<Impl>()) {
    Sources sources;
    for (const auto& file : options.filelists) sources.filelist(file);
    for (const auto& directory : options.ip_dirs) {
        if (!std::filesystem::is_directory(directory)) throw Error({directory.string()}, "E_IO", "IP directory does not exist");
        std::vector<std::string> files;
        for (const auto& entry : std::filesystem::recursive_directory_iterator(directory)) {
            auto ext = entry.path().extension();
            if (entry.is_regular_file() && (ext == ".sv" || ext == ".v")) files.push_back(std::filesystem::weakly_canonical(entry.path()).string());
        }
        std::sort(files.begin(), files.end());
        for (auto& file : files) append_unique(sources.files, std::move(file));
    }
    if (sources.files.empty()) return;
    for (const auto& file : sources.files)
        if (!std::filesystem::is_regular_file(file)) throw Error({file}, "E_IO", "filelist source is not a readable regular file");
    slang::parsing::PreprocessorOptions preprocessor;
    for (const auto& include : sources.includes) preprocessor.additionalIncludePaths.emplace_back(include);
    preprocessor.predefines = sources.defines;
    std::vector<std::string_view> paths(sources.files.begin(), sources.files.end());
    auto tree = slang::syntax::SyntaxTree::fromFiles(paths, impl->source_manager, slang::Bag{preprocessor});
    if (!tree) throw Error({sources.files.front()}, "E_IP", "cannot parse IP files");
    impl->ip_tree = *tree;
    slang::Diagnostics errors;
    for (const auto& diagnostic : impl->ip_tree->diagnostics()) if (diagnostic.isError()) errors.push_back(diagnostic);
    if (!errors.empty()) throw Error({sources.files.front()}, "E_IP", slang::DiagnosticEngine::reportAll(impl->source_manager, errors));
    slang::ast::Compilation compilation;
    compilation.addSyntaxTree(impl->ip_tree);
    const auto& root = compilation.getRoot();
    for (const auto* definition : compilation.getDefinitions()) {
        std::string name(definition->name);
        if (ips.contains(name)) throw Error({sources.files.front()}, "E_DUPLICATE", "duplicate IP module '" + name + "'");
        auto instance = root.lookupName(name);
        const slang::ast::InstanceBodySymbol* reflected_body = nullptr;
        if (instance && instance->kind == slang::ast::SymbolKind::Instance)
            reflected_body = &instance->as<slang::ast::InstanceSymbol>().body;
        else if (definition->kind == slang::ast::SymbolKind::Definition)
            reflected_body = &slang::ast::InstanceSymbol::createDefault(compilation, definition->as<slang::ast::DefinitionSymbol>()).body;
        if (!reflected_body) continue;
        const auto& body = *reflected_body;
        Interface interface;
        for (const auto& symbol : body.members()) {
            if (symbol.kind == slang::ast::SymbolKind::TypeParameter)
                throw Error({sources.files.front()}, "E_IP", "type parameters are not supported by Slip: " + name);
            if (symbol.kind != slang::ast::SymbolKind::Parameter) continue;
            const auto& parameter = symbol.as<slang::ast::ParameterSymbol>();
            auto declared = symbol.getDeclaredType();
            auto initializer = declared ? declared->getInitializerSyntax() : nullptr;
            auto text = initializer ? trim(initializer->toString()) : parameter.getValue().toString();
            (parameter.isLocalParam() ? interface.localparams : interface.parameters).push_back({std::string(symbol.name), expression({sources.files.front()}, Literal{text})});
        }
        for (const auto* symbol : body.getPortList()) {
            if (symbol->kind != slang::ast::SymbolKind::Port)
                throw Error({sources.files.front()}, "E_IP", "unsupported interface port in '" + name + "'");
            const auto& port = symbol->as<slang::ast::PortSymbol>();
            InterfacePort info;
            info.name = std::string(port.name);
            info.direction = port.direction == slang::ast::ArgumentDirection::In ? "input" : port.direction == slang::ast::ArgumentDirection::Out ? "output" : "inout";
            info.is_signed = port.getType().isSigned();
            const auto* declared = port.internalSymbol ? port.internalSymbol->getDeclaredType() : nullptr;
            if (declared) {
                info.width = packed_dimensions(declared->getTypeSyntax());
                if (auto dims = declared->getDimensionSyntax()) for (auto dim : *dims) info.array += trim(dim->toString());
            }
            if (info.width.empty() && port.getType().getBitWidth() > 1 && info.array.empty()) info.width = "[" + std::to_string(port.getType().getBitWidth() - 1) + ":0]";
            interface.ports.push_back(std::move(info));
        }
        ips.emplace(name, std::move(interface));
    }
}

std::int64_t Backend::constant(std::string_view expr, const Environment& environment, Location loc) {
    std::string result_name = "__slip_constant";
    auto exists = [&](const std::string& name) { return std::any_of(environment.begin(), environment.end(), [&](const auto& pair) { return pair.first == name; }); };
    while (exists(result_name)) result_name += '_';
    std::string source = "module __slip_eval;\n";
    for (const auto& [name, value] : environment) source += "localparam " + name + " = " + value + ";\n";
    source += "localparam " + result_name + " = " + std::string(expr) + ";\nendmodule";
    if (auto found = impl->constants.find(source); found != impl->constants.end()) return found->second;
    slang::SourceManager manager;
    auto tree = slang::syntax::SyntaxTree::fromText(source, manager);
    slang::ast::Compilation compilation;
    compilation.addSyntaxTree(tree);
    const auto& body = compilation.getRoot().lookupName("__slip_eval")->as<slang::ast::InstanceSymbol>().body;
    slang::Diagnostics errors;
    for (const auto& diagnostic : compilation.getAllDiagnostics()) if (diagnostic.isError()) errors.push_back(diagnostic);
    if (!errors.empty()) throw Error(loc, "E_CONSTANT", slang::DiagnosticEngine::reportAll(manager, errors));
    const auto& value = body.lookupName(result_name)->as<slang::ast::ParameterSymbol>().getValue();
    if (!value.isInteger() || value.hasUnknown()) throw Error(loc, "E_CONSTANT", "constant is not a known integer (x/z or division by zero)");
    auto integer = value.integer().as<std::int64_t>();
    if (!integer || (!value.integer().isSigned() && *integer < 0)) throw Error(loc, "E_LIMIT", "metaprogram integer exceeds signed 64-bit range");
    if (impl->constants.size() >= 4096) impl->constants.clear();
    impl->constants.emplace(std::move(source), *integer);
    return *integer;
}

void Backend::validate(const std::map<std::string, std::string>& modules, bool strict, std::vector<Diagnostic>& warnings) {
    slang::ast::Compilation compilation;
    if (impl->ip_tree) compilation.addSyntaxTree(impl->ip_tree);
    for (const auto& [name, source] : modules)
        compilation.addSyntaxTree(slang::syntax::SyntaxTree::fromText(source, impl->source_manager, name + ".sv"));
    slang::Diagnostics errors, width_warnings;
    for (const auto& diagnostic : compilation.getAllDiagnostics()) {
        bool width = diagnostic.code == slang::diag::PortWidthExpand ||
            diagnostic.code == slang::diag::PortWidthTruncate || diagnostic.code == slang::diag::WidthExpand ||
            diagnostic.code == slang::diag::WidthTruncate || diagnostic.code == slang::diag::ConstantConversion;
        if (diagnostic.isError() || (strict && width)) errors.push_back(diagnostic);
        else if (width) width_warnings.push_back(diagnostic);
    }
    if (!errors.empty()) throw Error({"<design>"}, "E_SV", slang::DiagnosticEngine::reportAll(impl->source_manager, errors));
    if (!width_warnings.empty()) warnings.push_back({{"<design>"}, "W_WIDTH", slang::DiagnosticEngine::reportAll(impl->source_manager, width_warnings)});
}
} // namespace slip
