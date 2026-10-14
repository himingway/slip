#include "project.hpp"

#include <cctype>
#include <fstream>
#include <optional>
#include <set>

namespace slip::cli {
namespace {
std::string_view trim(std::string_view text) {
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front()))) text.remove_prefix(1);
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back()))) text.remove_suffix(1);
    return text;
}
std::string value(std::string_view text, const Location& loc) {
    text = trim(text);
    std::string result;
    if (!text.empty() && (text.front() == '"' || text.front() == '\'')) {
        const char quote = text.front();
        std::size_t i = 1;
        bool closed = false;
        for (; i < text.size(); ++i) {
            if (text[i] == quote) { ++i; closed = true; break; }
            if (quote == '"' && text[i] == '\\') {
                if (++i == text.size() || (text[i] != '\\' && text[i] != '"'))
                    throw Error(loc, "E_CONFIG", "quoted paths support only escaped quotes and backslashes");
            }
            result += text[i];
        }
        if (!closed) throw Error(loc, "E_CONFIG", "unterminated quoted value");
        const auto tail = trim(text.substr(i));
        if (!tail.empty() && tail.front() != '#') throw Error(loc, "E_CONFIG", "unexpected text after quoted value");
    }
    else result = std::string(trim(text.substr(0, text.find('#'))));
    if (result.empty()) throw Error(loc, "E_CONFIG", "configuration values must not be empty");
    return result;
}
bool boolean(const std::string& text, const Location& loc) {
    if (text == "true") return true;
    if (text == "false") return false;
    throw Error(loc, "E_CONFIG", "expected true or false");
}
} // namespace

Project read_project(const std::filesystem::path& file) {
    std::error_code error;
    auto path = std::filesystem::absolute(file, error).lexically_normal();
    if (error) throw Error({file.string()}, "E_IO", "cannot resolve project configuration: " + error.message());
    if (!std::filesystem::is_regular_file(path, error))
        throw Error({path.string()}, "E_IO", "project configuration is not a readable regular file");
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw Error({path.string()}, "E_IO", "cannot read project configuration");
    const auto base = path.parent_path();
    Project project;
    project.loc.file = path.string();
    project.output = base / "build";
    bool strict = false;
    std::optional<bool> no_implicit, widths_as_errors;
    std::set<std::string> seen;
    std::string line;
    unsigned number = 0;
    std::size_t bytes = 0;
    while (std::getline(stream, line)) {
        Location loc{path.string(), ++number, 1};
        bytes += line.size() + 1;
        if (bytes > 1000000) throw Error(loc, "E_CONFIG", "project configuration exceeds 1 MB");
        if (line.find('\0') != std::string::npos) throw Error(loc, "E_CONFIG", "NUL bytes are not allowed in project configuration");
        auto text = trim(line);
        if (text.empty() || text.front() == '#') continue;
        loc.column = static_cast<unsigned>(text.data() - line.data() + 1);
        auto equal = text.find('=');
        if (equal == text.npos) throw Error(loc, "E_CONFIG", "expected key = value");
        const std::string key(trim(text.substr(0, equal)));
        if (key != "entry" && key != "out_dir" && key != "ip_dir" && key != "filelist" &&
            key != "strict" && key != "no_implicit" && key != "widths_as_errors")
            throw Error(loc, "E_CONFIG", "unknown project option '" + key + "'");
        if (key != "ip_dir" && key != "filelist" && !seen.insert(key).second)
            throw Error(loc, "E_CONFIG", "duplicate project option '" + key + "'");
        auto raw = trim(text.substr(equal + 1));
        auto value_loc = loc;
        value_loc.column += static_cast<unsigned>(raw.data() - text.data());
        const auto parsed = value(raw, value_loc);
        const auto resolved = (base / std::filesystem::path(parsed)).lexically_normal();
        if (key == "entry") {
            if (parsed == "-") throw Error(value_loc, "E_CONFIG", "project entry must be a file; pass '-' on the command line for stdin");
            project.entry = resolved.string();
        }
        else if (key == "out_dir") project.output = resolved;
        else if (key == "ip_dir") project.options.ip_dirs.push_back(resolved);
        else if (key == "filelist") project.options.filelists.push_back(resolved);
        else if (key == "strict") strict = boolean(parsed, value_loc);
        else if (key == "no_implicit") no_implicit = boolean(parsed, value_loc);
        else if (key == "widths_as_errors") widths_as_errors = boolean(parsed, value_loc);
    }
    if (stream.bad()) throw Error({path.string()}, "E_IO", "cannot read project configuration");
    // Independent settings take precedence over the strict shorthand, regardless
    // of key order. Keep Options::strict clear so false overrides stay effective.
    project.options.no_implicit = no_implicit.value_or(strict);
    project.options.widths_as_errors = widths_as_errors.value_or(strict);
    return project;
}
} // namespace slip::cli
