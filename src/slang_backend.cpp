#include "internal.hpp"

#include <slang/ast/Compilation.h>
#include <slang/analysis/AnalysisManager.h>
#include <slang/ast/symbols/InstanceSymbols.h>
#include <slang/ast/symbols/ParameterSymbols.h>
#include <slang/ast/symbols/PortSymbols.h>
#include <slang/ast/symbols/MemberSymbols.h>
#include <slang/ast/symbols/VariableSymbols.h>
#include <slang/ast/symbols/CompilationUnitSymbols.h>
#include <slang/ast/types/DeclaredType.h>
#include <slang/ast/types/Type.h>
#include <slang/diagnostics/DiagnosticEngine.h>
#include <slang/diagnostics/AllDiags.h>
#include <slang/parsing/Preprocessor.h>
#include <slang/parsing/ParserMetadata.h>
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
    std::unique_ptr<slang::ast::Compilation> reflection;
    std::string ip_file;
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
    impl->ip_file = sources.files.front();
    for (const auto& file : sources.files)
        if (!std::filesystem::is_regular_file(file)) throw Error({file}, "E_IO", "filelist source is not a readable regular file");
    slang::parsing::PreprocessorOptions preprocessor;
    for (const auto& include : sources.includes) preprocessor.additionalIncludePaths.emplace_back(include);
    preprocessor.predefines = sources.defines;
    std::vector<std::string_view> paths(sources.files.begin(), sources.files.end());
    auto tree = slang::syntax::SyntaxTree::fromFiles(paths, impl->source_manager, slang::Bag{preprocessor});
    if (!tree) throw Error({impl->ip_file}, "E_IP", "cannot parse IP files");
    impl->ip_tree = *tree;
    slang::Diagnostics errors;
    for (const auto& diagnostic : impl->ip_tree->diagnostics()) if (diagnostic.isError()) errors.push_back(diagnostic);
    if (!errors.empty()) throw Error({impl->ip_file}, "E_IP", slang::DiagnosticEngine::reportAll(impl->source_manager, errors));
    impl->reflection = std::make_unique<slang::ast::Compilation>();
    impl->reflection->addSyntaxTree(impl->ip_tree);
    for (const auto* definition : impl->reflection->getDefinitions()) {
        if (!ip_names.insert(std::string(definition->name)).second) throw Error({impl->ip_file}, "E_DUPLICATE", "duplicate IP module");
        if (definition->kind == slang::ast::SymbolKind::Definition && definition->as<slang::ast::DefinitionSymbol>().definitionKind == slang::ast::DefinitionKind::Interface)
            interface_names.insert(std::string(definition->name));
    }
}
const Interface* Backend::reflect(const std::string& name) {
    if (auto found = ips.find(name); found != ips.end()) return &found->second;
    if (!ip_names.contains(name)) return nullptr;
    auto& compilation = *impl->reflection;
    const auto& root = compilation.getRoot();
    const slang::ast::Symbol* definition = nullptr;
    for (auto candidate : compilation.getDefinitions()) if (candidate->name == name) { definition = candidate; break; }
    if (!definition) return nullptr;
    const auto source = impl->source_manager.getFullyExpandedLoc(definition->location);
    const auto& path = impl->source_manager.getFullPath(source.buffer());
    const Location ip_loc{path.empty() ? impl->ip_file : path.string(), static_cast<unsigned>(impl->source_manager.getLineNumber(source)), static_cast<unsigned>(impl->source_manager.getColumnNumber(source))};
    auto instance = root.lookupName(name);
    const slang::ast::InstanceBodySymbol* reflected_body = nullptr;
    if (instance && instance->kind == slang::ast::SymbolKind::Instance)
        reflected_body = &instance->as<slang::ast::InstanceSymbol>().body;
    else if (definition->kind == slang::ast::SymbolKind::Definition)
        reflected_body = &slang::ast::InstanceSymbol::createDefault(compilation, definition->as<slang::ast::DefinitionSymbol>()).body;
    if (!reflected_body) return nullptr;
    const auto& body = *reflected_body;
    Interface interface;
    for (const auto& symbol : body.members()) {
        if (symbol.kind == slang::ast::SymbolKind::TypeParameter)
            throw Error(ip_loc, "E_IP", "type parameters are not supported by Slip: " + name);
        if (symbol.kind != slang::ast::SymbolKind::Parameter) continue;
        const auto& parameter = symbol.as<slang::ast::ParameterSymbol>();
        auto declared = symbol.getDeclaredType();
        auto initializer = declared ? declared->getInitializerSyntax() : nullptr;
        auto text = initializer ? trim(initializer->toString()) : parameter.getValue().toString();
        (parameter.isLocalParam() ? interface.localparams : interface.parameters).push_back({std::string(symbol.name), expression(ip_loc, Literal{text})});
    }
    for (const auto* symbol : body.getPortList()) {
        if (symbol->kind == slang::ast::SymbolKind::InterfacePort) {
            const auto& port = symbol->as<slang::ast::InterfacePortSymbol>();
            if (auto range = port.getDeclaredRange(); !range || !range->empty())
                throw Error(ip_loc, "E_INTERFACE", "interface port arrays are not supported: " + name + "." + std::string(port.name));
            InterfacePort info;
            info.name = std::string(port.name); info.direction = "interface"; info.native = true;
            if (port.interfaceDef) info.interface_type = std::string(port.interfaceDef->name);
            else if (!port.isGeneric) throw Error(ip_loc, "E_INTERFACE", "unresolved interface type at '" + name + "." + info.name + "'");
            info.modport = std::string(port.modport);
            interface.ports.push_back(std::move(info));
            continue;
        }
        if (symbol->kind != slang::ast::SymbolKind::Port)
            throw Error(ip_loc, "E_IP", "unsupported interface port in '" + name + "'");
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
    return &ips.emplace(name, std::move(interface)).first->second;
}

const NativeInterface& Backend::reflect_native(const std::string& name, Location loc) {
    if (auto found = native_interfaces.find(name); found != native_interfaces.end()) return found->second;
    if (!interface_names.contains(name)) throw Error(loc, "E_INTERFACE", "cannot resolve SV interface '" + name + "' (pass -ip/-f for its definition)");
    NativeInterface result;
    result.constructor = *reflect(name);
    for (const auto& port : result.constructor.ports) if (port.native)
        throw Error(loc, "E_INTERFACE", "nested interface constructor ports are not supported: " + name + "." + port.name);
    const slang::ast::DefinitionSymbol* definition = nullptr;
    for (auto candidate : impl->reflection->getDefinitions()) if (candidate->name == name && candidate->kind == slang::ast::SymbolKind::Definition) { definition = &candidate->as<slang::ast::DefinitionSymbol>(); break; }
    const auto& body = slang::ast::InstanceSymbol::createDefault(*impl->reflection, *definition).body;
    for (const auto& member : body.members()) {
        if (member.kind == slang::ast::SymbolKind::Variable || member.kind == slang::ast::SymbolKind::Net) {
            InterfacePort field; field.name = std::string(member.name);
            field.is_signed = member.as<slang::ast::ValueSymbol>().getType().isSigned();
            const auto* declared = member.getDeclaredType();
            field.width = packed_dimensions(declared->getTypeSyntax());
            if (auto dims = declared->getDimensionSyntax()) for (auto dim : *dims) field.array += trim(dim->toString());
            result.fields.push_back(std::move(field));
        } else if (member.kind == slang::ast::SymbolKind::Modport) {
            auto& fields = result.modports[std::string(member.name)];
            for (const auto& item : member.as<slang::ast::ModportSymbol>().members()) {
                if (item.kind != slang::ast::SymbolKind::ModportPort) {
                    result.unsupported_modports[std::string(member.name)] = "clocking and imported/exported tasks or functions";
                    continue;
                }
                const auto& port = item.as<slang::ast::ModportPortSymbol>();
                if (port.explicitConnection || !port.internalSymbol || port.internalSymbol->name != port.name) {
                    result.unsupported_modports[std::string(member.name)] = "modport expressions and renamed fields";
                    continue;
                }
                fields.emplace(std::string(port.name), port.direction == slang::ast::ArgumentDirection::In ? "input" :
                    port.direction == slang::ast::ArgumentDirection::Out ? "output" : port.direction == slang::ast::ArgumentDirection::InOut ? "inout" : "ref");
                if (port.direction == slang::ast::ArgumentDirection::Ref)
                    result.unsupported_modports[std::string(member.name)] = "ref modport fields";
            }
        }
    }
    return native_interfaces.emplace(name, std::move(result)).first->second;
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

void Backend::validate(const std::map<std::string, std::string>& modules, const SourceMaps& source_maps,
                       bool widths_as_errors, std::vector<Diagnostic>& warnings, bool native_interfaces) {
    if (modules.empty()) return;
    std::vector<std::shared_ptr<slang::syntax::SyntaxTree>> trees;
    std::set<std::string> referenced;
    std::map<slang::BufferID, const std::vector<Location>*> origins;
    for (const auto& [name, source] : modules) {
        auto tree = slang::syntax::SyntaxTree::fromText(source, impl->source_manager, name + ".sv");
        for (auto buffer : tree->getSourceBufferIds()) origins.emplace(buffer, &source_maps.at(name));
        for (auto instance : tree->getMetadata().globalInstances) referenced.insert(std::string(instance->type.valueText()));
        trees.push_back(std::move(tree));
    }
    slang::ast::CompilationOptions settings;
    for (const auto& [name, source] : modules) { (void)source; if (!referenced.contains(name)) settings.topModules.insert(name); }
    slang::ast::Compilation compilation(slang::Bag{settings});
    if (impl->ip_tree) compilation.addSyntaxTree(impl->ip_tree);
    for (auto& tree : trees) compilation.addSyntaxTree(tree);

    auto locate = [&](slang::SourceLocation source) {
        if (!source.valid()) return Location{"<design>"};
        source = impl->source_manager.getFullyExpandedLoc(source);
        auto line = impl->source_manager.getLineNumber(source);
        if (auto found = origins.find(source.buffer()); found != origins.end() && line > 0 && line <= found->second->size())
            return found->second->at(line - 1);
        return Location{std::string(impl->source_manager.getFileName(source)), static_cast<unsigned>(line),
                        static_cast<unsigned>(impl->source_manager.getColumnNumber(source))};
    };
    slang::DiagnosticEngine engine(impl->source_manager);
    auto describe = [&](const slang::Diagnostic& diagnostic) {
        std::string message = engine.formatMessage(diagnostic);
        for (const auto& note : diagnostic.notes) {
            auto loc = locate(note.location);
            message += "\nnote: " + loc.file + ':' + std::to_string(loc.line) + ':' + std::to_string(loc.column) + ": " + engine.formatMessage(note);
            if (!loc.expansion.empty()) message += " (expanded with " + loc.expansion + ")";
        }
        return message;
    };
    std::vector<Diagnostic> errors;
    for (const auto& diagnostic : compilation.getAllDiagnostics()) {
        bool width = diagnostic.code == slang::diag::PortWidthExpand ||
            diagnostic.code == slang::diag::PortWidthTruncate || diagnostic.code == slang::diag::WidthExpand ||
            diagnostic.code == slang::diag::WidthTruncate || diagnostic.code == slang::diag::ConstantConversion;
        if (diagnostic.isError() || (widths_as_errors && width)) errors.push_back({locate(diagnostic.location), "E_SV", describe(diagnostic)});
        else if (width) warnings.push_back({locate(diagnostic.location), "W_WIDTH", describe(diagnostic)});
    }
    if (!errors.empty()) {
        auto message = errors.front().message;
        for (std::size_t i = 1; i < errors.size(); ++i) {
            const auto& error = errors[i];
            message += "\n" + error.loc.file + ':' + std::to_string(error.loc.line) + ':' + std::to_string(error.loc.column) + ": " + error.message;
            if (!error.loc.expansion.empty()) message += " (expanded with " + error.loc.expansion + ")";
        }
        throw Error(errors.front().loc, "E_SV", std::move(message));
    }
    // Analyze elaborated RTL so full case coverage, selects, loops and IP drivers
    // follow SystemVerilog semantics. Only report these checks for generated Slip.
    compilation.freeze();
    slang::analysis::AnalysisOptions analysis_options;
    analysis_options.flags = slang::analysis::AnalysisFlags::CheckUnused;
    analysis_options.numThreads = 1;
    analysis_options.maxCaseAnalysisSteps = 10000;
    analysis_options.maxLoopAnalysisSteps = 10000;
    slang::analysis::AnalysisManager analysis(analysis_options);
    analysis.analyze(compilation);
    for (const auto& diagnostic : analysis.getDiagnostics()) {
        const auto source = impl->source_manager.getFullyExpandedLoc(diagnostic.location);
        if (native_interfaces && (diagnostic.code == slang::diag::MultipleContAssigns ||
            diagnostic.code == slang::diag::MultipleAlwaysAssigns || diagnostic.code == slang::diag::MultipleUWireDrivers ||
            diagnostic.code == slang::diag::MultipleUDNTDrivers))
            throw Error(locate(diagnostic.location), "E_MULTIPLE_DRIVERS", describe(diagnostic));
        if (!origins.contains(source.buffer())) continue;
        if (diagnostic.code == slang::diag::MissingReturn || diagnostic.code == slang::diag::IncompleteReturn)
            throw Error(locate(diagnostic.location), "E_FUNCTION", describe(diagnostic));
        if (diagnostic.code == slang::diag::InferredLatch)
            warnings.push_back({locate(diagnostic.location), "W_LATCH", describe(diagnostic) +
                "; assign a default value in comb or cover every branch"});
        else if (diagnostic.code == slang::diag::UnassignedVariable || diagnostic.code == slang::diag::UndrivenNet ||
                 diagnostic.code == slang::diag::UndrivenPort)
            warnings.push_back({locate(diagnostic.location), "W_UNDRIVEN", describe(diagnostic)});
    }
    compilation.unfreeze();
}
} // namespace slip
