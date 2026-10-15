#include "internal.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <sstream>

namespace slip {
namespace {
struct Word { std::string text; Location loc; std::vector<std::size_t> separators; };
void append_unique(std::vector<std::string>& items, std::string value) {
    if (std::find(items.begin(), items.end(), value) == items.end()) items.push_back(std::move(value));
}
std::vector<Word> words(std::string_view source, const std::string& file) {
    std::vector<Word> result;
    Location loc{file};
    std::size_t pos = 0;
    auto advance = [&] { if (source[pos++] == '\n') { ++loc.line; loc.column = 1; } else ++loc.column; };
    auto starts = [&](std::string_view text) { return source.substr(pos, text.size()) == text; };
    while (pos < source.size()) {
        if (std::isspace(static_cast<unsigned char>(source[pos]))) { advance(); continue; }
        if (starts("\\\n")) { advance(); advance(); continue; }
        if (starts("//") || source[pos] == '#') { while (pos < source.size() && source[pos] != '\n') advance(); continue; }
        if (starts("/*")) {
            const auto start = loc;
            advance(); advance();
            while (pos < source.size() && !starts("*/")) advance();
            if (pos == source.size()) throw Error(start, "E_FILELIST", "unterminated block comment");
            advance(); advance(); continue;
        }
        Word word{{}, loc, {}};
        char quote = 0;
        while (pos < source.size()) {
            const char ch = source[pos];
            if (!quote && std::isspace(static_cast<unsigned char>(ch))) break;
            if (!quote && starts("/*")) break;
            if (ch == '"' || (ch == '\'' && (quote == '\'' || word.text.empty() || word.text.ends_with('+') || word.text == "-I"))) {
                if (!quote) { quote = ch; advance(); continue; }
                if (quote == ch) { quote = 0; advance(); continue; }
            }
            if (ch == '\\' && quote != '\'') {
                advance();
                if (pos == source.size()) throw Error(loc, "E_FILELIST", "trailing backslash");
                if (source[pos] != '\n') word.text += source[pos];
                advance(); continue;
            }
            if (ch == '$' && quote != '\'') {
                const auto start = loc;
                advance();
                if (pos < source.size() && source[pos] == '$') { word.text += '$'; advance(); continue; }
                char close = 0;
                if (pos < source.size() && (source[pos] == '{' || source[pos] == '(')) { close = source[pos] == '{' ? '}' : ')'; advance(); }
                std::string name;
                while (pos < source.size() && (std::isalnum(static_cast<unsigned char>(source[pos])) || source[pos] == '_')) { name += source[pos]; advance(); }
                if (name.empty() || (close && (pos == source.size() || source[pos] != close)))
                    throw Error(start, "E_FILELIST", "expected $NAME, ${NAME} or $(NAME) environment variable");
                if (close) advance();
                const auto* value = std::getenv(name.c_str());
                if (!value) throw Error(start, "E_FILELIST", "environment variable '" + name + "' is not set");
                word.text += value;
                continue;
            }
            if (!quote && ch == '+') word.separators.push_back(word.text.size());
            word.text += ch; advance();
        }
        if (quote) throw Error(word.loc, "E_FILELIST", "unterminated quoted argument");
        if (word.text.empty()) throw Error(word.loc, "E_FILELIST", "empty filelist argument");
        result.push_back(std::move(word));
    }
    return result;
}
} // namespace

void SourceInputs::filelist(const std::filesystem::path& file) {
    const auto path = std::filesystem::weakly_canonical(file);
    if (active.size() >= 128) throw Error({path.string()}, "E_LIMIT", "filelist nesting limit exceeded");
    if (!active.insert(path).second) throw Error({path.string()}, "E_FILELIST", "circular filelist reference");
    dependencies.insert(path);
    const auto tokens = words(read_file(path), path.string());
    const auto resolve = [&](std::string_view value) { return std::filesystem::weakly_canonical(path.parent_path() / std::filesystem::path(value)); };
    for (std::size_t i = 0; i < tokens.size(); ++i) {
        const auto& token = tokens[i];
        const auto& text = token.text;
        auto argument = [&]() -> const std::string& {
            if (++i == tokens.size()) throw Error(token.loc, "E_FILELIST", "missing argument after '" + text + "'");
            return tokens[i].text;
        };
        auto plus_parts = [&](std::size_t offset, const auto& consume) {
            auto start = offset;
            bool any = false;
            for (const auto separator : token.separators) if (separator >= offset) {
                if (separator > start) { consume(text.substr(start, separator - start)); any = true; }
                start = separator + 1;
            }
            if (start < text.size()) { consume(text.substr(start)); any = true; }
            if (!any) throw Error(token.loc, "E_FILELIST", "missing value after '" + text + "'");
        };
        if (text == "-f" || text == "-F") filelist(resolve(argument()));
        else if (text.starts_with("-f") && text.size() > 2) filelist(resolve(text.substr(2)));
        else if (text == "-v") append_unique(files, resolve(argument()).string());
        else if (text == "-y") libraries.emplace_back(resolve(argument()), token.loc);
        else if (text.starts_with("+libext+")) {
            extensions.clear();
            plus_parts(8, [&](const auto& ext) {
                if (ext.front() != '.' || ext.find_first_of("/\\") != ext.npos)
                    throw Error(token.loc, "E_FILELIST", "library extensions must start with '.' and contain no path separators");
                append_unique(extensions, ext);
            });
        }
        else if (text.starts_with("+incdir+")) plus_parts(8, [&](const auto& value) { append_unique(includes, resolve(value).string()); });
        else if (text.starts_with("+define+")) plus_parts(8, [&](const auto& value) { append_unique(defines, value); });
        else if (text == "-I") append_unique(includes, resolve(argument()).string());
        else if (text.starts_with("-I")) append_unique(includes, resolve(text.substr(2)).string());
        else if (text == "-D") append_unique(defines, argument());
        else if (text.starts_with("-D")) append_unique(defines, text.substr(2));
        else if (text == "-sverilog" || text == "-sv") {} // All sources are parsed as SystemVerilog.
        else if (text.front() == '-' || text.front() == '+')
            throw Error(token.loc, "E_FILELIST", "unsupported filelist option '" + text + "'; remove simulator-only options or put them in the downstream invocation");
        else append_unique(files, resolve(text).string());
    }
    active.erase(path);
}
void SourceInputs::finish_libraries() {
    for (const auto& [directory, loc] : libraries) {
        if (!std::filesystem::is_directory(directory)) throw Error(loc, "E_FILELIST", "library directory does not exist: " + directory.string());
        dependencies.insert(directory);
        std::vector<std::string> found;
        for (const auto& entry : std::filesystem::directory_iterator(directory)) {
            const auto ext = entry.path().extension().string();
            if (entry.is_regular_file() && std::find(extensions.begin(), extensions.end(), ext) != extensions.end())
                found.push_back(std::filesystem::weakly_canonical(entry.path()).string());
        }
        std::sort(found.begin(), found.end());
        for (auto& file : found) append_unique(files, std::move(file));
    }
}
} // namespace slip
