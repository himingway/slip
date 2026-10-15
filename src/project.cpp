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

Project read_project(const std::filesystem::path& file, const std::string& profile) {
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
    struct Setting { Location loc; std::string key, value; };
    std::map<std::string, std::vector<Setting>> sections;
    std::map<std::string, std::set<std::string>> seen;
    std::string section;
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
        if (text.front() == '[') {
            if (!text.starts_with("[profile.") || text.back() != ']')
                throw Error(loc, "E_CONFIG", "expected [profile.NAME] section");
            section = std::string(text.substr(9, text.size() - 10));
            if (section.empty() || section.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != section.npos)
                throw Error(loc, "E_CONFIG", "invalid profile name");
            if (sections.contains(section)) throw Error(loc, "E_CONFIG", "duplicate profile '" + section + "'");
            sections[section] = {};
            continue;
        }
        auto equal = text.find('=');
        if (equal == text.npos) throw Error(loc, "E_CONFIG", "expected key = value");
        const std::string key(trim(text.substr(0, equal)));
        if (key != "entry" && key != "out_dir" && key != "ip_dir" && key != "filelist" && key != "top" &&
            key != "strict" && key != "no_implicit" && key != "widths_as_errors" && key != "no_implicit_ports" &&
            key != "no_implicit_signals" && key != "warnings_as_errors" && !key.starts_with("param.") && !key.starts_with("warning."))
            throw Error(loc, "E_CONFIG", "unknown project option '" + key + "'");
        if (key != "ip_dir" && key != "filelist" && !seen[section].insert(key).second)
            throw Error(loc, "E_CONFIG", "duplicate project option '" + key + "'");
        auto raw = trim(text.substr(equal + 1));
        auto value_loc = loc;
        value_loc.column += static_cast<unsigned>(raw.data() - text.data());
        const auto parsed = value(raw, value_loc);
        if (key == "strict" || key == "no_implicit" || key == "widths_as_errors" || key == "no_implicit_ports" ||
            key == "no_implicit_signals" || key == "warnings_as_errors") boolean(parsed, value_loc);
        if ((key.starts_with("param.") || key.starts_with("warning.")) && key.back() == '.')
            throw Error(loc, "E_CONFIG", "missing parameter or diagnostic name");
        if (key.starts_with("warning.") && parsed != "error" && parsed != "warning" && parsed != "off")
            throw Error(loc, "E_CONFIG", "warning severity must be error, warning or off");
        sections[section].push_back({value_loc, key, parsed});
    }
    if (stream.bad()) throw Error({path.string()}, "E_IO", "cannot read project configuration");
    if (!profile.empty() && !sections.contains(profile))
        throw Error({path.string()}, "E_CONFIG", "unknown project profile '" + profile + "'");
    std::vector<Setting> settings = sections[""];
    if (!profile.empty()) settings.insert(settings.end(), sections[profile].begin(), sections[profile].end());
    // Scalar profile settings replace defaults, including strict's independent overrides.
    std::map<std::string, Setting> scalars;
    for (const auto& setting : settings) {
        const auto& key = setting.key;
        if (key == "ip_dir") project.options.ip_dirs.push_back((base / setting.value).lexically_normal());
        else if (key == "filelist") project.options.filelists.push_back((base / setting.value).lexically_normal());
        else scalars.insert_or_assign(key, setting);
    }
    for (const auto& [key, setting] : scalars) {
        const auto& parsed = setting.value;
        const auto resolved = (base / std::filesystem::path(parsed)).lexically_normal();
        if (key == "entry") {
            if (parsed == "-") throw Error(setting.loc, "E_CONFIG", "project entry must be a file; pass '-' on the command line for stdin");
            project.entry = resolved.string();
        }
        else if (key == "out_dir") project.output = resolved;
        else if (key == "top") project.options.top = parsed;
        else if (key == "no_implicit_ports") project.options.no_implicit_ports = boolean(parsed, setting.loc);
        else if (key == "no_implicit_signals") project.options.no_implicit_signals = boolean(parsed, setting.loc);
        else if (key == "warnings_as_errors") project.options.warnings_as_errors = boolean(parsed, setting.loc);
        else if (key.starts_with("param.")) project.options.parameter_overrides[key.substr(6)] = parsed;
        else if (key.starts_with("warning.")) project.options.warning_levels[key.substr(8)] = parsed;
    }
    const bool strict = scalars.contains("strict") && boolean(scalars.at("strict").value, scalars.at("strict").loc);
    project.options.no_implicit = scalars.contains("no_implicit") ? boolean(scalars.at("no_implicit").value, scalars.at("no_implicit").loc) : strict;
    project.options.widths_as_errors = scalars.contains("widths_as_errors") ? boolean(scalars.at("widths_as_errors").value, scalars.at("widths_as_errors").loc) : strict;
    if (scalars.contains("no_implicit_ports") || scalars.contains("no_implicit_signals")) {
        const bool base = project.options.no_implicit;
        project.options.no_implicit_ports = scalars.contains("no_implicit_ports") ? project.options.no_implicit_ports : base;
        project.options.no_implicit_signals = scalars.contains("no_implicit_signals") ? project.options.no_implicit_signals : base;
        project.options.no_implicit = false;
    }
    return project;
}
} // namespace slip::cli
