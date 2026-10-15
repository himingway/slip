#include "internal.hpp"

#include <algorithm>
#include <fstream>
#include <set>
#include <sstream>

namespace slip {
namespace {
std::string json(std::string_view text) {
    std::string result = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char ch : text) {
        if (ch == '"' || ch == '\\') { result += '\\'; result += ch; }
        else if (ch < 32) { result += "\\u00"; result += hex[ch >> 4]; result += hex[ch & 15]; }
        else result += ch;
    }
    return result + '"';
}
std::string fingerprint(std::string_view text) {
    std::uint64_t hash = 14695981039346656037ull;
    for (unsigned char ch : text) { hash ^= ch; hash *= 1099511628211ull; }
    std::ostringstream result;
    result << std::hex << hash << '-' << std::dec << text.size();
    return result.str();
}
bool owned_name(const std::string& name) {
    if (name.empty() || std::filesystem::path(name).filename() != name || name == "." || name == "..") return false;
    return name.ends_with(".sv") || name == "sources.f" || name == "slip.d" || name == "source-map.json" || name == ".slip-build-stamp";
}
std::filesystem::file_status state(const std::filesystem::path& file) {
    std::error_code error;
    const auto result = std::filesystem::symlink_status(file, error);
    if (error && error != std::errc::no_such_file_or_directory)
        throw Error({file.string()}, "E_IO", "cannot inspect output path: " + error.message());
    return result;
}
void require_regular_or_missing(const std::filesystem::path& file) {
    const auto status = state(file);
    if (std::filesystem::exists(status) && !std::filesystem::is_regular_file(status))
        throw Error({file.string()}, "E_IO", "output path must be a regular file (directories and symlinks are not overwritten)");
}
std::string quote_filelist(std::string_view value) {
    std::string result = "\"";
    for (char ch : value) {
        if (ch == '\n' || ch == '\r' || ch == '\0') throw Error({}, "E_IO", "filelist paths cannot contain newline or NUL");
        if (ch == '\\' || ch == '"' || ch == '$') result += '\\';
        result += ch;
    }
    return result + '"';
}
std::string make_escape(std::string_view value) {
    std::string result;
    for (char ch : value) {
        if (ch == '\n' || ch == '\r') throw Error({}, "E_IO", "dependency paths cannot contain newlines");
        if (ch == '$') result += '$';
        else if (ch == ' ' || ch == '\t' || ch == '#' || ch == ':' || ch == '\\') result += '\\';
        result += ch;
    }
    return result;
}
struct TemporaryDirectory {
    std::filesystem::path path;
    ~TemporaryDirectory() { std::error_code ignored; if (!path.empty()) std::filesystem::remove_all(path, ignored); }
};
} // namespace

void write_outputs(const Result& result, const std::filesystem::path& directory) {
    std::error_code error;
    std::filesystem::create_directories(directory, error);
    if (error) throw Error({directory.string()}, "E_IO", "cannot create output directory: " + error.message());
    // Serialize publishers to a directory; independent compilations still run concurrently.
    const auto lock_path = directory / ".slip-lock";
    if (!std::filesystem::create_directory(lock_path, error))
        throw Error({lock_path.string()}, "E_OUTPUT_BUSY", error ? error.message() : "another build owns this output directory; remove a stale .slip-lock after an interrupted process");
    TemporaryDirectory lock{lock_path};
    const auto manifest_file = directory / ".slip-manifest";
    require_regular_or_missing(manifest_file);
    std::map<std::string, std::string> previous;
    if (std::filesystem::is_regular_file(state(manifest_file))) {
        std::istringstream manifest(read_file(manifest_file));
        std::string line;
        if (!std::getline(manifest, line) || line != "slip-manifest 1")
            throw Error({manifest_file.string()}, "E_OUTPUT_MANIFEST", "invalid generated output manifest");
        while (std::getline(manifest, line)) {
            const auto tab = line.find('\t');
            if (tab == line.npos || !owned_name(line.substr(tab + 1)) || !previous.emplace(line.substr(tab + 1), line.substr(0, tab)).second)
                throw Error({manifest_file.string()}, "E_OUTPUT_MANIFEST", "invalid generated output manifest entry");
        }
    }
    std::map<std::string, std::string> outputs;
    std::vector<std::string> order = result.module_order;
    if (order.empty()) for (const auto& [name, source] : result.modules) { (void)source; order.push_back(name); }
    for (const auto& [name, source] : result.modules) {
        const auto file = name + ".sv";
        if (!owned_name(file)) throw Error({directory.string()}, "E_IO", "invalid generated module filename");
        outputs[file] = source;
    }
    std::string filelist;
    for (const auto& include : result.include_dirs) filelist += "+incdir+" + quote_filelist(include) + '\n';
    for (const auto& define : result.defines) filelist += "+define+" + quote_filelist(define) + '\n';
    for (const auto& source : result.sv_sources) filelist += quote_filelist(source) + '\n';
    for (const auto& name : order)
        filelist += quote_filelist(std::filesystem::absolute(directory / (name + ".sv")).lexically_normal().string()) + '\n';
    outputs["sources.f"] = std::move(filelist);

    outputs[".slip-build-stamp"] = "Slip build completed successfully.\n";
    std::string dependencies = make_escape(std::filesystem::absolute(directory / ".slip-build-stamp").lexically_normal().string()) + ' ';
    for (const auto& name : order) dependencies += make_escape(std::filesystem::absolute(directory / (name + ".sv")).lexically_normal().string()) + ' ';
    dependencies += make_escape(std::filesystem::absolute(manifest_file).lexically_normal().string()) + ':';
    std::set<std::filesystem::path> inputs(result.dependencies.begin(), result.dependencies.end());
    for (const auto& input : inputs) dependencies += " \\\n  " + make_escape(input.string());
    dependencies += '\n';
    outputs["slip.d"] = std::move(dependencies);

    std::string maps = "{\"schema_version\":1,\"files\":[";
    bool first_file = true;
    for (const auto& [name, lines] : result.source_maps) {
        if (!first_file) maps += ',';
        first_file = false;
        maps += "{\"generated\":" + json(name + ".sv") + ",\"lines\":[";
        for (std::size_t i = 0; i < lines.size(); ++i) {
            if (i) maps += ',';
            const auto& loc = lines[i];
            maps += "{\"generated_line\":" + std::to_string(i + 1) + ",\"file\":" + json(loc.file) +
                ",\"line\":" + std::to_string(loc.line) + ",\"column\":" + std::to_string(loc.column);
            if (!loc.expansion.empty()) maps += ",\"expansion\":" + json(loc.expansion);
            maps += '}';
        }
        maps += "]}";
    }
    outputs["source-map.json"] = maps + "]}\n";

    std::string manifest = "slip-manifest 1\n";
    for (const auto& [name, text] : outputs) manifest += fingerprint(text) + '\t' + name + '\n';
    outputs[".slip-manifest"] = std::move(manifest);
    std::vector<std::string> changed, obsolete;
    // Validate every destination before staging or publishing any new output.
    for (const auto& [name, text] : outputs) {
        const auto file = directory / name;
        require_regular_or_missing(file);
        if (std::filesystem::is_regular_file(state(file))) {
            const auto existing = read_file(file);
            if (existing == text) continue;
            if (const auto old = previous.find(name); old != previous.end() && fingerprint(existing) != old->second)
                throw Error({file.string()}, "E_OUTPUT_MODIFIED", "generated file was edited; move the edited file before rebuilding");
        }
        changed.push_back(name);
    }
    for (const auto& [name, hash] : previous) {
        if (outputs.contains(name)) continue;
        const auto file = directory / name;
        // An edited file or a symlink is now user-owned: leave it alone.
        if (std::filesystem::is_regular_file(state(file)) && fingerprint(read_file(file)) == hash) obsolete.push_back(name);
    }
    const auto stage_path = lock_path / "staged";
    std::filesystem::create_directory(stage_path, error);
    if (error) throw Error({stage_path.string()}, "E_IO", "cannot stage outputs: " + error.message());
    for (const auto& name : changed) {
        std::ofstream stream(stage_path / name, std::ios::binary | std::ios::trunc);
        stream << outputs.at(name);
        stream.close();
        if (!stream) throw Error({(directory / name).string()}, "E_IO", "cannot stage output");
    }
    // The manifest is the commit record and is published last.
    std::stable_sort(changed.begin(), changed.end(), [](const auto& a, const auto& b) { return (a != ".slip-manifest") > (b != ".slip-manifest"); });
    for (const auto& name : changed) {
        if (name == ".slip-manifest") continue;
        std::filesystem::rename(stage_path / name, directory / name, error);
        if (error) throw Error({(directory / name).string()}, "E_IO", "cannot publish output: " + error.message());
    }
    for (const auto& name : obsolete) {
        std::filesystem::remove(directory / name, error);
        if (error) throw Error({(directory / name).string()}, "E_IO", "cannot remove stale output: " + error.message());
    }
    if (std::find(changed.begin(), changed.end(), ".slip-manifest") != changed.end()) {
        std::filesystem::rename(stage_path / ".slip-manifest", manifest_file, error);
        if (error) throw Error({manifest_file.string()}, "E_IO", "cannot publish manifest: " + error.message());
    }
    // The success stamp is the generator target for timestamp-based build tools.
    // Touch it even when SV contents are identical; do not rewrite those outputs.
    const auto stamp = directory / ".slip-build-stamp";
    std::filesystem::last_write_time(stamp, std::filesystem::file_time_type::clock::now(), error);
    if (error) throw Error({stamp.string()}, "E_IO", "cannot update build stamp: " + error.message());
}
} // namespace slip
