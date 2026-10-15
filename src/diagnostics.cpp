#include "internal.hpp"

#include <algorithm>
#include <sstream>

namespace slip {
namespace {
const std::set<std::string> warning_codes = {
    "W_IMPLICIT", "W_REGEX_UNUSED", "W_SEQ_CONVERSION", "W_UNCONNECTED",
    "W_LATCH", "W_UNDRIVEN", "W_WIDTH"
};
struct Suppression { std::string code; unsigned first, last; };
struct Directive { Location loc; std::string operation; std::vector<std::string> codes; };
std::vector<Suppression> suppressions(std::string_view source, const std::string& file) {
    std::vector<Directive> directives;
    std::vector<unsigned> executable_lines;
    unsigned line = 1, block = 0;
    bool string = false, code = false;
    for (std::size_t i = 0; i < source.size();) {
        if (source[i] == '\n') { if (code) executable_lines.push_back(line); ++line; code = false; ++i; continue; }
        const auto pair = source.substr(i, 2);
        if (block) {
            if (pair == "/*") { ++block; i += 2; }
            else if (pair == "*/") { --block; i += 2; }
            else ++i;
            continue;
        }
        if (string) {
            if (source[i] == '\\' && i + 1 < source.size()) i += 2;
            else { if (source[i] == '"') string = false; ++i; }
            continue;
        }
        if (pair == "/*") { ++block; i += 2; continue; }
        if (pair == "//") {
            const auto end = source.find('\n', i);
            auto comment = trim(source.substr(i + 2, end == source.npos ? source.size() - i - 2 : end - i - 2));
            if (comment.starts_with("slip:")) {
                std::istringstream text(comment.substr(5));
                Directive directive{{file, line, 1}, {}, {}};
                text >> directive.operation;
                if (directive.operation != "waive" && directive.operation != "disable" && directive.operation != "enable")
                    throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "expected slip: waive, disable or enable");
                std::string remainder; std::getline(text, remainder);
                const auto reason = remainder.find("--");
                if (directive.operation != "enable" && (reason == remainder.npos || trim(std::string_view(remainder).substr(reason + 2)).empty()))
                    throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "a waiver requires '-- reason'");
                auto names = remainder.substr(0, reason);
                std::replace(names.begin(), names.end(), ',', ' ');
                std::istringstream codes(names); std::string name;
                while (codes >> name) {
                    if (!warning_codes.contains(name)) throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "unknown warning code '" + name + "'");
                    directive.codes.push_back(name);
                }
                if (directive.codes.empty()) throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "a waiver requires at least one warning code");
                directives.push_back(std::move(directive));
            }
            i = end == source.npos ? source.size() : end;
            continue;
        }
        if (source[i] == '"') string = true;
        if (source[i] != ' ' && source[i] != '\t' && source[i] != '\r') code = true;
        ++i;
    }
    if (code) executable_lines.push_back(line);
    std::vector<Suppression> result;
    std::map<std::string, unsigned> disabled;
    for (const auto& directive : directives) for (const auto& name : directive.codes) {
        if (directive.operation == "waive") {
            const auto next = std::lower_bound(executable_lines.begin(), executable_lines.end(), directive.loc.line);
            if (next == executable_lines.end()) throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "waiver has no following statement");
            result.push_back({name, *next, *next});
        } else if (directive.operation == "disable") {
            if (!disabled.emplace(name, directive.loc.line).second) throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "warning '" + name + "' is already disabled");
        } else {
            auto start = disabled.find(name);
            if (start == disabled.end()) throw Error(directive.loc, "E_DIAGNOSTIC_CONFIG", "warning '" + name + "' was not disabled");
            result.push_back({name, start->second, directive.loc.line - 1});
            disabled.erase(start);
        }
    }
    for (const auto& [name, first] : disabled) result.push_back({name, first, line});
    return result;
}
} // namespace
void apply_diagnostic_policy(Result& result, const Options& options,
                             const std::map<std::string, std::string>& sources) {
    for (const auto& [code, level] : options.warning_levels) {
        if (!warning_codes.contains(code)) throw Error({"<warning-policy>"}, "E_CONFIG", "unknown warning code '" + code + "'");
        if (level != "error" && level != "warning" && level != "off")
            throw Error({"<warning-policy>"}, "E_CONFIG", "warning severity must be error, warning or off");
    }
    std::map<std::string, std::vector<Suppression>> waived;
    for (const auto& [file, text] : sources) waived[file] = suppressions(text, file);
    std::vector<Diagnostic> errors;
    std::erase_if(result.warnings, [&](const auto& diagnostic) {
        const auto found = waived.find(diagnostic.loc.file);
        if (found != waived.end() && std::any_of(found->second.begin(), found->second.end(), [&](const auto& item) {
            return item.code == diagnostic.code && item.first <= diagnostic.loc.line && diagnostic.loc.line <= item.last;
        })) return true;
        auto level = options.warning_levels.find(diagnostic.code);
        if (level != options.warning_levels.end() && level->second == "off") return true;
        if (level != options.warning_levels.end() ? level->second == "error" : options.warnings_as_errors) {
            errors.push_back(diagnostic);
            return true;
        }
        return false;
    });
    if (!errors.empty()) {
        std::string message;
        for (const auto& diagnostic : errors) {
            if (!message.empty()) message += '\n';
            message += diagnostic.loc.file + ':' + std::to_string(diagnostic.loc.line) + ':' + std::to_string(diagnostic.loc.column) +
                ": [" + diagnostic.code + "] " + diagnostic.message;
        }
        throw Error(errors.front().loc, "E_WARNING_AS_ERROR", std::move(message));
    }
}
} // namespace slip
