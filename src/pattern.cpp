#include "internal.hpp"
#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>

namespace slip {
struct Pattern::Impl {
    Location loc;
    std::unique_ptr<pcre2_code, decltype(&pcre2_code_free)> code{nullptr, pcre2_code_free};
    std::unique_ptr<pcre2_match_context, decltype(&pcre2_match_context_free)> context{pcre2_match_context_create(nullptr), pcre2_match_context_free};
};
Pattern::Pattern(std::string_view source, Location loc) : impl(std::make_unique<Impl>()) {
    impl->loc = std::move(loc);
    if (source.size() > 65536) throw Error(impl->loc, "E_LIMIT", "regex pattern size limit exceeded");
    int error = 0; PCRE2_SIZE offset = 0;
    impl->code.reset(pcre2_compile(reinterpret_cast<PCRE2_SPTR>(source.data()), source.size(), PCRE2_ANCHORED | PCRE2_ENDANCHORED, &error, &offset, nullptr));
    if (!impl->code) {
        PCRE2_UCHAR message[256]; pcre2_get_error_message(error, message, sizeof(message));
        throw Error(impl->loc, "E_REGEX", "invalid regex at offset " + std::to_string(offset) + ": " + reinterpret_cast<const char*>(message));
    }
    if (!impl->context) throw std::bad_alloc();
    pcre2_set_match_limit(impl->context.get(), 100000);
    pcre2_set_depth_limit(impl->context.get(), 128);
    pcre2_set_heap_limit(impl->context.get(), 1024);
}
Pattern::~Pattern() = default;
Pattern::Pattern(Pattern&&) noexcept = default;
Pattern& Pattern::operator=(Pattern&&) noexcept = default;
std::optional<std::vector<std::string>> Pattern::match(std::string_view text) const {
    auto data = std::unique_ptr<pcre2_match_data, decltype(&pcre2_match_data_free)>{pcre2_match_data_create_from_pattern(impl->code.get(), nullptr), pcre2_match_data_free};
    if (!data) throw std::bad_alloc();
    auto result = pcre2_match(impl->code.get(), reinterpret_cast<PCRE2_SPTR>(text.data()), text.size(), 0, 0, data.get(), impl->context.get());
    if (result == PCRE2_ERROR_NOMATCH) return {};
    if (result < 0) throw Error(impl->loc, "E_REGEX", "regex matching exceeded resource limits or failed (" + std::to_string(result) + ")");
    std::vector<std::string> captures;
    auto offsets = pcre2_get_ovector_pointer(data.get());
    for (std::size_t i = 0; i < pcre2_get_ovector_count(data.get()); ++i)
        captures.push_back(offsets[i * 2] == PCRE2_UNSET ? "" : std::string(text.substr(offsets[i * 2], offsets[i * 2 + 1] - offsets[i * 2])));
    return captures;
}
} // namespace slip
