#pragma once

#include "slip/compiler.hpp"
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <sstream>
#include <stdexcept>

namespace test {
struct Case { std::string name; void (*run)(); };
std::vector<Case>& cases();
struct Register {
    Register(std::string name, void (*run)()) { cases().push_back({std::move(name), run}); }
};
inline void check(bool value, std::string_view expression, std::string_view file, unsigned line) {
    if (!value) throw std::runtime_error(std::string(file) + ':' + std::to_string(line) + ": " + std::string(expression));
}
inline void contains(std::string_view text, std::string_view expected) {
    if (text.find(expected) == text.npos)
        throw std::runtime_error("Expected " + std::string(expected) + " in:\n" + std::string(text));
}
template<class F> slip::Error error(F&& action, std::string_view code, std::string_view message = {}) {
    try { action(); }
    catch (const slip::Error& e) {
        if (e.code != code) throw std::runtime_error("Expected " + std::string(code) + ", got " + e.what());
        contains(e.message, message);
        return e;
    }
    throw std::runtime_error("Expected error " + std::string(code));
}
inline std::string module(std::string_view source, std::string_view name = "m", bool strict = false) {
    slip::Options options; options.strict = strict;
    return slip::compile(source, "regression.slip", options).modules.at(std::string(name));
}
inline slip::Error rejected(std::string_view source, std::string_view code,
                           std::string_view message = {}, const slip::Options& options = {}) {
    return error([&] { slip::compile(source, "regression.slip", options); }, code, message);
}
class Directory {
    std::filesystem::path directory;
public:
    Directory() {
        static std::atomic<unsigned> sequence{0};
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        for (unsigned attempt = 0; attempt < 100; ++attempt) {
            directory = std::filesystem::temp_directory_path() /
                ("slip-test-" + std::to_string(stamp) + '-' + std::to_string(sequence++));
            if (std::filesystem::create_directory(directory)) return;
        }
        throw std::runtime_error("Unable to create a temporary test directory");
    }
    Directory(const Directory&) = delete;
    Directory& operator=(const Directory&) = delete;
    ~Directory() { std::error_code ignored; std::filesystem::remove_all(directory, ignored); }
    const auto& path() const { return directory; }
    std::filesystem::path write(std::string_view name, std::string_view contents) const {
        auto file = directory / name;
        std::filesystem::create_directories(file.parent_path());
        std::ofstream stream(file, std::ios::binary);
        stream << contents;
        if (!stream) throw std::runtime_error("Unable to write " + file.string());
        return file;
    }
};
inline std::string function_source(std::string_view expression) {
    return "defun f(s):\n    return " + std::string(expression) +
        "\nmodule leaf(p_x) { logic p_x; }\nmodule m { leaf u { \"p_(.*)\" => \"v_$f(\\1)\" }; }\n";
}
inline void function_value(std::string_view expression, std::string_view expected) {
    contains(module(function_source("\"ok\" if (" + std::string(expression) + ")==(" +
        std::string(expected) + ") else \"bad\"")), ".p_x(v_ok)");
}
} // namespace test

#define CHECK(value) ::test::check(bool(value), #value, __FILE__, __LINE__)
#define TEST_CASE(name) \
    static void name(); \
    static const ::test::Register register_##name{#name, name}; \
    static void name()
